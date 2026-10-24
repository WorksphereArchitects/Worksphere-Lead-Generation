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


def _update_job(job_id: str, values: dict[str, Any]) -> None:
    payload = {
        **values,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("report_ingestion_runs").update(payload).eq(
        "id", job_id
    ).execute()


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
        if (
            getattr(error, "code", None) == "23505"
            or "ux_report_ingestion_runs_one_processing_per_company"
            in str(error)
        ):
            raise ReportIngestionConflict from error
        raise

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
        _update_job(job["id"], {
            "status": "failed",
            "failure_reason": "Could not start annual report ingestion.",
        })
        raise RuntimeError(
            "Could not start annual report ingestion."
        ) from error
    return job


def get_company_report_ingestion(
    company_id: str,
    job_id: str,
) -> dict[str, Any] | None:
    response = (
        supabase.table("report_ingestion_runs")
        .select("id,company_id,status,report_id,result,failure_reason,created_at,updated_at")
        .eq("company_id", company_id)
        .eq("id", job_id)
        .maybe_single()
        .execute()
    )
    return response.data if response else None
