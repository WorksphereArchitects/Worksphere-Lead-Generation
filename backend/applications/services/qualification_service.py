from __future__ import annotations

from typing import Any

from applications.services.supabase_client import supabase


# ============================================================
# QUALIFICATION THRESHOLDS
# ============================================================

REVENUE_THRESHOLD = 3000.0
GROWTH_THRESHOLD = 10.0


# ============================================================
# HELPERS
# ============================================================

def _to_float(value: Any) -> float | None:
    """
    Safely convert a value to float.

    Returns None when the value cannot be converted.
    """

    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ============================================================
# QUALIFICATION LOGIC
# ============================================================

def qualify_company(
    financial: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Apply the WorkSphere financial qualification rule.

    Qualification:

        revenue > 3000 Cr
        AND
        revenue_growth > 10%

    Gemini does not decide qualification.
    This function applies the deterministic business rule.
    """

    # --------------------------------------------------------
    # No financial data
    # --------------------------------------------------------

    if not financial:
        return {
            "qualification_status": "insufficient_data",
            "qualified": False,

            "revenue": None,
            "revenue_growth": None,
            "financial_year": None,

            "revenue_pass": False,
            "growth_pass": False,

            "revenue_threshold": REVENUE_THRESHOLD,
            "growth_threshold": GROWTH_THRESHOLD,

            "growth_source": None,
            "financial_id": None,
            "source_resolution_status": None,
        }

    # --------------------------------------------------------
    # Extract financial values
    # --------------------------------------------------------

    revenue = _to_float(
        financial.get("revenue")
    )

    revenue_growth = _to_float(
        financial.get("revenue_growth")
    )

    # --------------------------------------------------------
    # Apply individual conditions
    # --------------------------------------------------------

    revenue_pass = (
        revenue is not None
        and revenue > REVENUE_THRESHOLD
    )

    growth_pass = (
        revenue_growth is not None
        and revenue_growth > GROWTH_THRESHOLD
    )

    qualified = (
        revenue_pass
        and growth_pass
    )

    # --------------------------------------------------------
    # Determine status
    #
    # Missing either required metric means we don't have
    # enough information to make a financial qualification
    # decision.
    # --------------------------------------------------------

    if revenue is None or revenue_growth is None:
        qualification_status = "insufficient_data"

    elif qualified:
        qualification_status = "qualified"

    else:
        qualification_status = "not_qualified"

    # --------------------------------------------------------
    # Return complete qualification information
    # --------------------------------------------------------

    return {
        "qualification_status": qualification_status,
        "qualified": qualified,

        "revenue": revenue,
        "revenue_growth": revenue_growth,

        "financial_year": financial.get(
            "financial_year"
        ),

        "revenue_pass": revenue_pass,
        "growth_pass": growth_pass,

        "revenue_threshold": REVENUE_THRESHOLD,
        "growth_threshold": GROWTH_THRESHOLD,

        "growth_source": financial.get(
            "growth_source"
        ),

        "financial_id": financial.get(
            "id"
        ),

        "source_resolution_status": financial.get(
            "source_resolution_status"
        ),
    }


# ============================================================
# GET LATEST FINANCIAL FOR ONE COMPANY
# ============================================================

def get_latest_financial(
    company_id: str,
) -> dict[str, Any] | None:
    """
    Get the latest financial record for one company.
    """

    response = (
        supabase
        .table("company_financials")
        .select("*")
        .eq(
            "company_id",
            company_id
        )
        .order(
            "financial_year",
            desc=True
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


# ============================================================
# GET QUALIFICATION FOR ONE COMPANY
# ============================================================

def get_company_qualification(
    company_id: str,
) -> dict[str, Any]:
    """
    Get financial data and qualification result
    for one company.
    """

    financial = get_latest_financial(
        company_id
    )

    return qualify_company(
        financial
    )


# ============================================================
# GET QUALIFICATIONS FOR MULTIPLE COMPANIES
# ============================================================

def get_target_company_qualifications(
    companies: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Get qualification information for all supplied companies.

    Financial records are fetched in batches to avoid creating
    an oversized Supabase/PostgREST request.
    """

    if not companies:
        return {}

    company_ids = [
        company["id"]
        for company in companies
        if company.get("id")
    ]

    if not company_ids:
        return {}

    # Keep the request size reasonable.
    BATCH_SIZE = 100

    latest_financials: dict[
        str,
        dict[str, Any]
    ] = {}

    # --------------------------------------------------------
    # Fetch financial records in batches
    # --------------------------------------------------------

    for start in range(
        0,
        len(company_ids),
        BATCH_SIZE
    ):
        batch_ids = company_ids[
            start:start + BATCH_SIZE
        ]

        response = (
            supabase
            .table("company_financials")
            .select("*")
            .in_(
                "company_id",
                batch_ids
            )
            .order(
                "financial_year",
                desc=True
            )
            .execute()
        )

        financial_rows = (
            response.data or []
        )

        # Because rows are ordered by financial_year
        # descending, the first row encountered for each
        # company is its latest financial record.
        for financial in financial_rows:
            company_id = financial.get(
                "company_id"
            )

            if not company_id:
                continue

            if company_id not in latest_financials:
                latest_financials[
                    company_id
                ] = financial

    # --------------------------------------------------------
    # Calculate qualification
    # --------------------------------------------------------

    qualifications: dict[
        str,
        dict[str, Any]
    ] = {}

    for company in companies:
        company_id = company.get("id")

        if not company_id:
            continue

        financial = latest_financials.get(
            company_id
        )

        qualifications[company_id] = (
            qualify_company(
                financial
            )
        )

    return qualifications


# ============================================================
# GET ONLY QUALIFIED COMPANIES
# ============================================================

def get_qualified_companies() -> list[dict[str, Any]]:
    """
    Return companies whose latest financial record
    satisfies both qualification thresholds.

    Qualification is performed in Python.
    Gemini is not involved in this decision.
    """

    companies_response = (
        supabase
        .table("companies")
        .select(
            "id, symbol, name, sector, "
            "target_for_worksphere, "
            "classification_status"
        )
        .eq(
            "target_for_worksphere",
            True
        )
        .order(
            "name"
        )
        .execute()
    )

    companies = (
        companies_response.data or []
    )

    qualifications = (
        get_target_company_qualifications(
            companies
        )
    )

    qualified = []

    for company in companies:
        company_id = company.get(
            "id"
        )

        qualification = qualifications.get(
            company_id
        )

        if (
            qualification
            and qualification["qualified"]
        ):
            qualified.append({
                **company,
                "qualification": qualification,
            })

    return qualified