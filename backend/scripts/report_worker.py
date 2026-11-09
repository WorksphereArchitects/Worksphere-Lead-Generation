
import logging
import os
import socket
import time
from datetime import datetime, timezone

from applications.services.gemini_engine import process_annual_report
from applications.services.report_job_queue import (
    claim_next_job,
    update_job,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("worksphere.report_worker")

POLL_SECONDS = float(
    os.getenv("WORKER_POLL_SECONDS", "5")
)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_forever():
    logger.info("Report worker started: %s", WORKER_ID)

    while True:
        try:
            job = claim_next_job(WORKER_ID)

            if not job:
                time.sleep(POLL_SECONDS)
                continue

            job_id = job["id"]
            report_id = job["annual_report_id"]

            logger.info(
                "Starting job %s for report %s",
                job_id,
                report_id,
            )

            try:
                process_annual_report(report_id)

                update_job(job_id, {
                    "status": "completed",
                    "last_error": None,
                    "completed_at": utc_now(),
                    "locked_at": None,
                    "worker_id": None,
                })

                logger.info("Job %s completed", job_id)

            except Exception as exc:
                logger.exception(
                    "Processing failed for report %s",
                    report_id,
                )

                attempts = int(job.get("attempts") or 1)
                max_attempts = int(job.get("max_attempts") or 2)

                terminal_failure = attempts >= max_attempts

                update_job(job_id, {
                    "status": (
                        "failed"
                        if terminal_failure
                        else "queued"
                    ),
                    "last_error": (
                        f"{type(exc).__name__}: {str(exc)[:1500]}"
                    ),
                    "completed_at": (
                        utc_now() if terminal_failure else None
                    ),
                    "locked_at": None,
                    "worker_id": None,
                })

        except Exception:
            logger.exception("Worker loop failed.")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
