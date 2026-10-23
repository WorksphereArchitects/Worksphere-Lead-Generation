from __future__ import annotations

from typing import Any

from applications.services.supabase_client import supabase


def get_company_by_symbol(
    symbol: str,
) -> dict[str, Any] | None:
    """
    Get one company from Supabase using its NSE symbol.
    """

    if not symbol:
        raise ValueError("Company symbol is required.")

    response = (
        supabase
        .table("companies")
        .select("*")
        .eq("symbol", symbol.strip().upper())
        .maybe_single()
        .execute()
    )

    return response.data


def get_target_companies(
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Get companies currently marked as WorkSphere targets.
    """

    query = (
        supabase
        .table("companies")
        .select("*")
        .eq("target_for_worksphere", True)
        .order("name")
    )

    if limit is not None:
        query = query.limit(limit)

    response = query.execute()

    return response.data or []


def get_all_companies(
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Get all companies from Supabase.

    Useful for testing the pipeline across the complete NSE
    company universe.
    """

    query = (
        supabase
        .table("companies")
        .select("*")
        .order("name")
    )

    if limit is not None:
        query = query.limit(limit)

    response = query.execute()

    return response.data or []