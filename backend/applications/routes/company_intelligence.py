from flask import Blueprint, jsonify, request
from applications.services.supabase_client import supabase
from applications.services.public_errors import safe_error_summary
from applications.services.news_intelligence import (
    NewsPersistenceFailure,
    NewsProviderFailure,
    NewsRunConflict,
    get_company_news,
    queue_company_news_ingestion,
)
import uuid
import logging

logger = logging.getLogger(__name__)

company_intelligence = Blueprint(
    "company_intelligence",
    __name__,
    url_prefix="/api/company-intelligence",
)

# ============================================================
# COMPANY LOOKUP
# ============================================================

def _get_company_by_identifier(identifier: str):
    """
    Resolve a company using either:
        1. NSE symbol
        2. Company UUID

    UUID lookup is only attempted when the identifier is
    actually a valid UUID. This prevents values like
    'ASIANPAINT' from ever being sent to the UUID column.
    """

    if not identifier:
        return None

    identifier = identifier.strip()

    # --------------------------------------------------------
    # 1. Try NSE symbol
    # --------------------------------------------------------

    response = (
        supabase
        .table("companies")
        .select("*")
        .eq("symbol", identifier.upper())
        .maybe_single()
        .execute()
    )

    # PostgREST's maybe_single().execute() returns None (not an API response
    # with data=None) when there are no matching rows.
    if response and response.data:
        return response.data

    # --------------------------------------------------------
    # 2. Only try UUID if identifier is actually a UUID
    # --------------------------------------------------------

    try:
        uuid.UUID(identifier)
    except ValueError:
        # Not a UUID.
        # Therefore do NOT query companies.id.
        return None

    response = (
        supabase
        .table("companies")
        .select("*")
        .eq("id", identifier)
        .maybe_single()
        .execute()
    )

    return response.data if response else None



def _get_company_qualification(company_id: str):
    """Return the latest persisted financial qualification."""

    response = (
        supabase
        .table("company_financials")
        .select(
            "id, company_id, financial_year, "
            "previous_financial_year, revenue, "
            "previous_year_revenue, revenue_growth, "
            "revenue_unit, growth_source, "
            "qualification_status, qualification_source, "
            "annual_report_id, source_resolution_status, "
            "yahoo_ticker, error"
        )
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    records = response.data or []

    if not records:
        return {
            "qualification_status": "insufficient_data",
            "qualified": False,
            "revenue": None,
            "previous_year_revenue": None,
            "revenue_growth": None,
            "financial_year": None,
            "previous_financial_year": None,
            "revenue_unit": None,
            "growth_source": None,
            "qualification_source": None,
            "revenue_threshold": 3000.0,
            "growth_threshold": 10.0,
            "revenue_pass": False,
            "growth_pass": False,
            "financial_id": None,
            "annual_report_id": None,
            "source_resolution_status": None,
            "yahoo_ticker": None,
            "error": None,
        }

    financial = records[0]
    status = financial.get("qualification_status")
    revenue = financial.get("revenue")
    growth = financial.get("revenue_growth")

    return {
        "qualification_status": status,
        "qualified": status == "qualified",
        "revenue": revenue,
        "previous_year_revenue": financial.get(
            "previous_year_revenue"
        ),
        "revenue_growth": growth,
        "financial_year": financial.get("financial_year"),
        "previous_financial_year": financial.get(
            "previous_financial_year"
        ),
        "revenue_unit": financial.get("revenue_unit"),
        "growth_source": financial.get("growth_source"),
        "qualification_source": financial.get(
            "qualification_source"
        ),
        "revenue_threshold": 3000.0,
        "growth_threshold": 10.0,
        "revenue_pass": (
            revenue is not None and float(revenue) > 3000
        ),
        "growth_pass": (
            growth is not None and float(growth) > 10
        ),
        "financial_id": financial.get("id"),
        "annual_report_id": financial.get("annual_report_id"),
        "source_resolution_status": financial.get(
            "source_resolution_status"
        ),
        "yahoo_ticker": financial.get("yahoo_ticker"),
        "error": (
            safe_error_summary(financial.get("error"))
            if financial.get("error")
            else None
        ),
    }


# ============================================================
# COMPANY EVIDENCE
# ============================================================

def _get_company_evidence(company_id: str):
    """
    Fetch current production evidence for a company.

    No validator or validation-status filtering is used.
    """

    response = (
        supabase
        .table("evidence")
        .select("*")
        .eq("company_id", company_id)
        .eq("is_current", True)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


# ============================================================
# COMPANY REPORTS
# ============================================================

def _get_company_reports(company_id: str):
    """
    Fetch annual reports associated with a company.
    """

    response = (
        supabase
        .table("annual_reports")
        .select("*")
        .eq("company_id", company_id)
        .order("financial_year", desc=True)
        .execute()
    )

    return response.data or []


# ============================================================
# PROCESSING RUNS
# ============================================================

def _get_processing_runs(company_id: str):
    """
    Fetch recent processing runs for a company.
    """

    response = (
        supabase
        .table("processing_runs")
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )

    return response.data or []


# ============================================================
# EVIDENCE SERIALIZER
# ============================================================

def _serialize_evidence(item):
    """
    Convert the production Supabase evidence row
    into the API response shape.
    """

    return {
        "id": item.get("id"),
        "company_id": item.get("company_id"),
        "source_type": item.get("source_type"),
        "source_id": item.get("source_id"),
        "financial_year": item.get("financial_year"),
        "evidence_type": item.get("evidence_type"),
        "event_state": item.get("event_state"),
        "headline": item.get("headline"),
        "summary": item.get("summary"),
        "why_it_matters": item.get("why_it_matters"),
        "statement": item.get("statement"),
        "excerpt": item.get("excerpt"),
        "location": item.get("location"),
        "investment": item.get("investment"),
        "physical_scale": item.get("physical_scale"),
        "timeline": item.get("timeline"),
        "physical_consequence": item.get("physical_consequence"),
        "supporting_facts": item.get("supporting_facts"),
        "source_candidate_ids": item.get("source_candidate_ids"),
        "source_sentence_indexes": item.get(
            "source_sentence_indexes"
        ),
        "source_resolution_status": item.get(
            "source_resolution_status"
        ),
        "confidence": item.get("confidence"),
        "is_current": item.get("is_current"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


# ============================================================
# ANNUAL REPORT SERIALIZER
# ============================================================

def _serialize_report(item):
    return {
        "id": item.get("id"),
        "company_id": item.get("company_id"),
        "financial_year": item.get("financial_year"),
        "report_title": item.get("report_title"),
        "nse_url": item.get("nse_url"),
        "local_file_path": item.get("local_file_path"),
        "google_drive_file_id": item.get(
            "google_drive_file_id"
        ),
        "page_count": item.get("page_count"),
        "processing_status": item.get(
            "processing_status"
        ),
        "processed_at": item.get("processed_at"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


# ============================================================
# LIST COMPANIES
# ============================================================

# @company_intelligence.route("", methods=["GET"])
# def list_companies():
#     """
#     Return company-level intelligence from the
#     production Supabase architecture.
#     """

#     try:
#         response = (
#             supabase
#             .table("companies")
#             .select("*")
#             .eq("target_for_worksphere", True)
#             .order("name")
#             .execute()
#         )

#         companies = response.data or []

#         result = []

#         for company in companies:
#             company_id = company["id"]

#             evidence_records = _get_company_evidence(
#                 company_id
#             )

#             reports = _get_company_reports(
#                 company_id
#             )

#             signals = sorted(
#                 {
#                     item.get("evidence_type")
#                     for item in evidence_records
#                     if item.get("evidence_type")
#                 }
#             )

#             result.append({
#                 "company": company.get("name"),
#                 "company_id": company_id,
#                 "symbol": company.get("symbol"),
#                 "sector": company.get("sector"),
#                 "target_for_worksphere": company.get(
#                     "target_for_worksphere"
#                 ),
#                 "classification_status": company.get(
#                     "classification_status"
#                 ),
#                 "report_count": len(reports),
#                 "evidence_count": len(
#                     evidence_records
#                 ),
#                 "signals": signals,
#             })

#         return jsonify({
#             "count": len(result),
#             "companies": result,
#         }), 200

#     except Exception as error:
#         return jsonify({
#             "error": "Failed to fetch company intelligence",
#             "details": str(error),
#         }), 500


# ============================================================
# SINGLE COMPANY INTELLIGENCE
# ============================================================

@company_intelligence.route(
    "/<string:identifier>",
    methods=["GET"]
)
def get_company_intelligence(identifier):
    """
    Return detailed production intelligence for one company.

    The identifier may be either:
        - NSE symbol
        - company UUID
    """

    try:

        # ----------------------------------------------------
        # Resolve company
        # ----------------------------------------------------

        company = _get_company_by_identifier(
            identifier
        )

        if not company:
            return jsonify({
                "error": "Company not found",
                "identifier": identifier,
            }), 404

        # ----------------------------------------------------
        # IMPORTANT:
        # Everything after this point uses the actual UUID
        # returned from the companies table.
        # ----------------------------------------------------

        company_id = company["id"]
        qualification = _get_company_qualification(company_id)
        reports = _get_company_reports(
            company_id
        )

        evidence_records = _get_company_evidence(
            company_id
        )

        processing_runs = [
            {
                **run,
                "error_message": (
                    safe_error_summary(run.get("error_message"))
                    if run.get("error_message")
                    else None
                ),
            }
            for run in _get_processing_runs(company_id)
        ]

        # ----------------------------------------------------
        # Signal types
        # ----------------------------------------------------

        signals = sorted(
            {
                item.get("evidence_type")
                for item in evidence_records
                if item.get("evidence_type")
            }
        )

        # ----------------------------------------------------
        # Resolution counts
        # ----------------------------------------------------

        resolved_count = sum(
            1
            for item in evidence_records
            if item.get(
                "source_resolution_status"
            ) == "resolved"
        )

        unresolved_count = sum(
            1
            for item in evidence_records
            if item.get(
                "source_resolution_status"
            ) == "unresolved"
        )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        return jsonify({
            "qualification": qualification,
            "company": {
                "id": company.get("id"),
                "name": company.get("name"),
                "symbol": company.get("symbol"),
                "sector": company.get("sector"),
                "target_for_worksphere": company.get(
                    "target_for_worksphere"
                ),
                "classification_status": company.get(
                    "classification_status"
                ),
                "sales_stage": company.get("sales_stage") or "suspect",
            },

            "summary": {
                "report_count": len(reports),
                "evidence_count": len(
                    evidence_records
                ),
                "resolved_evidence_count": (
                    resolved_count
                ),
                "unresolved_evidence_count": (
                    unresolved_count
                ),
                "signals": signals,
            },

            "reports": [
                _serialize_report(report)
                for report in reports
            ],

            "evidence": [
                _serialize_evidence(item)
                for item in evidence_records
            ],

            "processing_runs": processing_runs,

        }), 200

    except Exception:
        # Keep the client response generic while preserving the full traceback
        # in the backend log for diagnosis.
        logger.exception("Failed to fetch company intelligence")
        return jsonify({
            "error": "Failed to fetch company intelligence",
        }), 500


@company_intelligence.route(
    "/<string:identifier>/news",
    methods=["GET"],
)
def get_company_news_route(identifier):
    try:
        company = _get_company_by_identifier(identifier)
    except Exception:
        logger.exception("Company lookup failed for news retrieval")
        return jsonify({"error": "Company lookup failed"}), 500
    if not company:
        return jsonify({"error": "Company not found"}), 404

    try:
        limit_value = request.args.get("limit", "50")
        if not limit_value.isdigit() or not 1 <= int(limit_value) <= 100:
            return jsonify({"error": "limit must be between 1 and 100"}), 400
        result = get_company_news(company["id"], limit=int(limit_value))
        return jsonify({"company_id": company["id"], **result}), 200
    except NewsPersistenceFailure as error:
        return jsonify({"error": safe_error_summary(error)}), 500
    except Exception:
        logger.exception("Failed to retrieve company news")
        return jsonify({"error": "Failed to retrieve company news"}), 500


@company_intelligence.route(
    "/<string:identifier>/news/ingest",
    methods=["POST"],
)
def ingest_company_news_route(identifier):
    try:
        company = _get_company_by_identifier(identifier)
    except Exception:
        logger.exception("Company lookup failed for news ingestion")
        return jsonify({"error": "Company lookup failed"}), 500
    if not company:
        return jsonify({"error": "Company not found"}), 404

    days_value = request.args.get("days", "30")
    if not days_value.isdigit() or not 1 <= int(days_value) <= 90:
        return jsonify({"error": "days must be between 1 and 90"}), 400

    try:
        run = queue_company_news_ingestion(
            company, lookback_days=int(days_value)
        )
        return jsonify({
            "status": "processing",
            "company_id": company["id"],
            "run": run,
        }), 202
    except NewsRunConflict:
        return jsonify({"error": "News ingestion is already running for this company."}), 409
    except NewsProviderFailure as error:
        return jsonify({"error": safe_error_summary(error, "News provider request failed.")}), 502
    except NewsPersistenceFailure as error:
        return jsonify({"error": safe_error_summary(error, "News persistence failed.")}), 500
    except ValueError as error:
        return jsonify({"error": safe_error_summary(error)}), 400
    except Exception:
        logger.exception("Company news ingestion failed")
        return jsonify({"error": "Company news ingestion failed"}), 500
