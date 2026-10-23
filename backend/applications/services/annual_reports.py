from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from applications.services.supabase_client import supabase


class ReportAlreadyProcessingError(RuntimeError):
    """Raised when another request currently owns this report's processing."""


# ============================================================
# CREATE
# ============================================================

def create_annual_report(
    company_id: str,
    financial_year: str,
    report_title: str | None = None,
    nse_url: str | None = None,
    local_file_path: str | None = None,
    google_drive_file_id: str | None = None,
    page_count: int | None = None,
    processing_status: str = "pending",
) -> dict[str, Any]:
    """
    Create a new annual report record in Supabase.

    The combination of company_id + financial_year is unique,
    so use upsert_annual_report() when the record may already exist.
    """

    payload = {
        "company_id": company_id,
        "financial_year": financial_year,
        "report_title": report_title,
        "nse_url": nse_url,
        "local_file_path": local_file_path,
        "google_drive_file_id": google_drive_file_id,
        "page_count": page_count,
        "processing_status": processing_status,
    }

    response = (
        supabase
        .table("annual_reports")
        .insert(payload)
        .select("*")
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Failed to create annual report record."
        )

    return response.data[0]


# ============================================================
# READ
# ============================================================

def get_annual_report(
    report_id: str,
) -> dict[str, Any] | None:
    """
    Get one annual report by its Supabase UUID.
    """

    response = (
        supabase
        .table("annual_reports")
        .select("*")
        .eq("id", report_id)
        .maybe_single()
        .execute()
    )

    return response.data


def get_annual_report_for_company(
    company_id: str,
    financial_year: str,
) -> dict[str, Any] | None:
    """
    Get the annual report for a company and financial year.
    """

    response = (
        supabase
        .table("annual_reports")
        .select("*")
        .eq("company_id", company_id)
        .eq("financial_year", financial_year)
        .maybe_single()
        .execute()
    )

    return response.data


def get_latest_annual_report(
    company_id: str,
) -> dict[str, Any] | None:
    """
    Get the latest stored annual report for a company.

    financial_year should be stored consistently, for example:
        2024
        2025
        2026
    """

    response = (
        supabase
        .table("annual_reports")
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


def get_company_annual_reports(
    company_id: str,
) -> list[dict[str, Any]]:
    """
    Get all annual reports belonging to a company.
    """

    response = (
        supabase
        .table("annual_reports")
        .select("*")
        .eq("company_id", company_id)
        .order(
            "financial_year",
            desc=True,
        )
        .execute()
    )

    return response.data or []


def get_annual_reports_by_status(
    processing_status: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Get annual reports by processing status.

    Example statuses:
        pending
        processing
        completed
        failed
    """

    response = (
        supabase
        .table("annual_reports")
        .select("*")
        .eq(
            "processing_status",
            processing_status,
        )
        .order(
            "created_at",
            desc=False,
        )
        .limit(limit)
        .execute()
    )

    return response.data or []


# ============================================================
# UPDATE
# ============================================================

def update_annual_report(
    report_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """
    Update arbitrary annual report fields.
    """

    if not updates:
        raise ValueError(
            "No fields supplied for annual report update."
        )

    response = (
        supabase
        .table("annual_reports")
        .update(updates)
        .eq("id", report_id)
        .select("*")
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            f"Annual report not found or update failed: {report_id}"
        )

    return response.data[0]


def update_processing_status(
    report_id: str,
    processing_status: str,
) -> dict[str, Any]:
    """
    Update only the processing status.
    """

    return update_annual_report(
        report_id,
        {
            "processing_status": processing_status,
        },
    )


def mark_report_processing(
    report_id: str,
) -> dict[str, Any]:
    """
    Mark an annual report as currently being processed.
    """

    return update_processing_status(
        report_id,
        "processing",
    )


def claim_report_for_processing(report_id: str) -> dict[str, Any]:
    """Atomically claim a pending, completed, or failed report for one run."""
    response = (
        supabase.table("annual_reports")
        .update({"processing_status": "processing"})
        .eq("id", report_id)
        .in_("processing_status", ["pending", "completed", "failed"])
        .select("*")
        .execute()
    )
    if not response.data:
        current = get_annual_report(report_id)
        if current is None:
            raise RuntimeError(f"Annual report not found: {report_id}")
        if current.get("processing_status") == "processing":
            raise ReportAlreadyProcessingError(
                "Annual report is already processing."
            )
        raise RuntimeError("Annual report could not be claimed for processing.")
    return response.data[0]


def mark_report_processed(
    report_id: str,
    page_count: int | None = None,
    google_drive_file_id: str | None = None,
) -> dict[str, Any]:
    """
    Mark an annual report as successfully processed.
    """

    updates: dict[str, Any] = {
        "processing_status": "completed",
        "processed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    if page_count is not None:
        updates["page_count"] = page_count

    if google_drive_file_id is not None:
        updates["google_drive_file_id"] = (
            google_drive_file_id
        )

    return update_annual_report(
        report_id,
        updates,
    )


def mark_report_failed(
    report_id: str,
) -> dict[str, Any]:
    """
    Mark an annual report as failed.
    """

    return update_annual_report(
        report_id,
        {
            "processing_status": "failed",
        },
    )


# ============================================================
# UPSERT
# ============================================================

def upsert_annual_report(
    company_id: str,
    financial_year: str,
    report_title: str | None = None,
    nse_url: str | None = None,
    local_file_path: str | None = None,
    google_drive_file_id: str | None = None,
    page_count: int | None = None,
    processing_status: str = "pending",
) -> dict[str, Any]:
    """
    Insert or update an annual report.

    Supabase uses the unique constraint:
        company_id + financial_year

    This makes ingestion idempotent.
    """

    payload = {
        "company_id": company_id,
        "financial_year": financial_year,
        "report_title": report_title,
        "nse_url": nse_url,
        "local_file_path": local_file_path,
        "google_drive_file_id": google_drive_file_id,
        "page_count": page_count,
        "processing_status": processing_status,
    }

    response = (
        supabase.table("annual_reports")
        .select("id, processing_status")
        .eq("company_id", company_id)
        .eq("financial_year", financial_year)
        .maybe_single()
        .execute()
    )

    existing = response.data if response is not None else None

    if existing and existing.get("processing_status"):
        # Refreshing the NSE metadata must not erase a running, completed, or
        # failed processing state. The UI exposes an explicit safe retry.
        payload["processing_status"] = existing["processing_status"]

    response = (
        supabase
        .table("annual_reports")
        .upsert(
            payload,
            on_conflict="company_id,financial_year",
        )
        .select("*")
        .execute()
    )

    if response is None:
        raise RuntimeError(
            "Supabase returned no response while upserting annual report."
        )

    if not response.data:
        raise RuntimeError(
            "Failed to upsert annual report."
        )

    return response.data[0]



# ============================================================
# DELETE
# ============================================================

def delete_annual_report(
    report_id: str,
) -> bool:
    """
    Delete an annual report database record.

    NOTE:
    This does NOT delete the corresponding Google Drive PDF.
    Google Drive deletion should be handled separately.
    """

    response = (
        supabase
        .table("annual_reports")
        .delete()
        .eq("id", report_id)
        .execute()
    )

    return bool(response.data)
