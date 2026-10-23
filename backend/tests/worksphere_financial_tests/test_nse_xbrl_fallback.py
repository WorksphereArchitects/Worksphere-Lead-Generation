from __future__ import annotations

import csv
import json
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urljoin

import requests


# ============================================================
# PATH SETUP
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ============================================================
# OUTPUT
# ============================================================

OUT = Path("financial_test_output")
OUT.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = OUT / "nse_xbrl_fallback_test.csv"

# Save raw XBRL responses as well so we can inspect the
# actual NSE structure after the test.
RAW_OUT = OUT / "nse_xbrl_raw"
RAW_OUT.mkdir(parents=True, exist_ok=True)


# ============================================================
# THE 33 YFINANCE INSUFFICIENT-DATA COMPANIES
# ============================================================

SYMBOLS = [
    "AONESTEELS",
    "ADDIND",
    "ALFREDHE",
    "AGL",
    "ARMEE",
    "BLUECOAST",
    "BOHRAIND",
    "DISAQ",
    "ELCIDIN",
    "ELEVATE",
    "GLFL",
    "GUJRAFFIA",
    "INFOMEDIA",
    "KWIL",
    "MONEYVIEW",
    "NDLVENTURE",
    "NECLIFE",
    "NEXTMEDIA",
    "PARASPETRO",
    "QUINTEGRA",
    "SHYAMTEL",
    "SINGERIND",
    "TAKE",
    "TNTELE",
    "TARAPUR",
    "TCIFINANCE",
    "TECILCHEM",
    "STCINDIA",
    "VARMORA",
    "VAML",
    "VIVIDHA",
    "WEWORK",
    "ZODIAC",
]


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/155.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
)


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)

        if value != value:
            return None

        return value

    except (TypeError, ValueError):
        return None


def normalize_text(value):
    if value is None:
        return ""

    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).lower(),
    )


def rupees_to_crore(value):
    if value is None:
        return None

    return value / 10_000_000


def calculate_growth(current, previous):
    if current is None or previous is None:
        return None

    if previous == 0:
        return None

    return (
        (current - previous)
        / previous
    ) * 100


def is_consolidated(row):
    """
    NSE annual-results metadata has a 'consolidated' field.

    Prefer consolidated filings for this test.
    """

    value = str(
        row.get("consolidated", "")
    ).strip().lower()

    return value in {
        "true",
        "yes",
        "y",
        "1",
        "consolidated",
    }


def extract_xbrl_url(row):
    """
    NSE/nsepython may expose the XBRL URL under different
    metadata fields depending on package/version.
    """

    possible_fields = [
        "xbrl",
        "resultDetailedDataLink",
    ]

    for field in possible_fields:
        value = row.get(field)

        if value and isinstance(value, str):
            value = value.strip()

            if value.startswith("http://"):
                return value

            if value.startswith("https://"):
                return value

            if value.startswith("/"):
                return urljoin(
                    "https://www.nseindia.com",
                    value,
                )

    return None


def choose_annual_filing(rows):
    """
    Select the best annual filing.

    Priority:
        1. consolidated
        2. audited
        3. latest financial year
    """

    if not rows:
        return None

    rows = [
        row
        for row in rows
        if isinstance(row, dict)
    ]

    if not rows:
        return None

    consolidated_rows = [
        row
        for row in rows
        if is_consolidated(row)
    ]

    if consolidated_rows:
        rows = consolidated_rows

    audited_rows = [
        row
        for row in rows
        if str(
            row.get("audited", "")
        ).strip().lower()
        in {
            "true",
            "yes",
            "y",
            "1",
            "audited",
        }
    ]

    if audited_rows:
        rows = audited_rows

    # Prefer the latest financial year.
    rows.sort(
        key=lambda row: str(
            row.get(
                "financialYear",
                ""
            )
        ),
        reverse=True,
    )

    return rows[0]


# ============================================================
# XBRL FETCH
# ============================================================

def fetch_xbrl(url):
    response = SESSION.get(
        url,
        timeout=30,
    )

    response.raise_for_status()

    return response


# ============================================================
# XBRL STRUCTURE INSPECTION
# ============================================================

def inspect_json_structure(data, prefix="root", depth=0):
    """
    Print a compact representation of the JSON structure.

    This is intentionally generic because we first want to see
    what NSE actually returns before writing the final revenue
    extractor.
    """

    if depth > 4:
        return

    if isinstance(data, dict):

        print(
            "  " * depth
            + f"{prefix}: dict "
            + f"({len(data)} keys)"
        )

        for key, value in list(
            data.items()
        )[:30]:

            print(
                "  " * (depth + 1)
                + f"- {key}: "
                + type(value).__name__
            )

            if isinstance(
                value,
                (dict, list)
            ):
                inspect_json_structure(
                    value,
                    prefix=f"{prefix}.{key}",
                    depth=depth + 2,
                )

    elif isinstance(data, list):

        print(
            "  " * depth
            + f"{prefix}: list "
            + f"({len(data)} items)"
        )

        if data:

            first = data[0]

            if isinstance(
                first,
                (dict, list)
            ):
                inspect_json_structure(
                    first,
                    prefix=f"{prefix}[0]",
                    depth=depth + 1,
                )


# ============================================================
# GENERIC REVENUE SEARCH
# ============================================================

REVENUE_TERMS = [
    "total revenue",
    "revenue from operations",
    "revenue from operation",
    "operating revenue",
    "revenue",
    "turnover",
]


def find_revenue_candidates(
    obj,
    path="root",
):
    """
    Recursively search the returned XBRL JSON for keys/labels
    that look like revenue.

    This is NOT yet the production extractor.

    It is deliberately exploratory so we can learn the actual
    NSE XBRL structure.
    """

    matches = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_text = str(key).lower()

            if any(
                term in key_text
                for term in REVENUE_TERMS
            ):
                matches.append(
                    {
                        "path": f"{path}.{key}",
                        "key": str(key),
                        "value": value,
                    }
                )

            matches.extend(
                find_revenue_candidates(
                    value,
                    path=f"{path}.{key}",
                )
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):

            matches.extend(
                find_revenue_candidates(
                    value,
                    path=f"{path}[{index}]",
                )
            )

    return matches


# ============================================================
# EXTRACT NUMERIC VALUES FROM CANDIDATE
# ============================================================

def extract_numeric_values(value):
    """
    Recursively find numeric values inside a revenue candidate.

    This is exploratory only.
    """

    values = []

    if isinstance(value, dict):

        for key, item in value.items():

            numeric = safe_float(item)

            if numeric is not None:

                values.append(
                    {
                        "field": str(key),
                        "value": numeric,
                    }
                )

            elif isinstance(
                item,
                (dict, list)
            ):

                values.extend(
                    extract_numeric_values(item)
                )

    elif isinstance(value, list):

        for item in value:

            numeric = safe_float(item)

            if numeric is not None:

                values.append(
                    {
                        "field": None,
                        "value": numeric,
                    }
                )

            elif isinstance(
                item,
                (dict, list)
            ):

                values.extend(
                    extract_numeric_values(item)
                )

    return values


# ============================================================
# MAIN
# ============================================================

results = []


try:

    from nsepython import nse_results

except Exception as exc:

    print(
        "FAILED TO IMPORT NSPYTHON:"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    traceback.print_exc()

    raise


print("=" * 100)
print("NSE XBRL FALLBACK TEST")
print("=" * 100)

print(
    f"Companies to test: {len(SYMBOLS)}"
)

print(
    f"Output CSV: {OUTPUT_CSV.resolve()}"
)

print()


for index, symbol in enumerate(
    SYMBOLS,
    start=1,
):

    print("\n" + "=" * 100)

    print(
        f"[{index}/{len(SYMBOLS)}] "
        f"{symbol}"
    )

    result = {
        "symbol": symbol,

        "nse_result_status": None,

        "financial_year": None,
        "consolidated": None,
        "audited": None,

        "xbrl_url": None,
        "xbrl_http_status": None,
        "xbrl_content_type": None,

        "xbrl_format": None,

        "revenue_candidate_count": 0,
        "revenue_candidate_paths": None,

        "nse_current_revenue_raw": None,
        "nse_previous_revenue_raw": None,

        "nse_current_revenue_crore": None,
        "nse_previous_revenue_crore": None,

        "nse_revenue_growth_percent": None,

        "fallback_status": None,
        "error": None,
    }

    try:

        # ----------------------------------------------------
        # NSE ANNUAL RESULTS
        # ----------------------------------------------------

        print(
            "Fetching NSE annual-result metadata..."
        )

        annual_rows = nse_results(
            index="equities",
            period="Annual",
        )

        if annual_rows is None:

            result[
                "nse_result_status"
            ] = "no_response"

            result[
                "fallback_status"
            ] = "no_nse_results"

            results.append(result)

            print(
                "No NSE result response."
            )

            continue

        # nse_results normally returns a DataFrame.
        if hasattr(
            annual_rows,
            "to_dict",
        ):

            rows = annual_rows.to_dict(
                orient="records"
            )

        elif isinstance(
            annual_rows,
            list,
        ):

            rows = annual_rows

        else:

            raise TypeError(
                "Unexpected nse_results "
                "return type: "
                f"{type(annual_rows).__name__}"
            )

        # ----------------------------------------------------
        # FIND THIS COMPANY
        # ----------------------------------------------------

        company_rows = [
            row
            for row in rows
            if str(
                row.get("symbol", "")
            ).strip().upper()
            == symbol.upper()
        ]

        if not company_rows:

            result[
                "nse_result_status"
            ] = "company_not_found"

            result[
                "fallback_status"
            ] = "company_not_found_in_nse_results"

            results.append(result)

            print(
                "Company not found in "
                "nse_results(index='equities', period='Annual')."
            )

            continue

        result[
            "nse_result_status"
        ] = "found"

        print(
            f"NSE filings found: "
            f"{len(company_rows)}"
        )

        # ----------------------------------------------------
        # SELECT BEST FILING
        # ----------------------------------------------------

        filing = choose_annual_filing(
            company_rows
        )

        if not filing:

            result[
                "fallback_status"
            ] = "no_usable_filing"

            results.append(result)

            print(
                "No usable annual filing."
            )

            continue

        result[
            "financial_year"
        ] = filing.get(
            "financialYear"
        )

        result[
            "consolidated"
        ] = filing.get(
            "consolidated"
        )

        result[
            "audited"
        ] = filing.get(
            "audited"
        )

        print(
            "Selected financial year:",
            result["financial_year"],
        )

        print(
            "Consolidated:",
            result["consolidated"],
        )

        print(
            "Audited:",
            result["audited"],
        )

        # ----------------------------------------------------
        # XBRL URL
        # ----------------------------------------------------

        xbrl_url = extract_xbrl_url(
            filing
        )

        result[
            "xbrl_url"
        ] = xbrl_url

        if not xbrl_url:

            result[
                "fallback_status"
            ] = "no_xbrl_url"

            results.append(result)

            print(
                "No XBRL URL found."
            )

            continue

        print(
            "XBRL URL:",
            xbrl_url,
        )

        # ----------------------------------------------------
        # FETCH XBRL
        # ----------------------------------------------------

        response = fetch_xbrl(
            xbrl_url
        )

        result[
            "xbrl_http_status"
        ] = response.status_code

        result[
            "xbrl_content_type"
        ] = response.headers.get(
            "Content-Type"
        )

        print(
            "HTTP status:",
            response.status_code,
        )

        print(
            "Content-Type:",
            response.headers.get(
                "Content-Type"
            ),
        )

        # ----------------------------------------------------
        # SAVE RAW RESPONSE
        # ----------------------------------------------------

        raw_path = (
            RAW_OUT
            / f"{symbol}_xbrl_raw"
        )

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            ).lower()
        )

        # JSON
        if (
            "json" in content_type
            or response.text.lstrip().startswith(
                "{"
            )
            or response.text.lstrip().startswith(
                "["
            )
        ):

            try:

                data = response.json()

                result[
                    "xbrl_format"
                ] = "json"

                raw_path = raw_path.with_suffix(
                    ".json"
                )

                raw_path.write_text(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                print(
                    "XBRL format: JSON"
                )

                # ------------------------------------------------
                # PRINT STRUCTURE
                # ------------------------------------------------

                print(
                    "\nXBRL JSON structure:"
                )

                inspect_json_structure(
                    data
                )

                # ------------------------------------------------
                # FIND REVENUE CANDIDATES
                # ------------------------------------------------

                candidates = (
                    find_revenue_candidates(
                        data
                    )
                )

                result[
                    "revenue_candidate_count"
                ] = len(candidates)

                paths = [
                    item["path"]
                    for item in candidates
                ]

                result[
                    "revenue_candidate_paths"
                ] = " | ".join(
                    paths[:20]
                )

                print(
                    "\nRevenue-like candidates found:",
                    len(candidates),
                )

                for candidate in candidates[:20]:

                    print(
                        "\nPATH:",
                        candidate["path"],
                    )

                    print(
                        "KEY:",
                        candidate["key"],
                    )

                    print(
                        "VALUE:"
                    )

                    print(
                        json.dumps(
                            candidate["value"],
                            indent=2,
                            ensure_ascii=False,
                            default=str,
                        )[:3000]
                    )

                    numeric_values = (
                        extract_numeric_values(
                            candidate["value"]
                        )
                    )

                    if numeric_values:

                        print(
                            "NUMERIC VALUES:",
                            numeric_values[:20],
                        )

            except Exception as json_exc:

                result[
                    "xbrl_format"
                ] = "json_parse_failed"

                raw_path = raw_path.with_suffix(
                    ".txt"
                )

                raw_path.write_text(
                    response.text,
                    encoding="utf-8",
                )

                raise json_exc

        # XML
        else:

            result[
                "xbrl_format"
            ] = "xml_or_other"

            raw_path = raw_path.with_suffix(
                ".xml"
            )

            raw_path.write_text(
                response.text,
                encoding="utf-8",
            )

            print(
                "XBRL appears to be XML/other."
            )

            print(
                "\nFirst 5,000 characters:"
            )

            print(
                response.text[:5000]
            )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # We intentionally do NOT automatically decide that
        # some arbitrary XBRL value is revenue yet.
        #
        # This first test is to discover the actual structure.
        # ----------------------------------------------------

        result[
            "fallback_status"
        ] = "xbrl_fetched_needs_extraction"

        results.append(result)

    except Exception as exc:

        error_text = (
            f"{type(exc).__name__}: {exc}"
        )

        result[
            "error"
        ] = error_text

        if result[
            "fallback_status"
        ] is None:

            result[
                "fallback_status"
            ] = "error"

        results.append(result)

        print(
            "\nERROR:",
            error_text,
        )

        traceback.print_exc()


# ============================================================
# SAVE CSV
# ============================================================

FIELDNAMES = [
    "symbol",

    "nse_result_status",

    "financial_year",
    "consolidated",
    "audited",

    "xbrl_url",
    "xbrl_http_status",
    "xbrl_content_type",
    "xbrl_format",

    "revenue_candidate_count",
    "revenue_candidate_paths",

    "nse_current_revenue_raw",
    "nse_previous_revenue_raw",

    "nse_current_revenue_crore",
    "nse_previous_revenue_crore",

    "nse_revenue_growth_percent",

    "fallback_status",
    "error",
]


with OUTPUT_CSV.open(
    "w",
    newline="",
    encoding="utf-8",
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=FIELDNAMES,
    )

    writer.writeheader()

    writer.writerows(
        results
    )


# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 100)
print("TEST COMPLETE")
print("=" * 100)

print(
    f"Companies tested: {len(SYMBOLS)}"
)

print(
    f"Results produced: {len(results)}"
)

print(
    f"\nCSV:\n{OUTPUT_CSV.resolve()}"
)

print(
    f"\nRaw XBRL files:\n{RAW_OUT.resolve()}"
)

print("\nStatus summary:")

status_counts = {}

for result in results:

    status = result.get(
        "fallback_status",
        "unknown",
    )

    status_counts[status] = (
        status_counts.get(status, 0)
        + 1
    )

for status, count in sorted(
    status_counts.items()
):

    print(
        f"  {status}: {count}"
    )

print(
    "\nIMPORTANT:"
)

print(
    "This is an exploratory XBRL test."
)

print(
    "We are intentionally NOT treating arbitrary XBRL "
    "values as revenue yet."
)

print(
    "Use the printed XBRL structure + raw files to build "
    "the final revenue extractor."
)