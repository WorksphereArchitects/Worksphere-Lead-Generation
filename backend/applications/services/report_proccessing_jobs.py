"""Background execution and status queries for annual report processing."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Any

from applications.services.annual_reports import (
    ReportAlreadyProcessingError,
    get_annual_report,
    mark_report_failed,
    claim_report_for_processing,
)
from applications.services.gemini_engine import process_annual_report
from applications.services.public_errors import safe_error_summary
from applications.services.processing_runs import fail_processing_run
from applications.services.supabase_client import supabase

logger = logging.getLogger(__name__)
_REPORT_PROCESSING_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="report-processing",
)
STALE_PROCESSING_AFTER = timedelta(minutes=10)
PROCESSING_HEARTBEAT_INTERVAL = 60


def _heartbeat_report(report_id: str, stop_event: Event) -> None:
    while not stop_event.wait(PROCESSING_HEARTBEAT_INTERVAL):
        try:
            (
                supabase.table("annual_reports")
                .update({"updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", report_id)
                .eq("processing_status", "processing")
                .execute()
            )
        except Exception:
            logger.exception(
                "Could not refresh processing heartbeat for report %s",
                report_id,
            )


def _process_report(report_id: str) -> None:
    stop_event = Event()
    heartbeat = Thread(
        target=_heartbeat_report,
        args=(report_id, stop_event),
        name=f"report-heartbeat-{report_id}",
        daemon=True,
    )
    heartbeat.start()
    try:
        process_annual_report(report_id, already_claimed=True)
    except Exception:
        logger.exception("Background processing failed for report %s", report_id)
    finally:
        stop_event.set()
        heartbeat.join(timeout=PROCESSING_HEARTBEAT_INTERVAL + 1)


def _latest_run(report_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("processing_runs")
        .select(
            "id,status,error_message,started_at,completed_at,model_used,"
            "candidate_count,signal_count,resolved_signal_count,"
            "unresolved_signal_count"
        )
        .eq("annual_report_id", report_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    runs = response.data or []
    return runs[0] if runs else None


def _recover_stale_processing(
    report: dict[str, Any],
    latest_run: dict[str, Any] | None,
) -> bool:
    if report.get("processing_status") != "processing":
        return False
    if not report.get("updated_at"):
        return False

    try:
        started = datetime.fromisoformat(
            str(report["updated_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        logger.warning("Invalid processing start time for report %s", report["id"])
        return False

    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - started <= STALE_PROCESSING_AFTER:
        return False

    cutoff = datetime.now(timezone.utc) - STALE_PROCESSING_AFTER
    response = (
        supabase.table("annual_reports")
        .update({"processing_status": "failed"})
        .eq("id", report["id"])
        .eq("processing_status", "processing")
        .lt("updated_at", cutoff.isoformat())
        .select("id")
        .execute()
    )
    if not response.data:
        return False

    if latest_run and latest_run.get("status") == "running":
        try:
            fail_processing_run(
                latest_run["id"],
                "Processing stopped without completing. Retry the report.",
            )
        except Exception:
            logger.exception(
                "Could not close stale processing run %s",
                latest_run["id"],
            )
    return True


def queue_report_processing(report_id: str) -> dict[str, Any]:
    report = get_annual_report(report_id)
    if not report:
        raise LookupError(f"Annual report not found: {report_id}")

    if report.get("processing_status") == "processing":
        latest_run = _latest_run(report_id)
        _recover_stale_processing(report, latest_run)
        report = get_annual_report(report_id)
        if report and report.get("processing_status") == "processing":
            return {"status": "processing", "report_id": report_id}

    try:
        claim_report_for_processing(report_id)
    except ReportAlreadyProcessingError:
        return {"status": "processing", "report_id": report_id}

    try:
        _REPORT_PROCESSING_EXECUTOR.submit(_process_report, report_id)
    except Exception:
        logger.exception("Could not start processing for report %s", report_id)
        try:
            mark_report_failed(report_id)
        except Exception:
            logger.exception("Could not release report processing lock %s", report_id)
        raise

    return {"status": "processing", "report_id": report_id}


def get_report_processing_status(report_id: str) -> dict[str, Any] | None:
    report = get_annual_report(report_id)
    if not report:
        return None

    latest_run = _latest_run(report_id)
    if _recover_stale_processing(report, latest_run):
        report = get_annual_report(report_id)
        latest_run = _latest_run(report_id)
    if latest_run and latest_run.get("error_message"):
        latest_run["error_message"] = safe_error_summary(
            latest_run["error_message"]
        )

    return {
        "report_id": report_id,
        "status": report.get("processing_status"),
        "latest_run": latest_run,
    }
