
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from applications.services.supabase_client import supabase


def _rpc_row(response) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    return data


def enqueue_report_job(report: dict[str, Any], retry: bool = False) -> dict[str, Any]:
    report_id = report.get("id")
    if not report_id or not report.get("company_id"):
        raise ValueError("Annual report ID or company ID is missing.")
    response = supabase.rpc(
        "enqueue_report_processing_job",
        {"p_report_id": report_id, "p_retry": retry},
    ).execute()
    job = _rpc_row(response)
    if not job:
        raise RuntimeError("Could not enqueue annual report.")
    return job


def claim_job(job_id: str, report_id: str, worker_id: str) -> dict[str, Any] | None:
    response = supabase.rpc(
        "claim_report_processing_job",
        {"p_job_id": job_id, "p_report_id": report_id, "p_worker_id": worker_id},
    ).execute()
    return _rpc_row(response)


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    response = supabase.rpc("claim_next_report_job", {"p_worker_id": worker_id}).execute()
    return _rpc_row(response)


def heartbeat_job(job_id: str, worker_id: str) -> bool:
    response = supabase.rpc(
        "heartbeat_report_processing_job",
        {"p_job_id": job_id, "p_worker_id": worker_id},
    ).execute()
    return bool(getattr(response, "data", False))


def complete_job(job_id: str, worker_id: str, processing_run_id: str | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    response = supabase.rpc(
        "complete_report_processing_job",
        {"p_job_id": job_id, "p_worker_id": worker_id,
         "p_processing_run_id": processing_run_id, "p_metadata": metadata or {}},
    ).execute()
    return _rpc_row(response)


def fail_job(job_id: str, worker_id: str, error_message: str,
             retryable: bool = True) -> dict[str, Any] | None:
    response = supabase.rpc(
        "fail_report_processing_job",
        {"p_job_id": job_id, "p_worker_id": worker_id,
         "p_error": error_message[:4000], "p_retryable": retryable},
    ).execute()
    return _rpc_row(response)


def recover_stale_jobs() -> int:
    response = supabase.rpc("recover_stale_report_processing_jobs").execute()
    return int(getattr(response, "data", 0) or 0)


def get_latest_job_for_report(report_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("report_processing_jobs").select("*")
        .eq("annual_report_id", report_id).order("queued_at", desc=True)
        .limit(1).execute()
    )
    return response.data[0] if response.data else None


def mark_dispatch_failed(job_id: str, error_message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = (
        supabase.table("report_processing_jobs")
        .update({"status": "failed", "last_error": error_message[:4000],
                 "completed_at": now, "last_activity_at": now, "updated_at": now})
        .eq("id", job_id).eq("status", "queued").execute()
    )
    if response.data:
        supabase.table("report_processing_job_history").insert({
            "job_id": job_id, "status": "failed", "event": "workflow_dispatch_failed",
            "error_message": error_message[:4000],
        }).execute()
