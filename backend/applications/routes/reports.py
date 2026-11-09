
import logging
import traceback
import os
import hmac
import threading

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from flask import Blueprint, jsonify, request, current_app

from applications.services.gemini_engine import process_annual_report
from applications.services.annual_reports import (
    get_annual_report,
    ReportAlreadyProcessingError,
)
from applications.services.annual_report_ingestion import (
    load_report_from_company,
)
from applications.services.supabase_client import supabase
from applications.services.nse_diagnostic import test_nse_connection


logger = logging.getLogger(__name__)

reports = Blueprint(
    "reports",
    __name__,
    url_prefix="/api/reports",
)


# --------------------------------------------------
# SINGLE REPORT PROCESSING CONFIGURATION
# --------------------------------------------------

executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="annual-report-worker",
)

processing_lock = threading.Lock()
active_report_id = None


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

    global active_report_id

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

        with processing_lock:

            # Prevent any second report from starting.
            if active_report_id is not None:
                return jsonify({
                    "success": False,
                    "error": (
                        "Another annual report is currently "
                        "being processed. Please wait."
                    ),
                    "active_report_id": active_report_id,
                }), 409

            # Prevent duplicate processing of the same report.
            if report.get("processing_status") == "processing":
                return jsonify({
                    "success": False,
                    "error": "Annual report is already processing.",
                }), 409

            # Reserve the single processing slot.
            active_report_id = report_id

            try:
                app = current_app._get_current_object()

                executor.submit(
                    _process_report_background,
                    app,
                    report_id,
                )

            except Exception:
                active_report_id = None
                raise

        return jsonify({
            "success": True,
            "message": "Annual report processing started.",
            "report_id": report_id,
            "status": "queued",
        }), 202

    except ReportAlreadyProcessingError:
        return jsonify({
            "success": False,
            "error": "Annual report is already processing.",
        }), 409

    except Exception:
        logger.exception(
            "Could not start report processing: %s",
            report_id,
        )

        return jsonify({
            "success": False,
            "error": "Could not start annual report processing.",
        }), 500


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

        with processing_lock:
            is_active = active_report_id == report_id

        report_status = report.get("processing_status") or "pending"

        # Supabase is the source of truth for persisted status.
        # The local lock tells us whether this process owns the job.
        if is_active and report_status != "completed":
            status = (
                "processing"
                if report_status == "processing"
                else "queued"
            )
        else:
            status = report_status

        return jsonify({
            "success": True,
            "report_id": report_id,
            "status": status,
            "report_status": report_status,
            "is_active": is_active,
        }), 200

    except Exception:
        logger.exception(
            "Could not retrieve report status: %s",
            report_id,
        )

        return jsonify({
            "success": False,
            "error": "Could not retrieve processing status.",
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
