
import logging
import os
import hmac
from uuid import UUID

from flask import Blueprint, jsonify, request
from applications.services.annual_reports import (
    get_annual_report,
)
from applications.services.supabase_client import supabase
from applications.services.report_job_queue import (
    enqueue_report_job,
    get_latest_job_for_report,
    mark_dispatch_failed,
    recover_stale_jobs,
)
from applications.services.report_ingestion_jobs import (
    ReportIngestionConflict,
    get_company_report_ingestion,
    queue_company_report_ingestion,
)
from applications.services.nse_diagnostic import test_nse_connection
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError



logger = logging.getLogger(__name__)

reports = Blueprint(
    "reports",
    __name__,
    url_prefix="/api/reports",
)


def trigger_github_workflow(job_id, report_id):
    """
    Trigger the annual report processing GitHub Actions workflow.
    """

    token = os.getenv("GITHUB_ACTIONS_TOKEN")
    owner = os.getenv("GITHUB_REPOSITORY_OWNER")
    repo = os.getenv("GITHUB_REPOSITORY_NAME")
    workflow = os.getenv("GITHUB_WORKFLOW_FILE")
    branch = os.getenv("GITHUB_WORKFLOW_REF", "main")

    required = {
        "GITHUB_ACTIONS_TOKEN": token,
        "GITHUB_REPOSITORY_OWNER": owner,
        "GITHUB_REPOSITORY_NAME": repo,
        "GITHUB_WORKFLOW_FILE": workflow,
    }

    missing = [
        name for name, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing GitHub configuration: " + ", ".join(missing)
        )

    url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow}/dispatches"
    )

    payload = {
        "ref": branch,
        "inputs": {
            "job_id": job_id,
            "report_id": report_id,
        },
    }

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "WorkSphere-Lead-Generation",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(
                    f"GitHub returned HTTP {response.status}"
                )

    except HTTPError as error:
        details = error.read().decode(
            "utf-8",
            errors="replace",
        )

        logger.error(
            "GitHub workflow dispatch failed: HTTP %s - %s",
            error.code,
            details,
        )

        raise RuntimeError(
            f"GitHub workflow dispatch failed (HTTP {error.code})."
        ) from error

    except URLError as error:
        logger.exception("Could not connect to GitHub API.")

        raise RuntimeError(
            "Could not connect to GitHub."
        ) from error


# --------------------------------------------------
# PROCESS ANNUAL REPORT
# --------------------------------------------------


@reports.post("/<string:report_id>/process")
def process_report(report_id):

    try:
        UUID(report_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid annual report ID.",
        }), 400

    try:
        recover_stale_jobs()
        report = get_annual_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404

        retry = bool((request.get_json(silent=True) or {}).get("retry", False))
        existing_job = get_latest_job_for_report(report_id)
        job = enqueue_report_job(report, retry=retry)

        if job.get("status") == "failed" and not retry:
            return jsonify({
                "success": False,
                "error": job.get("last_error") or "The previous processing attempt failed. Retry explicitly.",
                "job_id": job["id"],
                "status": "failed",
            }), 409

        if existing_job and existing_job.get("id") == job.get("id") and job.get("status") in {"queued", "processing", "completed"}:
            return jsonify({
                "success": True,
                "message": "Annual report processing job already exists.",
                "report_id": report_id,
                "job_id": job["id"],
                "status": job["status"],
                "idempotent": True,
            }), 202

        try:
            trigger_github_workflow(job["id"], report_id)
        except Exception as dispatch_error:
            mark_dispatch_failed(job["id"], str(dispatch_error))
            raise

        logger.info(
            "GitHub processing workflow triggered for report %s",
            report_id,
        )

        return jsonify({
            "success": True,
            "message": "Annual report queued successfully.",
            "report_id": report_id,
            "job_id": job["id"],
            "status": "queued",
        }), 202

    except Exception as error:
        logger.exception(
            "Could not trigger report processing: %s",
            report_id,
        )

        message = str(error).lower()
        status_code = 409 if any(value in message for value in (
            "already_completed", "retry_limit", "already processing"
        )) else 502
        return jsonify({
            "success": False,
            "error": (
                "This report is already completed or its retry limit was reached."
                if status_code == 409 else "Could not start annual report processing."
            ),
        }), status_code



# --------------------------------------------------
# PROCESSING STATUS
# --------------------------------------------------


@reports.get("/<string:report_id>/status")
def report_processing_status(report_id):

    try:
        UUID(report_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid annual report ID.",
        }), 400

    try:
        recover_stale_jobs()
        report = get_annual_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404

        report_status = report.get("processing_status") or "pending"
        job = get_latest_job_for_report(report_id)

        # The GitHub runner may be waiting to start.
        status = (
            "queued"
            if report_status == "pending"
            else report_status
        )

        return jsonify({
            "success": True,
            "report_id": report_id,
            "status": status,
            "report_status": report_status,
            "job": job,
            "error": job.get("last_error") if job else None,
        }), 200

    except Exception:
        logger.exception(
            "Could not retrieve report status: %s",
            report_id,
        )

        return jsonify({
            "success": False,
            "error": "Could not retrieve report status.",
        }), 500



# --------------------------------------------------
# INGEST COMPANY ANNUAL REPORT
# --------------------------------------------------

@reports.post("/companies/<string:company_id>/ingest")
def ingest_company_report(company_id):

    try:
        UUID(company_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid company ID. A company UUID is required.",
        }), 400

    try:
        response = (
            supabase
            .table("companies")
            .select("*")
            .eq("id", company_id)
            .maybe_single()
            .execute()
        )

        company = response.data

        if not company:
            return jsonify({
                "success": False,
                "error": "Company not found.",
            }), 404

        job = queue_company_report_ingestion(company)
        return jsonify({
            "success": True,
            "message": "Annual report ingestion queued.",
            "job": job,
            "company": {
                "id": company["id"],
                "symbol": company["symbol"],
                "name": company["name"],
            },
        }), 200

    except ReportIngestionConflict:
        return jsonify({
            "success": False,
            "error": "Annual report ingestion is already running for this company.",
        }), 409

    except Exception:
        logger.exception(
            "Annual report ingestion failed for company %s",
            company_id,
        )

        return jsonify({
            "success": False,
            "error": (
                "Annual report ingestion failed. "
                "Check backend configuration and logs."
            ),
        }), 500


@reports.get("/companies/<string:company_id>/ingest/<string:job_id>")
def annual_report_ingestion_status(company_id, job_id):
    try:
        UUID(company_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid company ID."}), 400
    job = get_company_report_ingestion(company_id, job_id)
    if not job:
        return jsonify({"success": False, "error": "Ingestion job not found."}), 404
    return jsonify({"success": True, "job": job}), 200


# --------------------------------------------------
# NSE DIAGNOSTIC
# --------------------------------------------------

@reports.get("/debug/nse")
def debug_nse():

    expected_token = os.getenv("NSE_DEBUG_TOKEN")
    provided_token = request.headers.get("X-Debug-Token", "")

    if not expected_token or not hmac.compare_digest(
        provided_token,
        expected_token,
    ):
        return jsonify({
            "success": False,
            "error": "Unauthorized",
        }), 401

    try:
        test_nse_connection()

        return jsonify({
            "success": True,
            "message": (
                "NSE diagnostic completed. Check Render logs."
            ),
        }), 200

    except Exception:
        logger.exception("NSE diagnostic failed.")

        return jsonify({
            "success": False,
            "error": "NSE diagnostic failed. Check Render logs.",
        }), 500
