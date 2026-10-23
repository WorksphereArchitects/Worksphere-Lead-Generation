import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client


# ============================================================
# CONFIG
# ============================================================

# Load backend/.env
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

CSV_PATH = Path("../backend/tests/worksphere_financial_tests/financial_test_results/yfinance_qualification_results.csv")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_KEY must be set."
    )


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ============================================================
# HELPERS
# ============================================================

def to_float(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def to_jsonb(value):
    """
    CSV fields such as financial_columns and financial_rows
    may already contain JSON strings.

    If valid JSON -> store as JSONB.
    Otherwise -> store the original value as a JSON string.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def clean_text(value):
    if value is None:
        return None

    value = str(value).strip()

    return value if value else None


# ============================================================
# IMPORT
# ============================================================

def import_results():

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"CSV not found: {CSV_PATH.resolve()}"
        )

    with CSV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        rows = list(reader)

    print(f"Found {len(rows)} CSV rows.")

    inserted = 0
    skipped = 0
    errors = 0

    for index, row in enumerate(rows, start=1):

        try:

            company_id = clean_text(
                row.get("company_id")
            )

            if not company_id:
                print(
                    f"[SKIP {index}] Missing company_id"
                )
                skipped += 1
                continue

            current_year = clean_text(
                row.get("current_year")
            )

            previous_year = clean_text(
                row.get("previous_year")
            )

            revenue = to_float(
                row.get("revenue_crore")
            )

            previous_revenue = to_float(
                row.get("previous_revenue_crore")
            )

            revenue_growth = to_float(
                row.get("revenue_growth")
            )

            qualification_status = clean_text(
                row.get("qualification_status")
            )

            # ------------------------------------------------
            # Build Supabase row
            # ------------------------------------------------

            financial_row = {
                "company_id": company_id,

                "financial_year": current_year,
                "previous_financial_year": previous_year,

                "revenue": revenue,
                "previous_year_revenue": previous_revenue,
                "revenue_growth": revenue_growth,

                "revenue_unit": "INR_CRORE",
                "growth_source": "calculated",

                "qualification_status": qualification_status,
                "qualification_source": "yfinance",

                # No annual report involved in this import
                "annual_report_id": None,

                "source_candidate_ids": None,
                "source_sentence_indexes": None,
                "source_resolution_status": None,

                # YFinance metadata
                "yahoo_ticker": clean_text(
                    row.get("yahoo_ticker")
                ),

                "revenue_row": clean_text(
                    row.get("revenue_row")
                ),

                "financial_columns": to_jsonb(
                    row.get("financial_columns")
                ),

                "financial_rows": to_jsonb(
                    row.get("financial_rows")
                ),

                "error": clean_text(
                    row.get("error")
                ),
            }

            # ------------------------------------------------
            # Insert
            # ------------------------------------------------

            response = (
                supabase
                .table("company_financials")
                .insert(financial_row)
                .execute()
            )

            if response.data:

                inserted += 1

                print(
                    f"[OK {index}] "
                    f"{row.get('symbol')} - "
                    f"{row.get('name')} - "
                    f"{qualification_status}"
                )

            else:

                skipped += 1

                print(
                    f"[SKIP {index}] "
                    f"No row returned for "
                    f"{row.get('symbol')}"
                )

        except Exception as error:

            errors += 1

            print(
                f"[ERROR {index}] "
                f"{row.get('symbol')} - "
                f"{error}"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)

    print(f"Total CSV rows : {len(rows)}")
    print(f"Inserted       : {inserted}")
    print(f"Skipped        : {skipped}")
    print(f"Errors         : {errors}")


if __name__ == "__main__":
    import_results()