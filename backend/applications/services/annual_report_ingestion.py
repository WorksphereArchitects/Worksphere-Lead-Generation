from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from typing import Any

import requests

from nse import NSE
from pypdf import PdfReader

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from applications.services.annual_reports import (
    upsert_annual_report,
)


# ============================================================
# CONFIGURATION
# ============================================================

DOWNLOAD_FOLDER = Path(
    "storage/reports"
)

BASE_DIR = Path(
    __file__
).resolve().parents[2]

CREDENTIALS_FILE = (
    BASE_DIR / "credentials.json"
)

TOKEN_FILE = (
    BASE_DIR / "token.json"
)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file"
]


# Google Drive:
# WorkSphere_Test / Annual_Reports
ANNUAL_REPORTS_FOLDER_ID = (
    "1BShHAs--k0cIiJyaKIU6WJBlEcOzS6mF"
)


# ============================================================
# GOOGLE DRIVE AUTHENTICATION
# ============================================================

def authenticate_google_drive():
    """
    Authenticate with Google Drive.

    This local OAuth flow is suitable for local development.

    For cloud deployment, this should later be replaced by
    service-account authentication.
    """

    credentials = None

    # --------------------------------------------------------
    # Step 1 — Load existing credentials
    # --------------------------------------------------------

    if TOKEN_FILE.exists():
        credentials = (
            Credentials
            .from_authorized_user_file(
                TOKEN_FILE,
                SCOPES,
            )
        )

    # --------------------------------------------------------
    # Step 2 — Refresh expired credentials
    # --------------------------------------------------------

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        print(
            "Refreshing Google Drive credentials..."
        )

        credentials.refresh(
            Request()
        )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    # --------------------------------------------------------
    # Step 3 — First-time authentication
    # --------------------------------------------------------

    if (
        not credentials
        or not credentials.valid
    ):
        print(
            "Google Drive authorization required..."
        )

        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                "Google Drive credentials.json "
                f"not found at: {CREDENTIALS_FILE}"
            )

        flow = (
            InstalledAppFlow
            .from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES,
            )
        )

        credentials = flow.run_local_server(
            port=0
        )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    # --------------------------------------------------------
    # Step 4 — Build Drive service
    # --------------------------------------------------------

    return build(
        "drive",
        "v3",
        credentials=credentials,
    )


# ============================================================
# GOOGLE DRIVE UPLOAD
# ============================================================

def upload_report_to_drive(
    service,
    file_path: str | Path,
) -> dict[str, Any]:
    """
    Upload an annual report PDF to Google Drive.

    If the exact filename already exists inside the
    Annual_Reports folder, reuse that file instead of
    uploading a duplicate.

    Returns Drive metadata plus:
        already_exists: bool
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {file_path}"
        )

    file_name = file_path.name

    # --------------------------------------------------------
    # Escape filename for Drive query
    # --------------------------------------------------------

    escaped_file_name = (
        file_name
        .replace("\\", "\\\\")
        .replace("'", "\\'")
    )

    query = (
        f"name = '{escaped_file_name}' "
        f"and '{ANNUAL_REPORTS_FOLDER_ID}' in parents "
        f"and trashed = false"
    )

    # --------------------------------------------------------
    # Check for existing file
    # --------------------------------------------------------

    existing_files = (
        service
        .files()
        .list(
            q=query,
            spaces="drive",
            fields=(
                "files("
                "id,"
                "name,"
                "mimeType,"
                "size,"
                "parents"
                ")"
            ),
            pageSize=10,
        )
        .execute()
    )

    files = existing_files.get(
        "files",
        [],
    )

    if files:
        existing_file = files[0]

        existing_file[
            "already_exists"
        ] = True

        print(
            "Google Drive file already exists:"
        )

        print(
            f"  {existing_file.get('name')}"
        )

        print(
            f"  ID: {existing_file.get('id')}"
        )

        return existing_file

    # --------------------------------------------------------
    # Upload new file
    # --------------------------------------------------------

    file_metadata = {
        "name": file_name,
        "parents": [
            ANNUAL_REPORTS_FOLDER_ID
        ],
    }

    media = MediaFileUpload(
        str(file_path),
        mimetype="application/pdf",
        resumable=True,
    )

    uploaded_file = (
        service
        .files()
        .create(
            body=file_metadata,
            media_body=media,
            fields=(
                "id,"
                "name,"
                "mimeType,"
                "size,"
                "parents"
            ),
        )
        .execute()
    )

    uploaded_file[
        "already_exists"
    ] = False

    print(
        "Uploaded annual report to Google Drive:"
    )

    print(
        f"  {uploaded_file.get('name')}"
    )

    print(
        f"  ID: {uploaded_file.get('id')}"
    )

    return uploaded_file


# ============================================================
# NSE ANNUAL REPORT DISCOVERY
# ============================================================

def fetch_latest_annual_report(
    nse: NSE,
    company: dict[str, Any],
    download_folder: Path | None = None,
) -> dict[str, Any] | None:
    """
    Fetch the latest annual report available through NSE
    for a company.

    Important NSE behavior:

    The NSE annual report response uses `fileName` to contain
    the report URL, for example:

    https://nsearchives.nseindia.com/annual_reports/
    AR_29385_ASIANPAINT_2025_2026_A_26278926_12062026160918.pdf

    Therefore this function preserves TWO separate values:

        nse_url
            Full NSE URL.

        file_name
            Filename extracted from that URL.

    Example:

        nse_url:
        https://nsearchives.nseindia.com/annual_reports/
        AR_29385_ASIANPAINT_2025_2026_A_26278926_12062026160918.pdf

        file_name:
        AR_29385_ASIANPAINT_2025_2026_A_26278926_12062026160918.pdf

    Returns None if no annual report is available.
    """

    if download_folder is None:
        download_folder = DOWNLOAD_FOLDER

    download_folder = Path(
        download_folder
    )

    download_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    symbol = str(
        company.get("symbol", "")
    ).strip()

    if not symbol:
        raise ValueError(
            "Company is missing symbol."
        )

    company_name = str(
        company.get(
            "company_name",
            company.get("name", ""),
        )
    ).strip()

    # --------------------------------------------------------
    # Ask NSE for available annual reports
    # --------------------------------------------------------

    reports = nse.annual_reports(
        symbol
    )

    # --------------------------------------------------------
    # Normalize NSE annual-report response
    # --------------------------------------------------------
    #
    # Depending on the installed nse package version,
    # annual_reports() may return either:
    #
    #   1. a list of report dictionaries, or
    #   2. a response dictionary containing the list
    #      under "data".
    #
    # Normalize both shapes here.
    # --------------------------------------------------------

    if isinstance(reports, dict):
        reports = reports.get(
            "data",
            []
        )

    if not reports:
        print(
            f"No annual reports found for {symbol}."
        )

        return None

    if not isinstance(reports, list):
        raise TypeError(
            "Unexpected NSE annual_reports() response type: "
            f"{type(reports).__name__}"
        )

    # --------------------------------------------------------
    # Keep entries that are report dictionaries and have
    # a report URL/filename
    # --------------------------------------------------------

    reports_with_files = [
        report
        for report in reports
        if isinstance(report, dict)
        and report.get("fileName")
    ]

    if not reports_with_files:
        print(
            f"No downloadable annual report found "
            f"for {symbol}."
        )

        return None

    # --------------------------------------------------------
    # Sort reports by financial year / submission
    #
    # NSE metadata is not always perfectly consistent,
    # so sorting uses several available fields.
    # --------------------------------------------------------

    def sort_key(report):
        return (
            str(
                report.get(
                    "toYr",
                    "",
                )
            ),
            str(
                report.get(
                    "submissionDate",
                    report.get(
                        "originalSubmissionDate",
                        "",
                    ),
                )
            ),
            str(
                report.get(
                    "fileName",
                    "",
                )
            ),
        )

    reports_with_files.sort(
        key=sort_key,
        reverse=True,
    )

    selected_report = (
        reports_with_files[0]
    )

    # --------------------------------------------------------
    # Determine financial year
    # --------------------------------------------------------

    financial_year = str(
        selected_report.get(
            "toYr",
            "",
        )
    ).strip()

    # --------------------------------------------------------
    # Extract NSE URL and filename
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # NSE's `fileName` contains the complete URL.
    #
    # Example:
    #
    # https://nsearchives.nseindia.com/annual_reports/
    # AR_29385_ASIANPAINT_2025_2026_A_26278926_12062026160918.pdf
    #
    # We preserve the URL as `nse_url` and extract only
    # the filename as `file_name`.
    # --------------------------------------------------------

    nse_url = str(
        selected_report.get(
            "fileName",
            "",
        )
    ).strip()

    if not nse_url:
        return None

    file_name = Path(
        nse_url
    ).name

    if not file_name:
        raise ValueError(
            f"Could not extract filename from NSE URL: {nse_url}"
        )

    local_path = (
        download_folder / file_name
    )

    # --------------------------------------------------------
    # Local cache check
    # --------------------------------------------------------

    if local_path.exists():
        print(
            "Annual report already exists locally:"
        )

        print(
            f"  {local_path}"
        )

        return {
            "company_name": company_name,
            "symbol": symbol,
            "sector": company.get(
                "sector",
                "",
            ),
            "target_for_worksphere": company.get(
                "target_for_worksphere",
                "",
            ),
            "classification_status": company.get(
                "classification_status",
                "",
            ),
            "report": selected_report,
            "financial_year": financial_year,

            # IMPORTANT:
            # Keep URL and filename separate.
            "nse_url": nse_url,
            "file_name": file_name,

            "file_path": local_path,
            "downloaded": False,
            "local_cache_hit": True,
        }

    # --------------------------------------------------------
    # Download report from NSE
    # --------------------------------------------------------

    print(
        f"Downloading annual report for {symbol}..."
    )

    try:
        downloaded_path = (
            nse.download_document(
                selected_report,
            )
        )

    except TypeError:
        # Some versions/signatures may require
        # the report's fileName directly.
        downloaded_path = (
            nse.download_document(
                selected_report.get(
                    "fileName"
                )
            )
        )

    # --------------------------------------------------------
    # Normalize returned path
    # --------------------------------------------------------

    if downloaded_path:
        downloaded_path = Path(
            downloaded_path
        )

        if downloaded_path.exists():
            final_path = downloaded_path

        else:
            final_path = local_path

    else:
        final_path = local_path

    if not final_path.exists():
        raise FileNotFoundError(
            "NSE reported a successful download, "
            "but the PDF could not be found at: "
            f"{final_path}"
        )

    print(
        "Annual report downloaded:"
    )

    print(
        f"  {final_path}"
    )

    return {
        "company_name": company_name,
        "symbol": symbol,
        "sector": company.get(
            "sector",
            "",
        ),
        "target_for_worksphere": company.get(
            "target_for_worksphere",
            "",
        ),
        "classification_status": company.get(
            "classification_status",
            "",
        ),
        "report": selected_report,
        "financial_year": financial_year,

        # IMPORTANT:
        # Keep URL and filename separate.
        "nse_url": nse_url,
        "file_name": file_name,

        "file_path": final_path,
        "downloaded": True,
        "local_cache_hit": False,
    }


# ============================================================
# FINANCIALFILINGS ANNUAL REPORT DISCOVERY
# ============================================================

def fetch_annual_report_financialfilings(
    company: dict[str, Any],
    download_folder: Path | None = None,
) -> dict[str, Any] | None:
    """
    Fetch the current financial year's annual report using FinancialFilings.

    The company's ISIN must already be stored in the Supabase company record.

    Financial year selection:
        Uses date.today().year automatically. For example, in 2026 this
        selects filings whose FinancialFilings `fiscal_year` is 2026
        (FY 2025-26).

    Credit usage:
        The filing-list request costs one credit. The CDN is attempted first
        without an API credit. Only if that download fails or is not a valid
        PDF, /filings/{id}/document/ is called as a one-credit fallback.

    Returns a result compatible with the existing ingestion result shape,
    with FinancialFilings provenance fields added. This function does not
    change or replace the existing NSE functions.
    """

    if download_folder is None:
        download_folder = DOWNLOAD_FOLDER

    download_folder = Path(download_folder)
    download_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    symbol = str(
        company.get("symbol", "")
    ).strip()

    if not symbol:
        raise ValueError(
            "Company is missing symbol."
        )

    isin = str(
        company.get("isin", "")
    ).strip().upper()

    if not isin:
        raise ValueError(
            f"Company {symbol} is missing ISIN. "
            "Populate companies.isin in Supabase first."
        )

    api_key = os.getenv("FR_API_KEY")

    if not api_key:
        raise RuntimeError(
            "FR_API_KEY environment variable is missing."
        )

    # The API's fiscal_year is the ending year of the financial year.
    # Example: fiscal_year=2026 represents FY 2025-26.
    financial_year = str(date.today().year)

    api_url = "https://api.financialreports.eu/filings/"

    params = {
        "company_isin": isin,
        "primary_annual_report": "true",
        "ordering": "-release_datetime",
        "page_size": 100,
        "view": "full",
    }

    print(
        f"Searching FinancialFilings for {symbol} "
        f"(ISIN: {isin}, FY: {financial_year})..."
    )

    response = requests.get(
        api_url,
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
        },
        params=params,
        timeout=60,
    )

    print(
        "FinancialFilings metadata credits charged:",
        response.headers.get(
            "X-Credits-Charged",
            "not supplied",
        ),
    )

    response.raise_for_status()

    payload = response.json()

    if isinstance(payload, dict):
        filings = payload.get(
            "results",
            [],
        )
    elif isinstance(payload, list):
        filings = payload
    else:
        raise TypeError(
            "Unexpected FinancialFilings response type: "
            f"{type(payload).__name__}"
        )

    if not filings:
        print(
            f"No annual-report filings returned for {symbol}."
        )
        return None

    # --------------------------------------------------------
    # Select only the exact current financial year
    # --------------------------------------------------------

    matching_filings = [
        filing
        for filing in filings
        if isinstance(filing, dict)
        and str(
            filing.get("fiscal_year", "")
        ) == financial_year
    ]

    if not matching_filings:
        available_years = sorted(
            {
                str(filing.get("fiscal_year"))
                for filing in filings
                if isinstance(filing, dict)
                and filing.get("fiscal_year") is not None
            }
        )

        print(
            f"No annual report found for {symbol} "
            f"for FY {financial_year}. "
            f"Available fiscal years: {available_years or 'not provided'}"
        )

        return None

    # Prefer the most recently released matching filing.
    matching_filings.sort(
        key=lambda filing: (
            str(filing.get("release_datetime", "")),
            str(filing.get("filing_date", "")),
        ),
        reverse=True,
    )

    selected_report = matching_filings[0]

    # This ingestion path is specifically for original PDF reports.
    file_extension = str(
        selected_report.get("file_extension", "")
    ).strip().upper()

    if file_extension != "PDF":
        raise ValueError(
            f"FinancialFilings selected filing "
            f"{selected_report.get('id')} with extension "
            f"{file_extension or 'unknown'}, not PDF."
        )

    # API responses have used both `document_url` and `document`.
    cdn_url = (
        selected_report.get("document_url")
        or selected_report.get("document")
    )

    if not cdn_url:
        raise ValueError(
            "Selected FinancialFilings record has no "
            "document_url or document field."
        )

    if not str(cdn_url).startswith("https://"):
        raise ValueError(
            f"Unexpected FinancialFilings document URL: {cdn_url}"
        )

    filing_id = selected_report.get("id")

    if not filing_id:
        raise ValueError(
            "Selected FinancialFilings record is missing its filing ID."
        )

    company_name = str(
        company.get(
            "company_name",
            company.get("name", ""),
        )
    ).strip()

    file_name = (
        f"{symbol}_{isin}_FY{financial_year}_"
        f"{filing_id}.pdf"
    )

    local_path = download_folder / file_name

    # --------------------------------------------------------
    # Local cache check
    # --------------------------------------------------------

    if local_path.exists():
        with local_path.open("rb") as cached_file:
            is_valid_pdf = cached_file.read(5) == b"%PDF-"

        if is_valid_pdf:
            print(
                "Annual report already exists locally:"
            )
            print(
                f"  {local_path}"
            )

            return {
                "company_name": company_name,
                "symbol": symbol,
                "sector": company.get("sector", ""),
                "target_for_worksphere": company.get(
                    "target_for_worksphere",
                    "",
                ),
                "classification_status": company.get(
                    "classification_status",
                    "",
                ),
                "report": selected_report,
                "financial_year": financial_year,
                "nse_url": None,
                "file_name": file_name,
                "file_path": local_path,
                "downloaded": False,
                "local_cache_hit": True,
                "source_provider": "financialfilings",
                "source_filing_id": str(filing_id),
                "source_document_url": cdn_url,
                "source_company_isin": isin,
            }

        # Remove an invalid/incomplete cached file before downloading again.
        local_path.unlink()

    # --------------------------------------------------------
    # Download helpers
    # --------------------------------------------------------

    def download_and_validate_pdf(
        url: str,
        destination: Path,
        *,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
    ) -> int:
        """
        Stream a document to disk and verify its PDF signature.
        Deletes incomplete/invalid files before raising.
        """
        total = 0

        try:
            with requests.get(
                url,
                headers=headers or {},
                timeout=90,
                stream=True,
                allow_redirects=allow_redirects,
            ) as download_response:
                download_response.raise_for_status()

                with destination.open("wb") as output_file:
                    for chunk in download_response.iter_content(
                        chunk_size=256 * 1024
                    ):
                        if chunk:
                            output_file.write(chunk)
                            total += len(chunk)

            if total == 0:
                raise ValueError("The document response was empty.")

            with destination.open("rb") as downloaded_file:
                signature = downloaded_file.read(5)

            if signature != b"%PDF-":
                raise ValueError(
                    "The downloaded document is not a valid PDF "
                    "(missing %PDF- signature)."
                )

            return total

        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def download_via_document_endpoint(
        destination: Path,
    ) -> int:
        """
        Use FinancialFilings' authenticated document endpoint.

        A 200 response contains the document and is billed according to
        the endpoint's price. A 302 response is a free redirect to the
        stored document; the redirected CDN download itself is not an
        additional FinancialFilings API call.
        """
        document_api_url = (
            f"https://api.financialreports.eu/filings/"
            f"{filing_id}/document/"
        )

        print(
            f"CDN download failed for {symbol}; "
            "trying FinancialFilings document endpoint (fallback credit)..."
        )

        with requests.get(
            document_api_url,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/pdf,application/octet-stream,*/*",
            },
            timeout=90,
            stream=True,
            allow_redirects=False,
        ) as document_response:

            charged = document_response.headers.get(
                "X-Credits-Charged",
                "not supplied",
            )
            print(
                "FinancialFilings document endpoint credits charged:",
                charged,
            )

            if document_response.status_code in (301, 302, 303, 307, 308):
                redirect_url = document_response.headers.get("Location")
                if not redirect_url:
                    raise ValueError(
                        "FinancialFilings document endpoint returned a "
                        "redirect without a Location header."
                    )

            else:
                document_response.raise_for_status()

                # A successful 200 response contains the PDF itself.
                total = 0
                try:
                    with destination.open("wb") as output_file:
                        for chunk in document_response.iter_content(
                            chunk_size=256 * 1024
                        ):
                            if chunk:
                                output_file.write(chunk)
                                total += len(chunk)

                    if total == 0:
                        raise ValueError(
                            "FinancialFilings document endpoint returned "
                            "an empty document."
                        )

                    with destination.open("rb") as downloaded_file:
                        signature = downloaded_file.read(5)

                    if signature != b"%PDF-":
                        raise ValueError(
                            "FinancialFilings document endpoint did not "
                            "return a valid PDF."
                        )

                    return total

                except Exception:
                    destination.unlink(missing_ok=True)
                    raise

        # Follow the redirect outside the API response context.
        return download_and_validate_pdf(
            redirect_url,
            destination,
            headers={
                "Accept": "application/pdf,application/octet-stream,*/*",
            },
        )

    # --------------------------------------------------------
    # First attempt: direct CDN download (no API credit)
    # --------------------------------------------------------

    print(
        f"Downloading FY {financial_year} annual report "
        f"for {symbol} directly from FinancialFilings CDN..."
    )

    try:
        total_bytes = download_and_validate_pdf(
            str(cdn_url),
            local_path,
            headers={
                "Accept": "application/pdf,application/octet-stream,*/*",
            },
        )

        download_method = "cdn"

    except (requests.RequestException, ValueError) as cdn_error:
        print(
            f"FinancialFilings CDN retrieval failed for {symbol}: "
            f"{cdn_error}"
        )
        print(
            "Activating the one-credit document-endpoint fallback..."
        )

        # Second API credit is used only after CDN failure/invalid PDF.
        total_bytes = download_via_document_endpoint(
            local_path
        )
        download_method = "document_endpoint"

    print(
        "Annual report downloaded successfully:"
    )
    print(
        f"  Filing ID: {filing_id}"
    )
    print(
        f"  Financial year: {financial_year}"
    )
    print(
        f"  File: {local_path}"
    )
    print(
        f"  Size: {total_bytes:,} bytes"
    )
    print(
        f"  Download method: {download_method}"
    )

    return {
        "company_name": company_name,
        "symbol": symbol,
        "sector": company.get("sector", ""),
        "target_for_worksphere": company.get(
            "target_for_worksphere",
            "",
        ),
        "classification_status": company.get(
            "classification_status",
            "",
        ),
        "report": selected_report,
        "financial_year": financial_year,
        # Kept for compatibility with result consumers that expect this key.
        # FinancialFilings provenance is stored separately below.
        "nse_url": None,
        "file_name": file_name,
        "file_path": local_path,
        "downloaded": True,
        "local_cache_hit": False,
        "source_provider": "financialfilings",
        "source_filing_id": str(filing_id),
        "source_document_url": cdn_url,
        "source_company_isin": isin,
        "download_method": download_method,
    }



# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_report_text(
    file_path: str | Path,
) -> dict[str, Any]:
    """
    Extract text from an annual report PDF.

    Returns:

        {
            "raw_text": str,
            "page_count": int
        }
    """

    file_path = Path(
        file_path
    )

    if not file_path.exists():
        raise FileNotFoundError(
            f"Annual report not found: {file_path}"
        )

    reader = PdfReader(
        str(file_path)
    )

    page_texts: list[str] = []

    for page_number, page in enumerate(
        reader.pages,
        start=1,
    ):
        try:
            text = page.extract_text()

        except Exception as error:
            print(
                f"Warning: failed to extract "
                f"page {page_number}: {error}"
            )

            text = ""

        if text:
            page_texts.append(
                text
            )

    raw_text = "\n\n".join(
        page_texts
    )

    return {
        "raw_text": raw_text,
        "page_count": len(
            reader.pages
        ),
    }


# ============================================================
# FINANCIALFILINGS INGESTION ORCHESTRATION
# ============================================================

def ingest_annual_report_financialfilings(
    company: dict[str, Any],
    drive_service=None,
    download_folder: Path | None = None,
) -> dict[str, Any] | None:
    """
    Run the annual-report ingestion pipeline using FinancialFilings:

        Supabase company (including ISIN)
              ↓
        FinancialFilings metadata discovery
              ↓
        Direct CDN PDF download
              ↓ (only if CDN fails)
        Authenticated document-endpoint fallback
              ↓
        PDF text extraction
              ↓
        optional Google Drive upload
              ↓
        annual_reports metadata in Supabase

    This function deliberately does not call NSE. The existing NSE
    discovery and ingestion functions remain available separately.
    """

    result = fetch_annual_report_financialfilings(
        company=company,
        download_folder=download_folder,
    )

    if result is None:
        return None

    file_path = Path(result["file_path"])

    # Extract PDF text using the existing shared extraction function.
    document = extract_report_text(file_path)
    result["raw_text"] = document["raw_text"]
    result["page_count"] = document["page_count"]

    # Upload to Google Drive only when a service is explicitly supplied.
    drive_file = None
    if drive_service is not None:
        drive_file = upload_report_to_drive(
            drive_service,
            file_path,
        )

    result["google_drive_file_id"] = (
        drive_file.get("id") if drive_file else None
    )
    result["google_drive_file"] = drive_file

    # Persist using the existing annual_reports schema. nse_url is NULL
    # because the source is FinancialFilings, not NSE.
    report_row = upsert_annual_report(
        company_id=company["id"],
        financial_year=str(result["financial_year"]),
        report_title=result["file_name"],
        nse_url=None,
        local_file_path=str(file_path),
        google_drive_file_id=result["google_drive_file_id"],
        page_count=result["page_count"],
        processing_status="pending",
        source_provider="financialfilings",
        source_filing_id=result["source_filing_id"],
        source_document_url=result["source_document_url"],
        source_company_isin=result["source_company_isin"],
    )

    result["annual_report_id"] = report_row["id"]
    result["processing_status"] = report_row.get("processing_status")

    return result


# ============================================================
# COMPLETE LOCAL INGESTION HELPER
# ============================================================

def ingest_annual_report(
    nse: NSE,
    company: dict[str, Any],
    drive_service=None,
    download_folder: Path | None = None,
) -> dict[str, Any] | None:
    """
    Perform the ingestion portion of the pipeline:

        Supabase company
              ↓
        NSE annual report
              ↓
        local PDF
              ↓
        PDF text extraction
              ↓
        optional Google Drive upload
              ↓
        annual_reports metadata in Supabase

    This function does NOT:
        - call Gemini
        - create evidence
        - validate evidence
        - write evidence to Supabase

    Those responsibilities belong to later stages.

    The annual_reports metadata written here includes:

        report_title
            Exact PDF filename.

        nse_url
            Full NSE annual report URL.
    """

    result = fetch_latest_annual_report(
        nse=nse,
        company=company,
        download_folder=download_folder,
    )

    if result is None:
        return None

    file_path = Path(
        result["file_path"]
    )

    # --------------------------------------------------------
    # Extract PDF text
    # --------------------------------------------------------

    document = extract_report_text(
        file_path
    )

    result["raw_text"] = document[
        "raw_text"
    ]

    result["page_count"] = document[
        "page_count"
    ]

    # --------------------------------------------------------
    # Upload to Google Drive if service supplied
    # --------------------------------------------------------

    drive_file = None

    if drive_service is not None:
        drive_file = upload_report_to_drive(
            drive_service,
            file_path,
        )

        result[
            "google_drive_file_id"
        ] = drive_file.get(
            "id"
        )

        result[
            "google_drive_file"
        ] = drive_file

    else:
        result[
            "google_drive_file_id"
        ] = None

        result[
            "google_drive_file"
        ] = None

    # --------------------------------------------------------
    # Persist annual report metadata in Supabase
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # report_title = extracted PDF filename
    #
    # nse_url = complete NSE URL
    #
    # We DO NOT use:
    #     result["report"]["fileName"]
    # directly as report_title,
    # because fileName contains the complete URL.
    # --------------------------------------------------------

    report_row = upsert_annual_report(
        company_id=company["id"],

        financial_year=str(
            result["financial_year"]
        ),

        report_title=result[
            "file_name"
        ],

        nse_url=result[
            "nse_url"
        ],

        local_file_path=str(
            file_path
        ),

        google_drive_file_id=result.get(
            "google_drive_file_id"
        ),

        page_count=result[
            "page_count"
        ],

        # Ingestion creates/refreshes the report record. Processing starts
        # only when the processing endpoint atomically claims this row.
        processing_status="pending",
    )

    result[
        "annual_report_id"
    ] = report_row["id"]
    result["processing_status"] = report_row.get("processing_status")

    return result


# ============================================================
# SIMPLE COMPANY REPORT LOADER
# ============================================================

def load_report_from_company(
    symbol: str,
    company: dict[str, Any],
    drive_service=None,
) -> dict[str, Any]:
    """
    Load the current financial year's annual report for a Supabase company.

    Production orchestration uses FinancialFilings and the company's ISIN.
    The original NSE functions remain in this module for explicit fallback
    or legacy use, but are no longer invoked by this default loader.
    """

    if not symbol:
        raise ValueError("Company symbol is required.")

    if (
        str(company.get("symbol", "")).upper()
        != symbol.upper()
    ):
        raise ValueError(
            "Company record does not match "
            f"requested symbol: {symbol}"
        )

    DOWNLOAD_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = ingest_annual_report_financialfilings(
        company=company,
        drive_service=drive_service,
        download_folder=DOWNLOAD_FOLDER,
    )

    if not result:
        raise RuntimeError(
            f"No FinancialFilings annual report found for {symbol} "
            f"for FY {date.today().year}."
        )

    return result
