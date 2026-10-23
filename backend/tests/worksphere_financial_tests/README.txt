WorkSphere financial source tests
=================================

These scripts are isolated experiments. They do not import WorkSphere, write to
Supabase, change qualification, download annual reports, or call Gemini.

Install individually in the same Python environment as your backend:

    pip install nselib pandas
    pip install nsepython pandas
    pip install yfinance pandas

Run separately:

    python test_nselib.py
    python test_nsepython.py
    python test_yfinance.py

Outputs are written to financial_test_output/.

Please send back each terminal output and the generated CSV files.

Important: NSE wrappers are unofficial and endpoint schemas can change.
Yahoo Finance may differ in coverage, reporting period, currency/units, and
consolidated versus standalone figures. These raw tests are for comparison only;
we will verify units, years, and reporting basis before using data to qualify
companies.
