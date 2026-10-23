from __future__ import annotations

from typing import Any

from applications.services.supabase_client import supabase


# ============================================================
# CREATE / UPSERT
# ============================================================

def upsert_financial_metrics(
    company_id: str,
    annual_report_id: str,
    financial_year: str,
    revenue: float | None = None,
    previous_year_revenue: float | None = None,
    revenue_growth: float | None = None,
    revenue_unit: str = "INR_CRORE",
    growth_source: str = "unavailable",
    source_candidate_ids: list[Any] | None = None,
    source_sentence_indexes: list[Any] | None = None,
    source_resolution_status: str = "resolved",
) -> dict[str, Any]:
    """
    Insert or update financial metrics extracted from an annual report.

    The company_financials table uses:
        company_id + financial_year

    as the unique identity for a company's financial metrics.
    """

    if not company_id:
        raise ValueError("Company ID is required.")

    if not annual_report_id:
        raise ValueError("Annual report ID is required.")

    if not financial_year:
        raise ValueError("Financial year is required.")

    payload = {
        "company_id": company_id,
        "annual_report_id": annual_report_id,
        "financial_year": financial_year,
        "revenue": revenue,
        "previous_year_revenue": previous_year_revenue,
        "revenue_growth": revenue_growth,
        "revenue_unit": revenue_unit,
        "growth_source": growth_source,
        "source_candidate_ids": (
            source_candidate_ids
            if source_candidate_ids is not None
            else []
        ),
        "source_sentence_indexes": (
            source_sentence_indexes
            if source_sentence_indexes is not None
            else []
        ),
        "source_resolution_status": source_resolution_status,
    }

    response = (
        supabase
        .table("company_financials")
        .upsert(
            payload,
            on_conflict="company_id,financial_year",
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Failed to upsert company financial metrics."
        )

    return response.data[0]


# ============================================================
# READ
# ============================================================

def get_financial_metrics(
    financial_id: str,
) -> dict[str, Any] | None:
    """
    Get one financial metrics record by ID.
    """

    response = (
        supabase
        .table("company_financials")
        .select("*")
        .eq("id", financial_id)
        .maybe_single()
        .execute()
    )

    return response.data


def get_company_financials(
    company_id: str,
) -> list[dict[str, Any]]:
    """
    Get all financial records for a company.
    """

    response = (
        supabase
        .table("company_financials")
        .select("*")
        .eq("company_id", company_id)
        .order(
            "financial_year",
            desc=True,
        )
        .execute()
    )

    return response.data or []


def get_financials_for_report(
    annual_report_id: str,
) -> dict[str, Any] | None:
    """
    Get financial metrics associated with one annual report.
    """

    response = (
        supabase
        .table("company_financials")
        .select("*")
        .eq("annual_report_id", annual_report_id)
        .maybe_single()
        .execute()
    )

    return response.data


def get_latest_company_financials(
    company_id: str,
) -> dict[str, Any] | None:
    """
    Get the latest financial metrics for a company.
    """

    response = (
        supabase
        .table("company_financials")
        .select("*")
        .eq("company_id", company_id)
        .order(
            "financial_year",
            desc=True,
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


# ============================================================
# UPDATE
# ============================================================

def update_financial_metrics(
    financial_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing financial metrics record.
    """

    if not updates:
        raise ValueError(
            "No fields supplied for financial metrics update."
        )

    response = (
        supabase
        .table("company_financials")
        .update(updates)
        .eq("id", financial_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Financial metrics not found or update failed: "
            f"{financial_id}"
        )

    return response.data[0]


# ============================================================
# DELETE
# ============================================================

def delete_financial_metrics(
    financial_id: str,
) -> bool:
    """
    Delete one financial metrics record.
    """

    response = (
        supabase
        .table("company_financials")
        .delete()
        .eq("id", financial_id)
        .execute()
    )

    return bool(response.data)