import logging

from flask import Blueprint, jsonify
from uuid import UUID
from applications.services.report_ingestion_jobs import (
    ReportIngestionConflict,
    get_company_report_ingestion,
    queue_company_report_ingestion,
)
from applications.services.report_processing_jobs import (
    get_report_processing_status,
    queue_report_processing,
)
from applications.services.supabase_client import supabase

logger = logging.getLogger(__name__)

reports = Blueprint(
    "reports",
    __name__,
    url_prefix="/api/reports"
)


@reports.post("/<string:report_id>/process")
def process_report(report_id):
    try:
        UUID(report_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid annual report ID. A report UUID is required.",
        }), 400

    try:
        job = queue_report_processing(report_id)
        return jsonify({
            "success": True,
            "status": job["status"],
            "report_id": job["report_id"],
        }), 202

    except Exception as error:
        if isinstance(error, LookupError):
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404
        logger.exception("Could not queue report processing for %s", report_id)
        return jsonify({
            "success": False,
            "error": "Could not start annual report processing.",
        }), 500


@reports.get("/<string:report_id>/status")
def get_report_processing_status_route(report_id):
    try:
        UUID(report_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid annual report ID. A report UUID is required.",
        }), 400

    try:
        status = get_report_processing_status(report_id)
    except Exception:
        logger.exception("Could not retrieve processing status for %s", report_id)
        return jsonify({
            "success": False,
            "error": "Could not retrieve annual report processing status.",
        }), 500

    if not status:
        return jsonify({
            "success": False,
            "error": "Annual report not found.",
        }), 404

    return jsonify({"success": True, **status}), 200


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
                "error": "Company not found."
            }), 404

        job = queue_company_report_ingestion(company)
        return jsonify({
            "success": True,
            "status": job["status"],
            "job_id": job["id"],
        }), 202

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
            "error": "Could not queue annual report ingestion.",
        }), 500


@reports.get("/companies/<string:company_id>/ingest-runs/<string:job_id>")
def get_company_report_ingestion_status(company_id, job_id):
    try:
        UUID(company_id)
        UUID(job_id)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid company or ingestion job ID.",
        }), 400

    try:
        job = get_company_report_ingestion(company_id, job_id)
    except Exception:
        logger.exception(
            "Could not retrieve annual report ingestion job %s",
            job_id,
        )
        return jsonify({
            "success": False,
            "error": "Could not retrieve annual report ingestion status.",
        }), 500

    if not job:
        return jsonify({
            "success": False,
            "error": "Annual report ingestion job not found.",
        }), 404

    return jsonify({"success": True, "job": job}), 200
