from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


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

RAW_OUT = OUT / "nse_annual_reports"
RAW_OUT.mkdir(parents=True, exist_ok=True)


# ============================================================
# MAIN
# ============================================================

print("=" * 100)
print("NSE ANNUAL REPORTS DISCOVERY TEST")
print("=" * 100)

print("Company:", SYMBOL)


try:

    import nsepython

    print(
        "\nnsepython module:",
        nsepython.__file__,
    )

    # --------------------------------------------------------
    # INSPECT FUNCTION SIGNATURE
    # --------------------------------------------------------

    import inspect

    print("\nFunction signature:")

    print(
        inspect.signature(
            nsepython.nse_annual_reports
        )
    )

    print(
        "\nFunction documentation:"
    )

    print(
        inspect.getdoc(
            nsepython.nse_annual_reports
        )
    )

except Exception as exc:

    print(
        "\nCould not inspect nse_annual_reports:"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    traceback.print_exc()


# ============================================================
# TEST 1 — nse_annual_reports
# ============================================================

try:

    from nsepython import nse_annual_reports

    print("\n" + "=" * 100)
    print("TEST 1 — NSPYTHON nse_annual_reports()")
    print("=" * 100)

    result = nse_annual_reports(
        SYMBOL
    )

    print(
        "\nReturn type:",
        type(result).__name__,
    )

    print(
        "\nRaw result:"
    )

    if hasattr(
        result,
        "to_dict",
    ):

        data = result.to_dict(
            orient="records"
        )

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                default=str,
            )[:30000]
        )

    elif isinstance(
        result,
        (dict, list),
    ):

        data = result

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                default=str,
            )[:30000]
        )

    else:

        data = str(result)

        print(
            data[:30000]
        )

    raw_path = (
        RAW_OUT
        / f"{SYMBOL}_nsepython_annual_reports.json"
    )

    raw_path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        "\nSaved:",
        raw_path.resolve(),
    )

except Exception as exc:

    print(
        "\nERROR in nse_annual_reports():"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    traceback.print_exc()


# ============================================================
# TEST 2 — DIRECT NSE ANNUAL REPORTS ENDPOINT
# ============================================================

try:

    import requests

    print("\n" + "=" * 100)
    print("TEST 2 — DIRECT NSE ANNUAL REPORTS ENDPOINT")
    print("=" * 100)

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/155.0 Safari/537.36"
            ),
            "Accept": (
                "application/json,text/plain,*/*"
            ),
            "Referer": "https://www.nseindia.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    # First establish NSE session.
    home = session.get(
        "https://www.nseindia.com/",
        timeout=30,
    )

    print(
        "\nNSE homepage status:",
        home.status_code,
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # NSE told us that BOTH index and symbol are required.
    # --------------------------------------------------------

    url = (
        "https://www.nseindia.com/api/"
        f"annual-reports?index=cm&symbol={SYMBOL}"
    )

    print(
        "\nRequest URL:",
        url,
    )

    response = session.get(
        url,
        timeout=30,
    )

    print(
        "\nHTTP status:",
        response.status_code,
    )

    print(
        "Content-Type:",
        response.headers.get(
            "Content-Type"
        ),
    )

    print(
        "\nResponse:"
    )

    print(
        response.text[:30000]
    )

    # --------------------------------------------------------
    # Save raw response
    # --------------------------------------------------------

    raw_path = (
        RAW_OUT
        / f"{SYMBOL}_direct_annual_reports.txt"
    )

    raw_path.write_text(
        response.text,
        encoding="utf-8",
    )

    print(
        "\nSaved:",
        raw_path.resolve(),
    )

    # --------------------------------------------------------
    # Try JSON
    # --------------------------------------------------------

    try:

        data = response.json()

        json_path = (
            RAW_OUT
            / f"{SYMBOL}_direct_annual_reports.json"
        )

        json_path.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        print(
            "\nParsed JSON successfully."
        )

        print(
            "Top-level type:",
            type(data).__name__,
        )

        if isinstance(
            data,
            dict,
        ):

            print(
                "Top-level keys:",
                list(data.keys()),
            )

        elif isinstance(
            data,
            list,
        ):

            print(
                "Number of records:",
                len(data),
            )

        print(
            "\nJSON saved:",
            json_path.resolve(),
        )

    except Exception as json_exc:

        print(
            "\nResponse is not JSON."
        )

        print(
            "JSON parse error:",
            type(json_exc).__name__,
            str(json_exc),
        )

except Exception as exc:

    print(
        "\nERROR in direct NSE request:"
    )

    print(
        type(exc).__name__,
        str(exc),
    )

    traceback.print_exc()


# ============================================================
# TEST 3 — TRY nse_annual_reports WITH COMMON PARAMETERS
# ============================================================

print("\n" + "=" * 100)
print("TEST 3 — ALTERNATIVE nse_annual_reports CALLS")
print("=" * 100)


try:

    from nsepython import nse_annual_reports

    # Try the most common possible calling conventions.
    calls = [
        (
            "symbol_only",
            lambda: nse_annual_reports(
                SYMBOL
            ),
        ),
        (
            "symbol_cm",
            lambda: nse_annual_reports(
                SYMBOL,
                "cm",
            ),
        ),
        (
            "cm_symbol",
            lambda: nse_annual_reports(
                "cm",
                SYMBOL,
            ),
        ),
    ]

    for name, func in calls:

        print(
            "\n"
            + "-" * 80
        )

        print(
            "CALL:",
            name,
        )

        try:

            result = func()

            print(
                "SUCCESS"
            )

            print(
                "Type:",
                type(result).__name__,
            )

            if hasattr(
                result,
                "to_dict",
            ):

                data = result.to_dict(
                    orient="records"
                )

            else:

                data = result

            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )[:15000]
            )

        except Exception as exc:

            print(
                "FAILED:"
            )

            print(
                type(exc).__name__,
                str(exc),
            )

except Exception as exc:

    print(
        "Could not import function:",
        type(exc).__name__,
        str(exc),
    )


# ============================================================
# COMPLETE
# ============================================================

print("\n" + "=" * 100)
print("TEST COMPLETE")
print("=" * 100)

print(
    "\nRaw output directory:"
)

print(
    RAW_OUT.resolve()
)

print(
    "\nSend me the terminal output."
)

print(
    "Especially look for:"
)

print(
    "1. nse_annual_reports() result"
)

print(
    "2. Direct /api/annual-reports?index=cm&symbol=AONESTEELS"
)

print(
    "3. Any PDF/report URLs"
)

print(
    "4. Any XBRL URLs"
)