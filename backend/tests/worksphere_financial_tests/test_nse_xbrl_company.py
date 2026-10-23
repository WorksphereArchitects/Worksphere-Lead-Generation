from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import requests


# ============================================================
# PATH SETUP
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ============================================================
# TEST COMPANY
# ============================================================

SYMBOL = "AONESTEELS"


# ============================================================
# OUTPUT
# ============================================================

OUT = Path("financial_test_output")
OUT.mkdir(parents=True, exist_ok=True)

RAW_OUT = OUT / "nse_single_company"
RAW_OUT.mkdir(parents=True, exist_ok=True)


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
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Referer": "https://www.nseindia.com/",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


# ============================================================
# HELPERS
# ============================================================

def print_response(label, response):
    print("\n" + "=" * 100)
    print(label)
    print("=" * 100)

    print("URL:", response.url)
    print("Status:", response.status_code)
    print(
        "Content-Type:",
        response.headers.get("Content-Type"),
    )
    print(
        "Content-Length:",
        response.headers.get("Content-Length"),
    )

    print("\nResponse preview:")

    print(response.text[:5000])


def save_response(filename, response):
    path = RAW_OUT / filename

    content_type = (
        response.headers.get(
            "Content-Type",
            "",
        ).lower()
    )

    if "json" in content_type:

        try:
            data = response.json()

            path = path.with_suffix(".json")

            path.write_text(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )

            return path

        except Exception:
            pass

    path = path.with_suffix(".txt")

    path.write_text(
        response.text,
        encoding="utf-8",
    )

    return path


def try_json(response):
    try:
        return response.json()
    except Exception:
        return None


# ============================================================
# MAIN
# ============================================================

print("=" * 100)
print("NSE SINGLE COMPANY DISCOVERY TEST")
print("=" * 100)

print("Company:", SYMBOL)

print(
    "\nIMPORTANT:"
    "\nThis test is NOT extracting revenue yet."
    "\nWe are discovering which NSE endpoint exposes"
    "\nthe company's annual filing/XBRL data."
)


# ============================================================
# STEP 1 — NSE HOME
# ============================================================

try:

    print("\n\nSTEP 1 — Initialising NSE session")

    response = SESSION.get(
        "https://www.nseindia.com/",
        timeout=30,
    )

    print_response(
        "NSE HOME RESPONSE",
        response,
    )

    print(
        "\nCookies received:",
        SESSION.cookies.get_dict(),
    )

except Exception as exc:

    print(
        "\nFailed to initialise NSE session:",
        type(exc).__name__,
        str(exc),
    )


# ============================================================
# STEP 2 — EQUITY MASTER / SYMBOL SEARCH
# ============================================================

equity_urls = [
    (
        "equity_master",
        "https://www.nseindia.com/api/equity-master",
    ),
    (
        "equity_list",
        "https://www.nseindia.com/api/equity-list",
    ),
]


for name, url in equity_urls:

    try:

        print(
            "\n\nSTEP 2 — Trying:",
            name,
        )

        response = SESSION.get(
            url,
            timeout=30,
        )

        print_response(
            f"{name.upper()} RESPONSE",
            response,
        )

        data = try_json(response)

        if data is not None:

            print(
                "\nParsed JSON type:",
                type(data).__name__,
            )

            if isinstance(data, list):

                print(
                    "Number of records:",
                    len(data),
                )

                matches = []

                for row in data:

                    if not isinstance(row, dict):
                        continue

                    row_text = " ".join(
                        str(value)
                        for value in row.values()
                    ).upper()

                    if SYMBOL.upper() in row_text:

                        matches.append(row)

                print(
                    f"Matches for {SYMBOL}:",
                    len(matches),
                )

                for row in matches[:10]:

                    print(
                        "\nMATCH:"
                    )

                    print(
                        json.dumps(
                            row,
                            indent=2,
                            ensure_ascii=False,
                            default=str,
                        )[:5000]
                    )

            elif isinstance(data, dict):

                print(
                    "Top-level keys:"
                )

                print(
                    list(data.keys())[:100]
                )

        saved = save_response(
            f"{name}",
            response,
        )

        print(
            "\nSaved response:",
            saved.resolve(),
        )

    except Exception as exc:

        print(
            "\nERROR:",
            type(exc).__name__,
            str(exc),
        )


# ============================================================
# STEP 3 — COMPANY-SPECIFIC NSE API
# ============================================================

company_urls = [
    (
        "quote_equity",
        (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={SYMBOL}"
        ),
    ),
    (
        "corporate_info",
        (
            "https://www.nseindia.com/api/"
            f"corporate-info?symbol={SYMBOL}"
        ),
    ),
    (
        "annual_reports",
        (
            "https://www.nseindia.com/api/"
            f"annual-reports?symbol={SYMBOL}"
        ),
    ),
]


for name, url in company_urls:

    try:

        print(
            "\n\nSTEP 3 — Trying:",
            name,
        )

        response = SESSION.get(
            url,
            timeout=30,
        )

        print_response(
            f"{name.upper()} RESPONSE",
            response,
        )

        data = try_json(response)

        if data is not None:

            print(
                "\nParsed JSON:"
            )

            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )[:10000]
            )

        saved = save_response(
            f"{name}",
            response,
        )

        print(
            "\nSaved response:",
            saved.resolve(),
        )

    except Exception as exc:

        print(
            "\nERROR:",
            type(exc).__name__,
            str(exc),
        )


# ============================================================
# STEP 4 — NSPYTHON COMPANY-SPECIFIC FUNCTIONS
# ============================================================

print(
    "\n\n"
    + "=" * 100
)

print(
    "STEP 4 — NSPYTHON DISCOVERY"
)

print(
    "=" * 100
)


try:

    import nsepython

    print(
        "\nnsepython module:",
        nsepython.__file__,
    )

    print(
        "\nAvailable functions containing "
        "'annual', 'result', 'xbrl', or 'financial':"
    )

    names = [
        name
        for name in dir(nsepython)
        if any(
            term in name.lower()
            for term in [
                "annual",
                "result",
                "xbrl",
                "financial",
            ]
        )
    ]

    for name in sorted(names):

        print(
            " ",
            name,
        )

except Exception as exc:

    print(
        "\nCould not inspect nsepython:",
        type(exc).__name__,
        str(exc),
    )


# ============================================================
# STEP 5 — EXISTING NSPYTHON ANNUAL RESULTS
# ============================================================

try:

    from nsepython import nse_results

    print(
        "\n\n"
        + "=" * 100
    )

    print(
        "STEP 5 — NSPYTHON nse_results()"
    )

    print(
        "=" * 100
    )

    annual_rows = nse_results(
        index="equities",
        period="Annual",
    )

    print(
        "\nReturn type:",
        type(annual_rows).__name__,
    )

    if hasattr(
        annual_rows,
        "shape",
    ):

        print(
            "Shape:",
            annual_rows.shape,
        )

    if hasattr(
        annual_rows,
        "columns",
    ):

        print(
            "\nColumns:"
        )

        print(
            list(
                annual_rows.columns
            )
        )

    if hasattr(
        annual_rows,
        "to_dict",
    ):

        rows = annual_rows.to_dict(
            orient="records"
        )

    else:

        rows = annual_rows

    print(
        "\nTotal rows:",
        len(rows),
    )

    company_rows = [
        row
        for row in rows
        if str(
            row.get(
                "symbol",
                "",
            )
        ).strip().upper()
        == SYMBOL.upper()
    ]

    print(
        f"\nExact symbol matches for "
        f"{SYMBOL}:",
        len(company_rows),
    )

    if company_rows:

        for row in company_rows:

            print(
                "\n"
                + json.dumps(
                    row,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

    else:

        print(
            "\nAs expected, this company is not "
            "present in the small nse_results() dataset."
        )

except Exception as exc:

    print(
        "\nERROR in nse_results():",
        type(exc).__name__,
        str(exc),
    )

    traceback.print_exc()


# ============================================================
# STEP 6 — SEARCH NSE WEBSITE FOR COMPANY
# ============================================================

try:

    print(
        "\n\n"
        + "=" * 100
    )

    print(
        "STEP 6 — NSE WEBSITE SEARCH"
    )

    print(
        "=" * 100
    )

    search_url = (
        "https://www.nseindia.com/"
        f"search?q={SYMBOL}"
    )

    response = SESSION.get(
        search_url,
        timeout=30,
    )

    print_response(
        "NSE SEARCH RESPONSE",
        response,
    )

    saved = save_response(
        "nse_search",
        response,
    )

    print(
        "\nSaved response:",
        saved.resolve(),
    )

except Exception as exc:

    print(
        "\nERROR:",
        type(exc).__name__,
        str(exc),
    )


# ============================================================
# FINAL
# ============================================================

print(
    "\n\n"
    + "=" * 100
)

print(
    "DISCOVERY TEST COMPLETE"
)

print(
    "=" * 100
)

print(
    "\nRaw responses saved to:"
)

print(
    RAW_OUT.resolve()
)

print(
    "\nNext step:"
)

print(
    "Send me the terminal output + the generated files."
)

print(
    "\nWe will then identify the exact NSE endpoint/"
    "filing structure before writing the XBRL revenue extractor."
)