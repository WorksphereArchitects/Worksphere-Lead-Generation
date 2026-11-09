
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from applications.services.supabase_client import supabase


class ActiveReportJobError(RuntimeError):
    """Raised when a report already has an active processing job."""


def enqueue_report_job(report: dict[str, Any]) -> dict[str, Any]:
    report_id = report.get("id")
    company_id = report.get("company_id")

    if not report_id or not company_id:
        raise ValueError("Annual report ID or company ID is missing.")

    if report.get("processing_status") == "processing":
        raise ActiveReportJobError(
            "This annual report is already processing."
        )

    try:
        response = (
            supabase.table("report_processing_jobs")
            .insert({
                "annual_report_id": report_id,
                "company_id": company_id,
                "status": "queued",
                "attempts": 0,
                "max_attempts": 2,
            })
            .select("*")
            .execute()
        )

    except Exception as exc:
        message = str(exc).lower()

        if (
            "uq_report_jobs_active_report" in message
            or "duplicate key" in message
            or "23505" in message
        ):
            raise ActiveReportJobError(
                "A job for this report is already queued or running."
            ) from exc

        raise

    if not response.data:
        raise RuntimeError("Could not enqueue annual report.")

    return response.data[0]


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    response = supabase.rpc(
        "claim_next_report_job",
        {"p_worker_id": worker_id},
    ).execute()

    if not response.data:
        return None

    return (
        response.data[0]
        if isinstance(response.data, list)
        else response.data
    )


def update_job(job_id: str, values: dict[str, Any]) -> None:
    update_values = {
        **values,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    (
        supabase.table("report_processing_jobs")
        .update(update_values)
        .eq("id", job_id)
        .execute()
    )


def get_latest_job_for_report(
    report_id: str,
) -> dict[str, Any] | None:

    response = (
        supabase.table("report_processing_jobs")
        .select("*")
        .eq("annual_report_id", report_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    return response.data[0] if response.data else None
