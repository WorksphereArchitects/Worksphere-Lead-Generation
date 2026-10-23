import traceback

from flask import Blueprint, jsonify
from uuid import UUID
from applications.services.gemini_engine import (
    _safe_processing_error,
    process_annual_report,
)
from applications.services.annual_reports import ReportAlreadyProcessingError
from applications.services.annual_report_ingestion import (
    load_report_from_company,
)
from applications.services.supabase_client import supabase

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
        result = process_annual_report(report_id)

        return jsonify({
            "success": True,
            "report": result["report"],
            "processing_run": result["processing_run"],
            "signals": result["signals"],
            "negative_evidence": result["negative_evidence"],
            "unresolved_signals": result["unresolved_signals"],
            "retrieval_stats": result["retrieval_stats"],
            "model_metadata": result["model_metadata"],
        }), 200

    except Exception as error:
        if isinstance(error, ReportAlreadyProcessingError):
            return jsonify({
                "success": False,
                "error": "Annual report is already processing.",
            }), 409
        if isinstance(error, LookupError):
            return jsonify({
                "success": False,
                "error": "Annual report not found.",
            }), 404
        return jsonify({
            "success": False,
            "error": _safe_processing_error(error),
        }), 500


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

    except Exception as error:
        print(
            f"Annual report ingestion failed "
            f"({type(error).__name__}): {error}"
        )
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": "Annual report ingestion failed. Check backend configuration and logs.",
        }), 500
