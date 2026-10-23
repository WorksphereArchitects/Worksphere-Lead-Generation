from datetime import date
from pathlib import Path
import inspect, traceback

OUT = Path("financial_test_output")
OUT.mkdir(exist_ok=True)

try:
    import pandas as pd
    from nselib import capital_market

    fn = capital_market.financial_results_for_equity
    print("Function signature:", inspect.signature(fn))
    kwargs = {
        "from_date": "01-01-2023",
        "to_date": date.today().strftime("%d-%m-%Y"),
        "fo_sec": False,
        "fin_period": "Annual",
    }
    print("Calling with:", kwargs)
    result = fn(**kwargs)

    if result is None:
        print("No result returned.")
    elif isinstance(result, pd.DataFrame):
        print("Rows:", len(result))
        print("Columns:", list(result.columns))
        print(result.head(10).to_string(index=False))
        out = OUT / "nselib_annual_results.csv"
        result.to_csv(out, index=False)
        print("Saved:", out.resolve())
        for col in result.columns:
            if any(x in str(col).lower() for x in ("symbol", "company", "isin")):
                mask = result[col].astype(str).str.upper().str.contains(
                    r"ASIANPAINT|RELIANCE|INFOSYS|INFY", regex=True, na=False
                )
                if mask.any():
                    print("Sample matches on", col)
                    print(result.loc[mask].head(12).to_string(index=False))
    else:
        print("Returned type:", type(result))
        print(str(result)[:10000])
except Exception as exc:
    print("NSELIB TEST FAILED:", type(exc).__name__, str(exc))
    traceback.print_exc()
