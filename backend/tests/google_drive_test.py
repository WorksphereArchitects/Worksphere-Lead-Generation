from pathlib import Path
import io

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

REPORTS_DIR = BASE_DIR / "storage" / "reports"

# Google Drive folder:
# Worksphere_Test / Annual_Reports
ANNUAL_REPORTS_FOLDER_ID = "1BShHAs--k0cIiJyaKIU6WJBlEcOzS6mF"


def authenticate():
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES
        )

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES
        )

        credentials = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(credentials.to_json())

    return build("drive", "v3", credentials=credentials)


def list_files():
    service = authenticate()

    results = service.files().list(
        pageSize=100,
        fields="files(id, name, mimeType, parents)"
    ).execute()

    files = results.get("files", [])

    print(f"\nFiles found: {len(files)}\n")

    for file in files:
        print(f"Name: {file['name']}")
        print(f"ID: {file['id']}")
        print(f"Type: {file['mimeType']}")
        print(f"Parents: {file.get('parents')}")
        print("-" * 60)


def list_pdfs_in_folder(service, folder_id):
    results = service.files().list(
        q=(
            f"'{folder_id}' in parents "
            "and mimeType = 'application/pdf' "
            "and trashed = false"
        ),
        fields="files(id, name, mimeType, size, parents)"
    ).execute()

    files = results.get("files", [])

    print(f"\nPDFs found in Annual_Reports: {len(files)}\n")

    for file in files:
        print(f"Name: {file['name']}")
        print(f"ID: {file['id']}")
        print(f"Size: {file.get('size', 'Unknown')} bytes")
        print("-" * 60)

    return files


def download_file(service, file_id, file_name):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = REPORTS_DIR / file_name

    request = service.files().get_media(fileId=file_id)

    with io.FileIO(output_path, "wb") as file_handle:
        downloader = MediaIoBaseDownload(
            file_handle,
            request
        )

        done = False

        while not done:
            status, done = downloader.next_chunk()

            if status:
                print(
                    f"Download progress: "
                    f"{int(status.progress() * 100)}%"
                )

    print("\nDownloaded successfully:")
    print(output_path)

    return output_path


def upload_file(service, file_path, folder_id):
    file_path = Path(file_path)

    if not file_path.exists():
        print(f"\nPDF not found:")
        print(file_path)
        return None

    file_metadata = {
        "name": file_path.name,
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        str(file_path),
        mimetype="application/pdf",
        resumable=True,
    )

    uploaded_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, mimeType, parents, size",
    ).execute()

    print("\nUploaded successfully:")
    print(f"Name: {uploaded_file['name']}")
    print(f"ID: {uploaded_file['id']}")
    print(f"Size: {uploaded_file.get('size')} bytes")
    print(f"Parents: {uploaded_file.get('parents')}")

    return uploaded_file


def main():
    service = authenticate()

    folder_id = ANNUAL_REPORTS_FOLDER_ID

    print("\nGoogle Drive Test")
    print("-----------------")
    print("Target folder: Worksphere_Test / Annual_Reports")
    print(f"Folder ID: {folder_id}")

    print("\n1. Download PDF from Google Drive")
    print("2. Upload PDF to Google Drive")

    choice = input("\nChoose an option (1/2): ").strip()

    if choice == "1":

        # DOWNLOAD FROM GOOGLE DRIVE

        pdfs = list_pdfs_in_folder(
            service,
            folder_id
        )

        if not pdfs:
            print("\nNo PDFs found.")
            return

        pdf = pdfs[0]

        download_file(
            service,
            pdf["id"],
            pdf["name"]
        )

    elif choice == "2":

        # UPLOAD TO GOOGLE DRIVE

        local_pdf = (
            BASE_DIR
            / "storage"
            / "reports"
            / "AR_30433_AETHER_2025_2026_A_12885546_19082026181335.pdf"
        )

        upload_file(
            service,
            local_pdf,
            folder_id
        )

    else:
        print("\nInvalid option. Please choose 1 or 2.")


if __name__ == "__main__":
    main()