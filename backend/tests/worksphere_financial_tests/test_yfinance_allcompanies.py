from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

# ============================================================
# MAKE BACKEND IMPORTS WORK
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

# ============================================================
# IMPORTS
# ============================================================

import yfinance as yf

from applications.services.supabase_client import supabase


# ============================================================
# CONFIG
# ============================================================

OUTPUT_DIR = Path(__file__).resolve().parent / "financial_test_results"
OUTPUT_DIR.mkdir(exist_ok=True)

RESULTS_FILE = OUTPUT_DIR / "yfinance_qualification_results.csv"
FAILURES_FILE = OUTPUT_DIR / "yfinance_failures.csv"

REVENUE_THRESHOLD_CRORE = 3000
GROWTH_THRESHOLD_PERCENT = 10

YAHOO_SUFFIX = ".NS"

# Number of times to retry a Yahoo request
MAX_RETRIES = 3

# Small delay between companies
REQUEST_DELAY_SECONDS = 0.5

# Supabase pagination
SUPABASE_PAGE_SIZE = 1000


# ============================================================
# SUPABASE — FETCH ALL TARGET COMPANIES
# ============================================================

def get_target_companies() -> list[dict]:
    """
    Fetch ALL target companies from Supabase.

    Supabase/PostgREST normally limits a response to 1000 rows,
    so we explicitly paginate using range().
    """

    all_companies = []
    offset = 0

    while True:

        print(
            f"Fetching companies "
            f"{offset + 1} to {offset + SUPABASE_PAGE_SIZE}..."
        )

        response = (
            supabase
            .table("companies")
            .select("id, symbol, name, sector")
            .eq("target_for_worksphere", True)
            .order("name")
            .range(
                offset,
                offset + SUPABASE_PAGE_SIZE - 1
            )
            .execute()
        )

        rows = response.data or []

        if not rows:
            break

        all_companies.extend(rows)

        print(
            f"    Retrieved {len(rows)} rows "
            f"(total: {len(all_companies)})"
        )

        if len(rows) < SUPABASE_PAGE_SIZE:
            break

        offset += SUPABASE_PAGE_SIZE

    return all_companies


# ============================================================
# NUMERIC HELPERS
# ============================================================

def to_float(value):
    """
    Safely convert a value to float.
    """

    if value is None:
        return None

    try:

        if hasattr(value, "item"):
            value = value.item()

        if value != value:
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


# ============================================================
# FINANCIAL DATA HELPERS
# ============================================================

def get_financial_statement(ticker: str):
    """
    Retrieve annual income statement from Yahoo.

    We try get_income_stmt first and fall back to the
    income_stmt property.
    """

    stock = yf.Ticker(ticker)

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            # Primary method
            financials = stock.get_income_stmt(freq="yearly")

            if financials is not None and not financials.empty:
                return financials

            # Fallback
            financials = stock.income_stmt

            if financials is not None and not financials.empty:
                return financials

            print(
                f"        Attempt {attempt}: "
                f"empty financial statement"
            )

        except Exception as error:

            last_error = error

            print(
                f"        Attempt {attempt} failed: "
                f"{type(error).__name__}: {error}"
            )

        if attempt < MAX_RETRIES:
            time.sleep(2 * attempt)

    if last_error:
        raise last_error

    return None


def find_revenue_row(financials):
    """
    Find the best available revenue row.

    Yahoo can expose revenue under different row names
    depending on the company.
    """

    if financials is None or financials.empty:
        return None

    # Preferred rows — highest priority first.
    preferred_rows = [
        "Total Revenue",
        "Operating Revenue",
        "TotalRevenue",
        "OperatingRevenue",
        "Revenue",
    ]

    # Exact matches first
    for row_name in preferred_rows:

        if row_name in financials.index:
            return financials.loc[row_name]

    # Case-insensitive fallback
    normalized_rows = {
        str(index).strip().lower(): index
        for index in financials.index
    }

    for row_name in preferred_rows:

        key = row_name.strip().lower()

        if key in normalized_rows:
            actual_name = normalized_rows[key]
            return financials.loc[actual_name]

    # Last-resort search for rows containing "revenue"
    revenue_candidates = []

    for index in financials.index:

        index_string = str(index).strip().lower()

        if "revenue" in index_string:

            revenue_candidates.append(index)

    if revenue_candidates:

        # Prefer rows with "total" first
        for index in revenue_candidates:

            if "total" in str(index).lower():
                return financials.loc[index]

        # Then operating revenue
        for index in revenue_candidates:

            if "operating" in str(index).lower():
                return financials.loc[index]

        # Finally use first revenue-like row
        return financials.loc[revenue_candidates[0]]

    return None


def get_annual_values(revenue_row):
    """
    Extract valid annual revenue values from the row.
    """

    if revenue_row is None:
        return []

    values = []

    for column in revenue_row.index:

        value = to_float(revenue_row.get(column))

        if value is None:
            continue

        values.append(
            {
                "date": column,
                "value": value,
            }
        )

    # Sort newest -> oldest
    values.sort(
        key=lambda item: item["date"],
        reverse=True
    )

    return values


def extract_latest_two_years(ticker: str):

    financials = get_financial_statement(ticker)

    if financials is None or financials.empty:

        return {
            "current_revenue": None,
            "previous_revenue": None,
            "current_year": None,
            "previous_year": None,
            "revenue_row": None,
            "financial_columns": [],
            "financial_rows": [],
        }

    revenue_row = find_revenue_row(financials)

    if revenue_row is None:

        return {
            "current_revenue": None,
            "previous_revenue": None,
            "current_year": None,
            "previous_year": None,
            "revenue_row": None,
            "financial_columns": [
                str(column)
                for column in financials.columns
            ],
            "financial_rows": [
                str(index)
                for index in financials.index
            ],
        }

    values = get_annual_values(revenue_row)

    if not values:

        return {
            "current_revenue": None,
            "previous_revenue": None,
            "current_year": None,
            "previous_year": None,
            "revenue_row": str(revenue_row.name),
            "financial_columns": [
                str(column)
                for column in financials.columns
            ],
            "financial_rows": [
                str(index)
                for index in financials.index
            ],
        }

    current = values[0]

    previous = values[1] if len(values) >= 2 else None

    return {
        "current_revenue": current["value"],
        "previous_revenue": (
            previous["value"]
            if previous
            else None
        ),
        "current_year": str(current["date"]),
        "previous_year": (
            str(previous["date"])
            if previous
            else None
        ),
        "revenue_row": str(revenue_row.name),
        "financial_columns": [
            str(column)
            for column in financials.columns
        ],
        "financial_rows": [
            str(index)
            for index in financials.index
        ],
    }


# ============================================================
# GROWTH / QUALIFICATION
# ============================================================

def calculate_growth(
    current_revenue,
    previous_revenue
):
    """
    Calculate YoY revenue growth.
    """

    if current_revenue is None:
        return None

    if previous_revenue is None:
        return None

    if previous_revenue == 0:
        return None

    return (
        (current_revenue - previous_revenue)
        / previous_revenue
    ) * 100


def rupees_to_crore(value):

    if value is None:
        return None

    # Yahoo reports Indian company financials in INR.
    # 1 crore = 10,000,000 INR.
    return value / 10_000_000


def qualify(
    revenue_crore,
    growth_percent
):
    """
    WorkSphere financial qualification rule:

    Revenue > ₹3,000 Cr
    AND
    Revenue growth > 10%
    """

    if revenue_crore is None:
        return "insufficient_data"

    if growth_percent is None:
        return "insufficient_data"

    if (
        revenue_crore > REVENUE_THRESHOLD_CRORE
        and growth_percent > GROWTH_THRESHOLD_PERCENT
    ):
        return "qualified"

    return "not_qualified"


# ============================================================
# PROCESS ONE COMPANY
# ============================================================

def process_company(company: dict) -> dict:

    symbol = (
        company.get("symbol") or ""
    ).strip().upper()

    yahoo_ticker = f"{symbol}{YAHOO_SUFFIX}"

    result = {
        "company_id": company.get("id"),
        "symbol": symbol,
        "name": company.get("name"),
        "sector": company.get("sector"),
        "yahoo_ticker": yahoo_ticker,

        "current_year": None,
        "previous_year": None,

        "revenue_rupees": None,
        "previous_revenue_rupees": None,

        "revenue_crore": None,
        "previous_revenue_crore": None,

        "revenue_growth": None,

        "revenue_row": None,

        "qualification_status": None,

        "error": None,

        "financial_columns": None,
        "financial_rows": None,
    }

    try:

        financial_data = extract_latest_two_years(
            yahoo_ticker
        )

        current_revenue = (
            financial_data["current_revenue"]
        )

        previous_revenue = (
            financial_data["previous_revenue"]
        )

        growth = calculate_growth(
            current_revenue,
            previous_revenue
        )

        current_crore = rupees_to_crore(
            current_revenue
        )

        previous_crore = rupees_to_crore(
            previous_revenue
        )

        status = qualify(
            current_crore,
            growth
        )

        result.update(
            {
                "current_year": financial_data[
                    "current_year"
                ],

                "previous_year": financial_data[
                    "previous_year"
                ],

                "revenue_rupees": current_revenue,

                "previous_revenue_rupees":
                    previous_revenue,

                "revenue_crore": current_crore,

                "previous_revenue_crore":
                    previous_crore,

                "revenue_growth": growth,

                "revenue_row": financial_data[
                    "revenue_row"
                ],

                "qualification_status": status,

                "financial_columns": "|".join(
                    financial_data[
                        "financial_columns"
                    ]
                ),

                "financial_rows": "|".join(
                    financial_data[
                        "financial_rows"
                    ]
                ),
            }
        )

    except Exception as error:

        result["qualification_status"] = "error"

        result["error"] = (
            f"{type(error).__name__}: {error}"
        )

    return result


# ============================================================
# CSV
# ============================================================

RESULT_FIELDS = [

    "company_id",
    "symbol",
    "name",
    "sector",
    "yahoo_ticker",

    "current_year",
    "previous_year",

    "revenue_rupees",
    "previous_revenue_rupees",

    "revenue_crore",
    "previous_revenue_crore",

    "revenue_growth",

    "revenue_row",

    "qualification_status",

    "error",

    "financial_columns",
    "financial_rows",
]


def write_csv(
    path: Path,
    rows: list[dict]
):

    with path.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=RESULT_FIELDS
        )

        writer.writeheader()

        writer.writerows(rows)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "WORKSPHERE — YFINANCE FINANCIAL "
        "QUALIFICATION TEST"
    )
    print("=" * 70)
    print()

    # --------------------------------------------------------
    # SUPABASE
    # --------------------------------------------------------

    print(
        "Fetching ALL target companies from Supabase..."
    )

    companies = get_target_companies()

    print()

    print(
        f"Target companies found: "
        f"{len(companies)}"
    )

    if not companies:

        print(
            "No target companies found."
        )

        return

    print()

    # --------------------------------------------------------
    # PROCESS
    # --------------------------------------------------------

    print(
        "Starting yfinance processing..."
    )

    print()

    results = []

    start_time = time.time()

    for index, company in enumerate(
        companies,
        start=1
    ):

        symbol = company.get(
            "symbol",
            ""
        )

        name = company.get(
            "name",
            ""
        )

        print(
            f"[{index}/{len(companies)}] "
            f"{symbol} — {name}"
        )

        result = process_company(
            company
        )

        results.append(result)

        status = result[
            "qualification_status"
        ]

        revenue = result[
            "revenue_crore"
        ]

        growth = result[
            "revenue_growth"
        ]

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------

        if status == "qualified":

            print(
                f"    ✓ QUALIFIED | "
                f"Revenue: ₹{revenue:,.2f} Cr | "
                f"Growth: {growth:.2f}%"
            )

        elif status == "not_qualified":

            revenue_text = (
                f"₹{revenue:,.2f} Cr"
                if revenue is not None
                else "N/A"
            )

            growth_text = (
                f"{growth:.2f}%"
                if growth is not None
                else "N/A"
            )

            print(
                f"    ✗ NOT QUALIFIED | "
                f"Revenue: {revenue_text} | "
                f"Growth: {growth_text}"
            )

        elif status == "insufficient_data":

            print(
                "    ! INSUFFICIENT DATA"
            )

            if result["revenue_row"]:

                print(
                    f"        Revenue row: "
                    f"{result['revenue_row']}"
                )

            elif result["financial_rows"]:

                print(
                    "        Revenue row not found."
                )

                print(
                    f"        Available rows: "
                    f"{result['financial_rows'][:300]}"
                )

            else:

                print(
                    "        No annual financial "
                    "statement returned."
                )

        else:

            print(
                f"    ! ERROR: "
                f"{result.get('error')}"
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    # --------------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------------

    elapsed = (
        time.time() - start_time
    )

    write_csv(
        RESULTS_FILE,
        results
    )

    failures = [
        row
        for row in results
        if row["qualification_status"]
        in (
            "error",
            "insufficient_data",
        )
    ]

    write_csv(
        FAILURES_FILE,
        failures
    )

    # --------------------------------------------------------
    # COUNTS
    # --------------------------------------------------------

    total = len(results)

    qualified = sum(
        row["qualification_status"]
        == "qualified"
        for row in results
    )

    not_qualified = sum(
        row["qualification_status"]
        == "not_qualified"
        for row in results
    )

    insufficient = sum(
        row["qualification_status"]
        == "insufficient_data"
        for row in results
    )

    errors = sum(
        row["qualification_status"]
        == "error"
        for row in results
    )

    usable = (
        qualified
        + not_qualified
    )

    coverage = (
        usable / total * 100
        if total
        else 0
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()

    print("=" * 70)
    print(
        "TEST COMPLETE"
    )
    print("=" * 70)

    print(
        f"Total companies:        {total}"
    )

    print(
        f"Usable financial data:  {usable}"
    )

    print(
        f"Qualified:              {qualified}"
    )

    print(
        f"Not qualified:          {not_qualified}"
    )

    print(
        f"Insufficient data:      {insufficient}"
    )

    print(
        f"Errors:                 {errors}"
    )

    print(
        f"Coverage:               "
        f"{coverage:.2f}%"
    )

    print(
        f"Elapsed time:           "
        f"{elapsed / 60:.2f} minutes"
    )

    print()

    print(
        f"Full results:\n"
        f"{RESULTS_FILE.resolve()}"
    )

    print()

    print(
        f"Failures:\n"
        f"{FAILURES_FILE.resolve()}"
    )

    print()

    print("=" * 70)


if __name__ == "__main__":
    main()