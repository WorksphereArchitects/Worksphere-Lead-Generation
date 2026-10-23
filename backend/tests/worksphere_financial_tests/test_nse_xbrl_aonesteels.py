import requests
from nse_xbrl import NSEClient

SYMBOL = "AONESTEELS"
COMPANY_NAME = "A One Steels India Limited"

NSE_HOME = "https://www.nseindia.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def main():
    print("=" * 70)
    print("NSE XBRL COOKIE + FINANCIAL TEST")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(HEADERS)

    print("\n1. Opening NSE homepage...")

    response = session.get(
        NSE_HOME,
        timeout=20,
    )

    print("HTTP status:", response.status_code)
    print("Cookies received:", len(session.cookies))

    if not session.cookies:
        print("\n❌ NSE did not provide cookies.")
        print("Response headers:")
        for key, value in response.headers.items():
            if "cookie" in key.lower():
                print(key, value)

        return

    cookie_string = "; ".join(
        f"{cookie.name}={cookie.value}"
        for cookie in session.cookies
    )

    print("\nCookie string obtained:")
    print(cookie_string[:300] + "...")

    print("\n2. Creating NSE XBRL client...")

    try:
        client = NSEClient(
            cookie_string=cookie_string
        )
    except Exception as exc:
        print("❌ Failed to create NSEClient:")
        print(type(exc).__name__, exc)
        return

    print("✅ NSEClient created.")

    print("\n3. Fetching financial filings...")
    print("Symbol:", SYMBOL)
    print("Company:", COMPANY_NAME)

    try:
        filings = client.fetch_financials(
            SYMBOL,
            COMPANY_NAME,
            max_filings=12,
        )
    except Exception as exc:
        print("\n❌ fetch_financials failed:")
        print(type(exc).__name__, exc)
        return

    print("\nReturned filings:", len(filings))

    if not filings:
        print(
            "\n⚠️ No filings returned even with NSE cookies."
        )
        print(
            "This means we need to inspect the package's "
            "actual NSE endpoint/query next."
        )
        return

    print("\n" + "=" * 70)
    print("FILINGS")
    print("=" * 70)

    for i, filing in enumerate(filings, 1):
        print(f"\nFiling #{i}")

        for attr in [
            "symbol",
            "period_start",
            "period_end",
            "is_consolidated",
            "q_revenue",
            "ytd_revenue",
            "q_pat",
            "ytd_pat",
        ]:
            if hasattr(filing, attr):
                print(
                    f"{attr}:",
                    getattr(filing, attr)
                )


if __name__ == "__main__":
    main()