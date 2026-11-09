"""Background execution and status tracking for annual report ingestion."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from applications.services.annual_report_ingestion import load_report_from_company
from applications.services.public_errors import safe_error_summary
from applications.services.supabase_client import supabase

logger = logging.getLogger(__name__)
_REPORT_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="annual-report",
)


class ReportIngestionConflict(Exception):
    """Raised when a company already has an active report ingestion."""


class ReportIngestionDatabaseError(RuntimeError):
    """Raised when the ingestion job store is unavailable or incomplete."""


def _database_error(operation: str, error: Exception) -> ReportIngestionDatabaseError:
    logger.exception(
        "Annual report ingestion database operation failed: %s (code=%s)",
        operation,
        getattr(error, "code", None) or "unknown",
    )
    return ReportIngestionDatabaseError(
        "Annual report ingestion job storage is unavailable."
    )


def _update_job(job_id: str, values: dict[str, Any]) -> None:
    payload = {
        **values,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("report_ingestion_runs").update(payload).eq(
            "id", job_id
        ).execute()
    except Exception as error:
        raise _database_error("update ingestion job", error) from error


def _run_report_ingestion(job: dict[str, Any], company: dict[str, Any]) -> None:
    try:
        result = load_report_from_company(
            symbol=company["symbol"],
            company=company,
        )
        _update_job(job["id"], {
            "status": "completed",
            "report_id": result["annual_report_id"],
            "result": {
                "id": result["annual_report_id"],
                "financial_year": result["financial_year"],
                "report_title": result["file_name"],
                "nse_url": result["nse_url"],
                "page_count": result["page_count"],
                "processing_status": result["processing_status"],
            },
            "failure_reason": None,
        })
    except Exception as error:
        logger.exception(
            "Annual report ingestion failed for company %s",
            company.get("id"),
        )
        try:
            _update_job(job["id"], {
                "status": "failed",
                "failure_reason": safe_error_summary(
                    error,
                    "Annual report ingestion failed.",
                ),
            })
        except Exception:
            logger.exception(
                "Could not record annual report ingestion failure for job %s",
                job["id"],
            )


def queue_company_report_ingestion(
    company: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = (
            supabase.table("report_ingestion_runs")
            .insert({
                "company_id": company["id"],
                "status": "processing",
            })
            .select("*")
            .execute()
        )
    except Exception as error:
        error_code = getattr(error, "code", None)
        error_message = str(error)
        if error_code == "PGRST205" or "schema cache" in error_message.lower():
            raise _database_error("create ingestion job", error) from error
        if (
            error_code == "23505"
            or "ux_report_ingestion_runs_one_processing_per_company"
            in error_message
        ):
            try:
                existing = (
                    supabase.table("report_ingestion_runs")
                    .select("*")
                    .eq("company_id", company["id"])
                    .eq("status", "processing")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
            except Exception as lookup_error:
                raise _database_error(
                    "find active ingestion job",
                    lookup_error,
                ) from lookup_error
            if existing.data:
                return existing.data[0]
            raise ReportIngestionConflict from error
        raise _database_error("create ingestion job", error) from error

    if not response.data:
        raise RuntimeError("Could not create annual report ingestion job.")

    job = response.data[0]
    try:
        _REPORT_EXECUTOR.submit(_run_report_ingestion, job, company)
    except Exception as error:
        logger.exception(
            "Could not start annual report ingestion for company %s",
            company.get("id"),
        )
        try:
            _update_job(job["id"], {
                "status": "failed",
                "failure_reason": "Could not start annual report ingestion.",
            })
        except ReportIngestionDatabaseError:
            logger.exception(
                "Could not persist failed ingestion job %s",
                job.get("id"),
            )
        raise RuntimeError(
            "Could not start annual report ingestion."
        ) from error
    return job


def get_company_report_ingestion(
    company_id: str,
    job_id: str,
) -> dict[str, Any] | None:
    try:
        response = (
            supabase.table("report_ingestion_runs")
            .select("id,company_id,status,report_id,result,failure_reason,created_at,updated_at")
            .eq("company_id", company_id)
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
    except Exception as error:
        raise _database_error("read ingestion job", error) from error
    return response.data if response else None
