from flask import Blueprint, jsonify, request
from uuid import UUID
from applications.services.public_errors import safe_error_summary
from applications.services.supabase_client import supabase


companies = Blueprint(
    "companies",
    __name__,
    url_prefix="/api"
)


PAGE_SIZE = 1000


def fetch_all_rows(query_builder):
    """
    Fetch all rows from Supabase in batches.

    Supabase/PostgREST commonly returns a maximum of 1000 rows
    per request, so we explicitly paginate using range().
    """

    all_rows = []
    offset = 0

    while True:
        response = (
            query_builder
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )

        batch = response.data or []

        all_rows.extend(batch)

        print(
            f"Fetched {len(batch)} rows "
            f"(offset={offset})"
        )

        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return all_rows


@companies.get("/companies")
def get_companies():
    """
    Return ALL WorkSphere target companies together
    with their persisted financial qualification.

    companies:
        Used for company identity/display information.

    company_financials:
        Used as the authoritative source for
        qualification_status.

    No qualification is recalculated here.
    """

    try:

        # ============================================================
        # 1. GET ALL WORKSPHERE TARGET COMPANIES
        # ============================================================

        companies_query = (
            supabase
            .table("companies")
            .select(
                "id, symbol, name, sector, "
                "target_for_worksphere, "
                "classification_status, sales_stage"
)
            .eq("target_for_worksphere", True)
            .order("name")
        )

        companies_data = fetch_all_rows(companies_query)

        print(
            f"TOTAL TARGET COMPANIES: {len(companies_data)}"
        )

        if not companies_data:
            return jsonify({
                "count": 0,
                "companies": []
            }), 200


        # ============================================================
        # 2. GET ALL PERSISTED FINANCIAL RECORDS
        # ============================================================

        financial_query = (
            supabase
            .table("company_financials")
            .select(
                "id, "
                "company_id, "
                "financial_year, "
                "previous_financial_year, "
                "revenue, "
                "previous_year_revenue, "
                "revenue_growth, "
                "revenue_unit, "
                "growth_source, "
                "qualification_status, "
                "qualification_source, "
                "annual_report_id, "
                "source_resolution_status, "
                "yahoo_ticker, "
                "error, "
                "created_at"
            )
            .order("created_at", desc=True)
        )

        financial_data = fetch_all_rows(financial_query)

        print(
            f"TOTAL FINANCIAL RECORDS: {len(financial_data)}"
        )


        # ============================================================
        # 3. MAP LATEST FINANCIAL RECORD TO EACH COMPANY
        # ============================================================

        qualifications = {}

        for financial in financial_data:

            company_id = financial.get("company_id")

            if not company_id:
                continue

            normalized_company_id = str(company_id)

            # Because records are ordered newest first,
            # the first record we encounter is the latest one.
            if normalized_company_id not in qualifications:
                qualifications[normalized_company_id] = financial


        print(
            f"COMPANIES WITH FINANCIAL DATA: "
            f"{len(qualifications)}"
        )


        # ============================================================
        # 4. BUILD RESPONSE
        # ============================================================

        result = []

        qualified_count = 0
        not_qualified_count = 0
        insufficient_count = 0

        for company in companies_data:

            company_id = company.get("id")

            normalized_company_id = str(company_id)

            financial = qualifications.get(
                normalized_company_id
            )


            # ========================================================
            # NO FINANCIAL RECORD
            # ========================================================

            if financial is None:

                qualification = {
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

                insufficient_count += 1


            # ========================================================
            # EXISTING FINANCIAL RECORD
            # ========================================================

            else:

                # THIS IS THE SOURCE OF TRUTH.
                qualification_status = (
                    financial.get("qualification_status")
                )

                qualification = {
                    "qualification_status":
                        qualification_status,

                    "qualified":
                        qualification_status == "qualified",

                    "revenue":
                        financial.get("revenue"),

                    "previous_year_revenue":
                        financial.get(
                            "previous_year_revenue"
                        ),

                    "revenue_growth":
                        financial.get(
                            "revenue_growth"
                        ),

                    "financial_year":
                        financial.get(
                            "financial_year"
                        ),

                    "previous_financial_year":
                        financial.get(
                            "previous_financial_year"
                        ),

                    "revenue_unit":
                        financial.get(
                            "revenue_unit"
                        ),

                    "growth_source":
                        financial.get(
                            "growth_source"
                        ),

                    "qualification_source":
                        financial.get(
                            "qualification_source"
                        ),

                    "revenue_threshold": 3000.0,
                    "growth_threshold": 10.0,

                    "revenue_pass": (
                        financial.get("revenue") is not None
                        and float(
                            financial.get("revenue")
                        ) > 3000
                    ),

                    "growth_pass": (
                        financial.get("revenue_growth") is not None
                        and float(
                            financial.get("revenue_growth")
                        ) > 10
                    ),

                    "financial_id":
                        financial.get("id"),

                    "annual_report_id":
                        financial.get(
                            "annual_report_id"
                        ),

                    "source_resolution_status":
                        financial.get(
                            "source_resolution_status"
                        ),

                    "yahoo_ticker":
                        financial.get(
                            "yahoo_ticker"
                        ),

                    "error": (
                        safe_error_summary(financial.get("error"))
                        if financial.get("error")
                        else None
                    ),
                }


                # Count persisted statuses only.
                if qualification_status == "qualified":
                    qualified_count += 1

                elif qualification_status == "not_qualified":
                    not_qualified_count += 1

                else:
                    insufficient_count += 1


            # ========================================================
            # ADD COMPANY + QUALIFICATION
            # ========================================================

            result.append({
                **company,
                "qualification": qualification,
            })


        # ============================================================
        # 5. DEBUG COUNTS
        # ============================================================

        print(
            "QUALIFICATION COUNTS:",
            {
                "total": len(result),
                "qualified": qualified_count,
                "not_qualified": not_qualified_count,
                "insufficient_data": insufficient_count,
            }
        )


        # ============================================================
        # 6. RETURN
        # ============================================================

        return jsonify({
            "count": len(result),

            "qualification_counts": {
                "qualified": qualified_count,
                "not_qualified": not_qualified_count,
                "insufficient_data": insufficient_count,
            },

            "companies": result,
        }), 200


    except Exception as error:

        print(f"Failed to fetch companies ({type(error).__name__}).")

        return jsonify({
            "error": "Failed to fetch companies",
        }), 500


@companies.patch("/companies/<string:company_id>/sales-stage")
def update_company_sales_stage(company_id):
    """Persist a company's sales pipeline stage."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "error": "Invalid request body",
            "details": "A JSON object with sales_stage is required.",
        }), 400
    sales_stage = payload.get("sales_stage")

    if sales_stage not in {"suspect", "prospect"}:
        return jsonify({
            "error": "Invalid sales stage",
            "details": "sales_stage must be 'suspect' or 'prospect'.",
        }), 400

    try:
        UUID(company_id)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid company ID",
            "details": "company_id must be a UUID.",
        }), 400

    try:
        # Verify that the company exists before updating it.
        existing = (
            supabase
            .table("companies")
            .select("id")
            .eq("id", company_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            return jsonify({
                "error": "Company not found",
                "company_id": company_id,
            }), 404

        updated = (
            supabase
            .table("companies")
            .update({"sales_stage": sales_stage})
            .eq("id", company_id)
            .select("id, sales_stage")
            .execute()
        )

        if not updated.data:
            return jsonify({
                "error": "Sales stage update failed",
                "details": "The database returned no updated company.",
            }), 500

        return jsonify({
            "company": updated.data[0],
        }), 200

    except Exception as error:
        print(
            "Failed to update company sales stage "
            f"({type(error).__name__})."
        )
        return jsonify({
            "error": "Failed to update sales stage",
        }), 500
