
import logging
import traceback
import os
import hmac
from uuid import UUID

from flask import Blueprint, jsonify, request, current_app
from applications.services.annual_reports import (
    get_annual_report,
    ReportAlreadyProcessingError,
)
from applications.services.annual_report_ingestion import (
    load_report_from_company,
)
from applications.services.supabase_client import supabase
from applications.services.nse_diagnostic import test_nse_connection
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from applications.services.annual_reports import get_annual_report


logger = logging.getLogger(__name__)

reports = Blueprint(
    "reports",
    __name__,
    url_prefix="/api/reports",
)


def trigger_github_workflow(report_id):
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


def _process_report_background(app, report_id):
    """
    Runs annual report processing outside the HTTP request.

    Only one report can be processed at a time.
    """

    global active_report_id

    try:
        with app.app_context():
            logger.info(
                "Starting annual report processing: %s",
                report_id,
            )

            process_annual_report(report_id)

            logger.info(
                "Annual report processing completed: %s",
                report_id,
            )

    except Exception:
        logger.exception(
            "Annual report processing failed: %s",
            report_id,
        )

    finally:
        with processing_lock:
            if active_report_id == report_id:
                active_report_id = None

        logger.info(
            "Processing slot released for report: %s",
            report_id,
        )


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
        report = get_annual_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404

        if report.get("processing_status") == "processing":
            return jsonify({
                "success": False,
                "error": "Annual report is already processing.",
            }), 409

        # GitHub now handles the actual processing.
        trigger_github_workflow(report_id)

        logger.info(
            "GitHub processing workflow triggered for report %s",
            report_id,
        )

        return jsonify({
            "success": True,
            "message": "Annual report queued successfully.",
            "report_id": report_id,
            "status": "queued",
        }), 202

    except Exception:
        logger.exception(
            "Could not trigger report processing: %s",
            report_id,
        )

        return jsonify({
            "success": False,
            "error": "Could not start annual report processing.",
        }), 502



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
        report = get_annual_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404

        report_status = (
            report.get("processing_status") or "pending"
        )

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

        result = load_report_from_company(
            symbol=company["symbol"],
            company=company,
        )

        return jsonify({
            "success": True,
            "message": "Annual report discovered and ingested.",
            "company": {
                "id": company["id"],
                "symbol": company["symbol"],
                "name": company["name"],
            },
            "report": {
                "id": result["annual_report_id"],
                "financial_year": result["financial_year"],
                "report_title": result["file_name"],
                "nse_url": result["nse_url"],
                "page_count": result["page_count"],
                "processing_status": result["processing_status"],
            },
        }), 200

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
