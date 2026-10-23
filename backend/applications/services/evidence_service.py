from __future__ import annotations

from typing import Any

from applications.services.supabase_client import supabase


def create_evidence_batch(
    company_id: str,
    source_type: str,
    source_id: str,
    financial_year: str | None,
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist source-resolved Gemini signals. No validator is used here."""
    if not signals:
        return []

    rows = []

    # Keep retries idempotent at the report/evidence level. The report claim
    # serializes processing runs; this application key also covers deployments
    # whose database has no matching uniqueness constraint.
    existing_response = (
        supabase.table("evidence")
        .select("evidence_type, headline, source_candidate_ids")
        .eq("source_type", source_type)
        .eq("source_id", source_id)
        .execute()
    )
    existing_keys = {
        (
            item.get("evidence_type"),
            tuple(sorted(item.get("source_candidate_ids") or [])),
            " ".join((item.get("headline") or "").casefold().split()),
        )
        for item in (existing_response.data or [])
    }

    for signal in signals:
        location = signal.get("location", {})
        mentions = location.get("mentions", []) if isinstance(location, dict) else []
        investment = signal.get("investment", {})
        investment_values = (
            investment.get("values", []) if isinstance(investment, dict) else []
        )
        evidence = signal.get("evidence", {})

        row = {
            "company_id": company_id,
            "source_type": source_type,
            "source_id": source_id,
            "financial_year": financial_year,
            "evidence_type": signal.get("signal_type"),
            "event_state": signal.get("event_state"),
            "headline": signal.get("headline"),
            "summary": signal.get("summary"),
            "why_it_matters": signal.get("why_it_matters"),
            "statement": (
                signal.get("physical_consequence")
                or signal.get("summary")
                or signal.get("headline")
            ),
            "excerpt": evidence.get("excerpt"),
            "location": ", ".join(mentions),
            "investment": investment_values,
            "physical_scale": signal.get("physical_scale", []),
            "timeline": signal.get("timeline"),
            "physical_consequence": signal.get("physical_consequence"),
            "supporting_facts": signal.get("supporting_facts", []),
            "source_candidate_ids": evidence.get("source_candidate_ids", []),
            "source_sentence_indexes": evidence.get("source_sentence_indexes", []),
            "source_resolution_status": signal.get("source_resolution_status", "resolved",),            
            "confidence": signal.get("confidence"),
            "is_current": True,
        }
        key = (
            row["evidence_type"],
            tuple(sorted(row["source_candidate_ids"] or [])),
            " ".join((row["headline"] or "").casefold().split()),
        )
        if key not in existing_keys:
            rows.append(row)
            existing_keys.add(key)

    if not rows:
        return []

    response = supabase.table("evidence").insert(rows).select("*").execute()
    if not response.data:
        raise RuntimeError("Evidence insertion returned no persisted rows.")
    return response.data


def get_company_evidence(
    company_id: str,
    current_only: bool = True,
) -> list[dict[str, Any]]:
    query = (
        supabase.table("evidence")
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
    )

    if current_only:
        query = query.eq("is_current", True)

    response = query.execute()
    return response.data or []


def get_evidence(evidence_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("evidence")
        .select("*")
        .eq("id", evidence_id)
        .maybe_single()
        .execute()
    )
    return response.data
