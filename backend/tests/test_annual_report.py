from pathlib import Path

from applications.services.annual_reports import fetch_latest_annual_report


DOWNLOAD_FOLDER = Path("storage/reports")

DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


result = fetch_latest_annual_report(
    "AETHER",
    DOWNLOAD_FOLDER
)

print("\nRESULT:")
print(result)