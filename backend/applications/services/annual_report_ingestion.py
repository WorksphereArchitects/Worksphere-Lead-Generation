from __future__ import annotations

from pathlib import Path
from typing import Any

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
    Load the latest annual report for a supplied company.

    IMPORTANT:

    The company record now comes from Supabase.

    This function deliberately does NOT read the old
    NSE companies CSV.
    """

    if not symbol:
        raise ValueError(
            "Company symbol is required."
        )

    if (
        str(
            company.get(
                "symbol",
                "",
            )
        ).upper()
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

    with NSE(
        download_folder=DOWNLOAD_FOLDER
    ) as nse:

        result = ingest_annual_report(
            nse=nse,
            company=company,
            drive_service=drive_service,
            download_folder=DOWNLOAD_FOLDER,
        )

    if not result:
        raise RuntimeError(
            f"No annual report found for {symbol}."
        )

    return result
