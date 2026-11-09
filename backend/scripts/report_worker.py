
import logging
import os
import socket
import time
from threading import Event, Thread

from applications.services.gemini_engine import process_annual_report
from applications.services.report_job_queue import (
    claim_job,
    complete_job,
    fail_job,
    heartbeat_job,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("worksphere.report_worker")

WORKER_ID = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
JOB_ID = os.getenv("JOB_ID")
REPORT_ID = os.getenv("REPORT_ID")


def is_retryable(error: Exception) -> bool:
    message = str(error).lower()
    permanent_markers = ("missing", "not found", "invalid", "authentication", "unauthorized")
    return not any(marker in message for marker in permanent_markers)


def heartbeat_loop(job_id: str, stop_event: Event) -> None:
    while not stop_event.wait(60):
        try:
            if not heartbeat_job(job_id, WORKER_ID):
                logger.warning("Job %s heartbeat was rejected; worker no longer owns it", job_id)
                return
        except Exception:
            logger.exception("Could not update heartbeat for job %s", job_id)


def process_job(job_id: str, report_id: str) -> int:
    job = claim_job(job_id, report_id, WORKER_ID)
    if not job:
        logger.info("Job %s was already claimed, completed, or made stale", job_id)
        return 0

    stop_event = Event()
    heartbeat = Thread(target=heartbeat_loop, args=(job_id, stop_event), daemon=True)
    heartbeat.start()
    started_at = time.monotonic()
    try:
        result = process_annual_report(report_id, already_claimed=True)
        run_id = result.get("processing_run", {}).get("id") if result else None
        completed = complete_job(job_id, WORKER_ID, run_id, {
            "report_id": report_id,
            "evidence_count": len(result.get("signals", [])) if result else 0,
            "source_candidate_count": (result.get("retrieval_stats", {}) or {}).get("candidate_count", 0) if result else 0,
            "processing_duration_seconds": round(time.monotonic() - started_at, 2),
        })
        if not completed:
            raise RuntimeError("Job completion was rejected by Supabase.")
        logger.info("Completed job %s for report %s", job_id, report_id)
        return 0
    except Exception as error:
        message = f"{type(error).__name__}: {str(error)[:3800]}"
        logger.exception("Processing failed for job %s report %s", job_id, report_id)
        fail_job(job_id, WORKER_ID, message, retryable=is_retryable(error))
        return 1
    finally:
        stop_event.set()
        heartbeat.join(timeout=5)


if __name__ == "__main__":
    if not JOB_ID or not REPORT_ID:
        logger.error("JOB_ID and REPORT_ID environment variables are required")
        raise SystemExit(1)
    raise SystemExit(process_job(JOB_ID, REPORT_ID))
