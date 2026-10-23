import csv
import os
import sys

from dotenv import load_dotenv
from supabase import create_client


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL is not set in .env")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not set in .env")


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)


# --------------------------------------------------
# CSV path
# --------------------------------------------------

CSV_PATH = "../backend/data/processed/NSE_companies_categorized_v2.csv"

CSV_PATH = os.path.abspath(CSV_PATH)


# --------------------------------------------------
# CSV → Supabase mapping
# --------------------------------------------------

def convert_row(row):
    target_value = str(
        row.get("TARGET_FOR_WORKSPHERE", "")
    ).strip().lower()

    return {
        "symbol": str(row.get("SYMBOL", "")).strip(),
        "name": str(row.get("NAME OF COMPANY", "")).strip(),
        "sector": str(row.get("SECTOR", "")).strip() or None,
        "target_for_worksphere": target_value == "yes",
        "classification_status": (
            str(row.get("CLASSIFICATION_STATUS", "")).strip()
            or None
        )
    }


# --------------------------------------------------
# Read CSV
# --------------------------------------------------

def load_companies():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(
            f"CSV file not found:\n{CSV_PATH}"
        )

    companies = []

    with open(
        CSV_PATH,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as csv_file:

        reader = csv.DictReader(csv_file)

        required_columns = {
            "SYMBOL",
            "NAME OF COMPANY",
            "SECTOR",
            "TARGET_FOR_WORKSPHERE",
            "CLASSIFICATION_STATUS"
        }

        missing_columns = required_columns - set(reader.fieldnames or [])

        if missing_columns:
            raise ValueError(
                "Missing CSV columns: "
                + ", ".join(sorted(missing_columns))
            )

        for row in reader:
            company = convert_row(row)

            if not company["symbol"]:
                continue

            if not company["name"]:
                continue

            companies.append(company)

    return companies


# --------------------------------------------------
# Upload to Supabase
# --------------------------------------------------

def seed_companies(companies):
    print(f"Preparing to insert {len(companies)} companies...")

    # Supabase/PostgREST works well with batches.
    # This avoids sending an unnecessarily huge request.
    batch_size = 500

    total_inserted = 0

    for start in range(0, len(companies), batch_size):
        batch = companies[start:start + batch_size]

        response = (
            supabase
            .table("companies")
            .upsert(
                batch,
                on_conflict="symbol"
            )
            .execute()
        )

        inserted_count = len(response.data or [])

        total_inserted += inserted_count

        print(
            f"Processed {min(start + batch_size, len(companies))}"
            f"/{len(companies)} companies"
        )

    print()
    print("======================================")
    print("Company seeding completed")
    print("======================================")
    print(f"Companies processed: {len(companies)}")
    print(f"Companies returned:  {total_inserted}")


# --------------------------------------------------
# Main
# --------------------------------------------------

if __name__ == "__main__":
    try:
        companies = load_companies()

        if not companies:
            print("No companies found in CSV.")
            sys.exit(1)

        seed_companies(companies)

    except Exception as error:
        print()
        print("ERROR:")
        print(error)
        sys.exit(1)