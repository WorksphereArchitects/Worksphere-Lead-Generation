from pathlib import Path
from nse import NSE

DOWNLOAD_FOLDER = Path("storage/reports")

DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

try:
    with NSE(download_folder=DOWNLOAD_FOLDER) as nse:
        reports = nse.annual_reports("MEESHO")

        print("NSE connection successful!")
        print(reports)

except Exception as error:
    print(f"NSE request failed: {type(error).__name__}: {error}")