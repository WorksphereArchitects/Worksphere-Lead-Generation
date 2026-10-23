from pathlib import Path
import traceback
import csv

OUT = Path("financial_test_output")
OUT.mkdir(exist_ok=True)

SAMPLES = [
    "ASIANPAINT.NS",
    "RELIANCE.NS",
    "INFY.NS",
]

OUTPUT_CSV = OUT / "yfinance_currency_revenue_test.csv"


def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)

        if value != value:  # NaN
            return None

        return value

    except (TypeError, ValueError):
        return None


def find_revenue_rows(annual):
    """
    Find revenue-related rows while preserving the actual
    Yahoo Finance line-item names.
    """

    mask = [
        any(
            term in str(label).lower()
            for term in (
                "total revenue",
                "operating revenue",
                "revenue",
            )
        )
        for label in annual.index
    ]

    return annual.loc[mask]


results = []

try:
    import yfinance as yf

    for symbol in SAMPLES:

        print("\n" + "=" * 80)
        print("Ticker:", symbol)

        result = {
            "ticker": symbol,
            "currency": None,
            "currency_status": None,

            "revenue_row": None,

            "current_period": None,
            "current_revenue_raw": None,
            "current_revenue_crore": None,

            "previous_period": None,
            "previous_revenue_raw": None,
            "previous_revenue_crore": None,

            "revenue_growth_percent": None,

            "annual_statement_status": None,
            "error": None,
        }

        try:
            ticker = yf.Ticker(symbol)

            # ============================================================
            # CURRENCY
            # ============================================================

            try:
                info = ticker.get_info()

                currency = info.get("currency")

                result["currency"] = currency

                print("Yahoo currency:", currency)

                if currency == "INR":
                    result["currency_status"] = "INR"

                    print(
                        "Currency check: ✓ INR"
                    )

                elif currency:
                    result["currency_status"] = (
                        f"unsupported_{currency}"
                    )

                    print(
                        f"Currency check: ✗ UNSUPPORTED "
                        f"({currency})"
                    )

                else:
                    result["currency_status"] = (
                        "currency_unavailable"
                    )

                    print(
                        "Currency check: ! "
                        "Currency unavailable"
                    )

            except Exception as currency_exc:

                result["currency_status"] = (
                    "currency_check_failed"
                )

                result["error"] = (
                    f"Currency check: "
                    f"{type(currency_exc).__name__}: "
                    f"{currency_exc}"
                )

                print(
                    "Currency check failed:",
                    type(currency_exc).__name__,
                    str(currency_exc)
                )

            # ============================================================
            # ANNUAL INCOME STATEMENT
            # ============================================================

            annual = ticker.income_stmt

            if annual is None or annual.empty:

                result["annual_statement_status"] = (
                    "no_data"
                )

                print(
                    "No annual income statement returned."
                )

                results.append(result)
                continue

            result["annual_statement_status"] = (
                "available"
            )

            print(
                "Period columns:",
                [str(c) for c in annual.columns]
            )

            print(
                "Available line items:",
                list(annual.index)
            )

            # ============================================================
            # REVENUE ROWS
            # ============================================================

            revenue_rows = find_revenue_rows(annual)

            print(
                "\nRevenue-related rows:"
            )

            if revenue_rows.empty:

                print(
                    "No obvious revenue row found."
                )

                result["annual_statement_status"] = (
                    "revenue_row_not_found"
                )

                results.append(result)
                continue

            print(
                revenue_rows.to_string()
            )

            # ============================================================
            # CHOOSE REVENUE ROW
            # ============================================================

            preferred_rows = [
                "Total Revenue",
                "Operating Revenue",
                "TotalRevenue",
                "OperatingRevenue",
                "Revenue",
            ]

            selected_row_name = None

            # Exact preferred match
            for row_name in preferred_rows:

                if row_name in annual.index:

                    selected_row_name = row_name
                    break

            # Case-insensitive match
            if selected_row_name is None:

                normalized = {
                    str(index).strip().lower(): index
                    for index in annual.index
                }

                for row_name in preferred_rows:

                    key = row_name.lower()

                    if key in normalized:

                        selected_row_name = normalized[key]
                        break

            # Last fallback
            if selected_row_name is None:

                selected_row_name = revenue_rows.index[0]

            result["revenue_row"] = str(
                selected_row_name
            )

            print(
                "\nSelected revenue row:",
                selected_row_name
            )

            revenue_row = annual.loc[
                selected_row_name
            ]

            # ============================================================
            # EXTRACT ANNUAL REVENUE VALUES
            # ============================================================

            values = []

            for period in revenue_row.index:

                value = safe_float(
                    revenue_row.get(period)
                )

                if value is None:
                    continue

                values.append(
                    {
                        "period": str(period),
                        "value": value,
                    }
                )

            # Yahoo normally returns newest first,
            # but sort explicitly for safety.
            values.sort(
                key=lambda x: x["period"],
                reverse=True
            )

            if len(values) >= 1:

                current = values[0]

                result["current_period"] = (
                    current["period"]
                )

                result["current_revenue_raw"] = (
                    current["value"]
                )

            if len(values) >= 2:

                previous = values[1]

                result["previous_period"] = (
                    previous["period"]
                )

                result["previous_revenue_raw"] = (
                    previous["value"]
                )

            # ============================================================
            # INR → CRORE
            # ============================================================

            if result["currency"] == "INR":

                if result["current_revenue_raw"] is not None:

                    result["current_revenue_crore"] = (
                        result["current_revenue_raw"]
                        / 10_000_000
                    )

                if result["previous_revenue_raw"] is not None:

                    result["previous_revenue_crore"] = (
                        result["previous_revenue_raw"]
                        / 10_000_000
                    )

                print(
                    "\nCurrency verified as INR."
                )

                print(
                    "Current:",
                    result["current_revenue_raw"],
                    "INR →",
                    result["current_revenue_crore"],
                    "Cr"
                )

                print(
                    "Previous:",
                    result["previous_revenue_raw"],
                    "INR →",
                    result["previous_revenue_crore"],
                    "Cr"
                )

            else:

                print(
                    "\nCurrency is not verified as INR."
                )

                print(
                    "Skipping INR crore conversion."
                )

            # ============================================================
            # GROWTH
            # ============================================================

            current_crore = result[
                "current_revenue_crore"
            ]

            previous_crore = result[
                "previous_revenue_crore"
            ]

            if (
                current_crore is not None
                and previous_crore is not None
                and previous_crore != 0
            ):

                growth = (
                    (
                        current_crore
                        - previous_crore
                    )
                    / previous_crore
                ) * 100

                result[
                    "revenue_growth_percent"
                ] = growth

                print(
                    f"Growth: {growth:.2f}%"
                )

            else:

                print(
                    "Growth: unavailable"
                )

        except Exception as exc:

            result["annual_statement_status"] = (
                "error"
            )

            error_text = (
                f"{type(exc).__name__}: {exc}"
            )

            if result["error"]:
                result["error"] += (
                    " | " + error_text
                )
            else:
                result["error"] = error_text

            print(
                "Ticker failed:",
                error_text
            )

            traceback.print_exc()

        results.append(result)


except Exception as exc:

    print(
        "YFINANCE TEST FAILED:",
        type(exc).__name__,
        str(exc)
    )

    traceback.print_exc()


# ========================================================================
# SAVE ALL 3 COMPANIES INTO ONE CSV
# ========================================================================

FIELDNAMES = [
    "ticker",
    "currency",
    "currency_status",

    "revenue_row",

    "current_period",
    "current_revenue_raw",
    "current_revenue_crore",

    "previous_period",
    "previous_revenue_raw",
    "previous_revenue_crore",

    "revenue_growth_percent",

    "annual_statement_status",
    "error",
]


with OUTPUT_CSV.open(
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=FIELDNAMES
    )

    writer.writeheader()
    writer.writerows(results)


print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)

print(
    f"Results saved to:\n"
    f"{OUTPUT_CSV.resolve()}"
)

print(
    f"\nCompanies tested: {len(results)}"
)