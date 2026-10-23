from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from applications.services.supabase_client import supabase


def create_processing_run(
    company_id: str,
    annual_report_id: str | None,
    model_attempted: str | None,
) -> dict[str, Any]:
    payload = {
        "company_id": company_id,
        "annual_report_id": annual_report_id,
        "model_attempted": model_attempted,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    response = (
        supabase.table("processing_runs")
        .insert(payload)
        .select("*")
        .execute()
    )

    if not response.data:
        raise RuntimeError("Failed to create processing run.")

    return response.data[0]


def complete_processing_run(
    run_id: str,
    *,
    model_used: str | None,
    fallback_reason: str | None,
    flash_attempts: int | None,
    candidate_count: int,
    signal_count: int,
    resolved_signal_count: int,
    unresolved_signal_count: int,
) -> dict[str, Any]:
    payload = {
        "model_used": model_used,
        "fallback_reason": fallback_reason,
        "flash_attempts": flash_attempts,
        "candidate_count": candidate_count,
        "signal_count": signal_count,
        "resolved_signal_count": resolved_signal_count,
        "unresolved_signal_count": unresolved_signal_count,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    response = (
        supabase.table("processing_runs")
        .update(payload)
        .eq("id", run_id)
        .select("*")
        .execute()
    )

    if not response.data:
        raise RuntimeError(f"Processing run not found: {run_id}")

    return response.data[0]


def fail_processing_run(
    run_id: str,
    error_message: str,
) -> dict[str, Any]:
    response = (
        supabase.table("processing_runs")
        .update({
            "status": "failed",
            "error_message": error_message,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", run_id)
        .select("*")
        .execute()
    )

    if not response.data:
        raise RuntimeError(f"Processing run not found: {run_id}")

    return response.data[0]


def get_processing_runs(
    company_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    response = (
        supabase.table("processing_runs")
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []
