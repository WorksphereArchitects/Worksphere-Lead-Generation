import httpx
import logging

logger = logging.getLogger(__name__)

def test_nse_connection():
    urls = [
        "https://www.nseindia.com/",
        "https://www.nseindia.com/api/annual-reports?index=equities&symbol=MEESHO",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/",
        "Origin": "https://www.nseindia.com",
    }

    with httpx.Client(
        headers=headers,
        timeout=20,
        follow_redirects=True,
    ) as client:

        for url in urls:
            try:
                response = client.get(url)

                logger.info(
                    "NSE TEST | URL=%s | STATUS=%s | SERVER=%s",
                    url,
                    response.status_code,
                    response.headers.get("server"),
                )

            except Exception:
                logger.exception("NSE diagnostic failed: %s", url)
                
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_nse_connection()