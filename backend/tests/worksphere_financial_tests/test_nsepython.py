from pathlib import Path
import traceback

OUT = Path("financial_test_output")
OUT.mkdir(exist_ok=True)

try:
    import pandas as pd
    from nsepython import nse_results

    print("Fetching NSE annual financial results...")
    result = nse_results(index="equities", period="Annual")
    if result is None:
        print("No result returned.")
    elif isinstance(result, pd.DataFrame):
        print("Rows:", len(result))
        print("Columns:", list(result.columns))
        print(result.head(10).to_string(index=False))
        out = OUT / "nsepython_annual_results.csv"
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
    print("NSEPYTHON TEST FAILED:", type(exc).__name__, str(exc))
    traceback.print_exc()
