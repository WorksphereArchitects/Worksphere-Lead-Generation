"""Company-scoped news discovery, classification, and persistence."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from applications.services.discovery import discover_company_news
from applications.services.discovery_relevance import (
    CLASSIFICATION_BATCH_SIZE,
    classify_articles,
)
from applications.services.public_errors import safe_error_summary
from applications.services.supabase_client import supabase

MAX_NEWS_CANDIDATES_PER_RUN = 10
_NEWS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="company-news")
logger = logging.getLogger(__name__)


class NewsError(Exception):
    """Base class for news pipeline errors that are safe to map to HTTP."""


class NewsRunConflict(NewsError):
    pass


class NewsProviderFailure(NewsError):
    pass


class NewsPersistenceFailure(NewsError):
    pass


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _company_aliases(company: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("aliases", "alternate_names", "company_aliases", "trade_names"):
        value = company.get(key)
        if isinstance(value, str):
            normalized = value.replace(";", "|").replace(",", "|").replace("\n", "|")
            aliases.extend(part.strip() for part in normalized.split("|"))
        elif isinstance(value, (list, tuple)):
            aliases.extend(str(part).strip() for part in value if part)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _insert_run(company_id: str, lookback_days: int) -> dict[str, Any]:
    payload = {
        "company_id": company_id,
        "status": "processing",
        "lookback_days": lookback_days,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "discovered_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        "classification_failed_count": 0,
        "persistence_failed_count": 0,
        "malformed_count": 0,
        "truncated_count": 0,
        "metadata": {"provider": "google_news_rss", "progress": {
            "stage": "queued",
            "completed": 0,
            "total": 0,
            "reused": 0,
        }},
    }
    try:
        response = (
            supabase.table("news_ingestion_runs")
            .insert(payload)
            .select("*")
            .execute()
        )
    except Exception as error:
        if getattr(error, "code", None) == "23505" or "ux_news_ingestion_runs_one_processing_per_company" in str(error):
            raise NewsRunConflict from error
        raise NewsPersistenceFailure("Could not create the news ingestion run.") from error

    rows = _rows(response)
    if not rows:
        raise NewsPersistenceFailure("The database did not return the new ingestion run.")
    return rows[0]


def _update_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    complete: bool = True,
) -> dict[str, Any]:
    payload = dict(payload)
    if complete:
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    try:
        response = (
            supabase.table("news_ingestion_runs")
            .update(payload)
            .eq("id", run_id)
            .select("*")
            .execute()
        )
    except Exception as error:
        raise NewsPersistenceFailure("Could not save the news ingestion result.") from error
    rows = _rows(response)
    if not rows:
        raise NewsPersistenceFailure("The database did not return the updated ingestion run.")
    return rows[0]


def _upsert_article(payload: dict[str, Any]) -> None:
    try:
        response = (
            supabase.table("news_articles")
            .upsert(payload, on_conflict="company_id,normalized_url")
            .select("id")
            .execute()
        )
    except Exception as error:
        raise NewsPersistenceFailure("Could not save a discovered news article.") from error
    if not _rows(response):
        raise NewsPersistenceFailure("The database did not confirm the saved news article.")


def _prior_articles(company_id: str, urls: list[str]) -> dict[str, dict[str, Any]]:
    if not urls:
        return {}
    try:
        response = (
            supabase.table("news_articles")
            .select(
                "normalized_url,events,relevance,relevance_status,processing_status"
            )
            .eq("company_id", company_id)
            .in_("normalized_url", urls)
            .execute()
        )
    except Exception as error:
        raise NewsPersistenceFailure("Could not check for previously stored articles.") from error
    return {
        row["normalized_url"]: row
        for row in _rows(response)
        if row.get("normalized_url")
    }


def ingest_company_news(
    company: dict[str, Any],
    lookback_days: int = 30,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one bounded ingestion, optionally using a run queued by the API."""
    company_id = str(company.get("id") or "")
    company_name = str(company.get("name") or "").strip()
    if not company_id or not company_name:
        raise ValueError("Company ID and registered name are required.")

    run = run or _insert_run(company_id, lookback_days)
    run_id = run["id"]
    counts = {
        "discovered_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        "classification_failed_count": 0,
        "persistence_failed_count": 0,
        "malformed_count": 0,
        "truncated_count": 0,
    }

    progress = {
        "stage": "discovering",
        "completed": 0,
        "total": 0,
        "reused": 0,
    }
    _update_run(run_id, {
        **counts,
        "status": "processing",
        "metadata": {"provider": "google_news_rss", "progress": progress},
    }, complete=False)

    try:
        discovery = discover_company_news(
            company,
            aliases=_company_aliases(company),
            days=lookback_days,
            max_articles=MAX_NEWS_CANDIDATES_PER_RUN,
        )
    except Exception as error:
        _update_run(run_id, {
            **counts,
            "status": "failed",
            "failure_reason": safe_error_summary(error, "News discovery failed."),
        })
        raise NewsProviderFailure(
            safe_error_summary(error, "News discovery failed.")
        ) from error

    articles = discovery["articles"]
    counts["discovered_count"] = discovery["entry_count"]
    counts["duplicate_count"] = discovery["duplicate_count"]
    counts["malformed_count"] = discovery["malformed_count"]
    counts["truncated_count"] = discovery["truncated_count"]
    counts["failed_count"] = counts["malformed_count"] + counts["truncated_count"]

    try:
        prior = _prior_articles(
            company_id,
            [article["normalized_url"] for article in articles],
        )
    except NewsPersistenceFailure as error:
        _update_run(run_id, {
            **counts,
            "status": "failed",
            "failure_reason": safe_error_summary(error),
        })
        raise

    context = {
        "symbol": company.get("symbol"),
        "sector": company.get("sector"),
        "aliases": _company_aliases(company),
    }
    reused_count = 0
    pending_articles = []
    for article in articles:
        previous = prior.get(article["normalized_url"], {})
        is_classified = (
            isinstance(previous.get("relevance"), dict)
            and previous.get("relevance_status") in {"accepted", "rejected"}
            and previous.get("processing_status") in {
                "not_relevant", "events_extracted", "no_supported_event"
            }
        )
        if not is_classified:
            pending_articles.append(article)
            continue

        reused_count += 1
        counts[
            "accepted_count"
            if previous["relevance_status"] == "accepted"
            else "rejected_count"
        ] += 1

    progress = {
        "stage": "classifying",
        "completed": reused_count,
        "total": len(articles),
        "reused": reused_count,
    }
    run_metadata = {**discovery["metadata"], "progress": progress}
    _update_run(run_id, {
        **counts,
        "status": "processing",
        "metadata": run_metadata,
    }, complete=False)

    processed_count = reused_count
    for offset in range(0, len(pending_articles), CLASSIFICATION_BATCH_SIZE):
        batch = pending_articles[offset:offset + CLASSIFICATION_BATCH_SIZE]
        batch_results = classify_articles(
            company_name,
            batch,
            company_context=context,
        )

        for article, classification in zip(batch, batch_results):
            processed_count += 1
            if classification is None:
                counts["failed_count"] += 1
                counts["classification_failed_count"] += 1
                continue

            try:
                relevant = bool(
                    classification["relevant"]
                    and classification["company_role"] in {"subject", "participant"}
                    and classification["business_event"]
                )
                previous = prior.get(article["normalized_url"], {})
                events = []
                if relevant:
                    counts["accepted_count"] += 1
                    for event in classification["events"]:
                        events.append({
                            **event,
                            "source_url": article["url"],
                            "published_at": article.get("published_at"),
                        })
                    if not events and previous.get("events"):
                        events = previous["events"]
                else:
                    counts["rejected_count"] += 1

                now = datetime.now(timezone.utc).isoformat()
                payload = {
                    "company_id": company_id,
                    "latest_run_id": run_id,
                    "normalized_url": article["normalized_url"],
                    "source_url": article["url"],
                    "title": article["title"],
                    "publisher": article.get("publisher"),
                    "publisher_url": article.get("publisher_url"),
                    "published_at": article.get("published_at"),
                    "rss_description": article.get("summary"),
                    "relevance_status": "accepted" if relevant else "rejected",
                    "relevance": classification,
                    "processing_status": (
                        "not_relevant" if not relevant
                        else "events_extracted" if events
                        else "no_supported_event"
                    ),
                    "events": events,
                    "discovery_metadata": {
                        "provider": article.get("discovery_source"),
                        "query": article.get("discovery_query"),
                        "rss_url": article.get("rss_url"),
                        "rss_entry_id": article.get("entry_id"),
                        "rss_published_at": article.get("published_at_raw"),
                    },
                    "last_seen_at": now,
                    "updated_at": now,
                }
                _upsert_article(payload)
            except Exception:
                counts["failed_count"] += 1
                counts["persistence_failed_count"] += 1

        progress = {
            "stage": "classifying",
            "completed": processed_count,
            "total": len(articles),
            "reused": reused_count,
        }
        run_metadata["progress"] = progress
        _update_run(run_id, {
            **counts,
            "status": "processing",
            "metadata": run_metadata,
        }, complete=False)

    if counts["failed_count"] and counts["accepted_count"] + counts["rejected_count"] == 0:
        status = "failed"
    elif counts["failed_count"]:
        status = "completed_with_errors"
    else:
        status = "completed"

    completed_run = _update_run(run_id, {
        **counts,
        "status": status,
        "failure_reason": _failure_summary(counts),
        "metadata": {**discovery["metadata"], "progress": {
            "stage": "complete",
            "completed": processed_count,
            "total": len(articles),
            "reused": reused_count,
        }},
    })
    return {"run": completed_run, "counts": counts}


def _run_background_ingestion(company, lookback_days, run):
    try:
        ingest_company_news(company, lookback_days=lookback_days, run=run)
    except Exception as error:
        logger.exception("Background company news ingestion crashed")
        try:
            _update_run(run["id"], {
                "status": "failed",
                "failed_count": 1,
                "failure_reason": safe_error_summary(
                    error, "News ingestion stopped unexpectedly."
                ),
                "metadata": {"provider": "google_news_rss", "progress": {
                    "stage": "failed", "completed": 0, "total": 0, "reused": 0,
                }},
            })
        except Exception:
            logger.exception("Could not mark crashed news ingestion as failed")


def queue_company_news_ingestion(
    company: dict[str, Any],
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Create a processing run and execute its work outside the HTTP request."""
    company_id = str(company.get("id") or "")
    company_name = str(company.get("name") or "").strip()
    if not company_id or not company_name:
        raise ValueError("Company ID and registered name are required.")

    run = _insert_run(company_id, lookback_days)
    try:
        _NEWS_EXECUTOR.submit(
            _run_background_ingestion, company, lookback_days, run
        )
    except Exception as error:
        _update_run(run["id"], {
            "status": "failed",
            "failed_count": 1,
            "failure_reason": "Could not start background news ingestion.",
        })
        raise NewsProviderFailure("Could not start background news ingestion.") from error
    return run


def _failure_summary(counts: dict[str, int]) -> str | None:
    details = []
    for field, label in (
        ("classification_failed_count", "classification failures"),
        ("persistence_failed_count", "persistence failures"),
        ("malformed_count", "malformed RSS entries"),
        ("truncated_count", "candidates skipped at the per-run limit"),
    ):
        if counts.get(field):
            details.append(f"{counts[field]} {label}")
    return "; ".join(details) if details else None


def get_company_news(company_id: str, limit: int = 50) -> dict[str, Any]:
    """Return stored relevant news and the latest ingestion state."""
    try:
        article_response = (
            supabase.table("news_articles")
            .select(
                "id,company_id,latest_run_id,source_url,title,publisher,"
                "publisher_url,published_at,rss_description,relevance,"
                "processing_status,events,created_at,updated_at"
            )
            .eq("company_id", company_id)
            .eq("relevance_status", "accepted")
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
        )
        run_response = (
            supabase.table("news_ingestion_runs")
            .select("*")
            .eq("company_id", company_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as error:
        raise NewsPersistenceFailure("Stored company news is unavailable.") from error

    articles = _rows(article_response)
    runs = _rows(run_response)
    latest_run = runs[0] if runs else None
    if latest_run and latest_run.get("failure_reason"):
        latest_run["failure_reason"] = safe_error_summary(latest_run["failure_reason"])

    if not latest_run:
        state = "not_fetched"
    elif latest_run.get("status") == "processing":
        state = "processing"
    elif latest_run.get("status") == "failed":
        state = "failed"
    elif latest_run.get("status") == "completed_with_errors":
        state = "completed_with_errors"
    else:
        state = (
            "completed_with_articles"
            if latest_run.get("accepted_count", 0) > 0
            else "completed_empty"
        )

    return {"state": state, "articles": articles, "latest_run": latest_run}
