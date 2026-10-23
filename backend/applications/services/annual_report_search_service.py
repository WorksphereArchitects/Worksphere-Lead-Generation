"""
Annual Report Search Service - Currently does not work with free tier of Gemini API.

Flow:
    Company
      ↓
    Gemini Flash-Lite + Google Search grounding
      ↓
    Identify official company website ONLY
      ↓
    Python verifies website reachability
      ↓
    Crawl ONLY the verified official domain
      ↓
    Find Investor Relations / Annual Reports / Financial Reports pages
      ↓
    Find current FY + previous FY annual report URLs
      ↓
    Validate report URLs

Important:
- Gemini is used ONLY for official website discovery.
- Gemini does NOT search for annual reports.
- Annual report discovery is Python-only.
- No NSE/BSE/third-party annual-report search.
- Flash-Lite only.
- Rate limits are handled with retries and exponential backoff.
"""

import json
import logging
import os
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite",
)

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not configured in .env"
    )

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# -------------------------------------------------------------------
# HTTP / CRAWLER CONFIG
# -------------------------------------------------------------------

REQUEST_TIMEOUT = 15

MAX_PAGES_TO_CRAWL = 20

MAX_REPORT_LINKS = 100


# -------------------------------------------------------------------
# GEMINI RATE LIMIT CONFIG
# -------------------------------------------------------------------

# Maximum number of retries AFTER the first request.
GEMINI_MAX_RETRIES = 3

# Initial wait after a rate-limit/temporary error.
GEMINI_INITIAL_BACKOFF = 30

# Maximum wait between retries.
GEMINI_MAX_BACKOFF = 300


# -------------------------------------------------------------------
# HTTP HEADERS
# -------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/155.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/pdf,*/*"
    ),
}


# -------------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# HTTP SESSION
# -------------------------------------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


# ===================================================================
# GENERAL HELPERS
# ===================================================================

def clean_url(url: str) -> str:
    """Normalize a URL."""

    url = url.strip()

    url, _ = urldefrag(url)

    if not url.startswith(
        ("http://", "https://")
    ):
        url = "https://" + url

    return url.rstrip("/")


def normalize_domain(url: str) -> str:
    """Return normalized hostname."""

    parsed = urlparse(url)

    return parsed.netloc.lower().replace(
        "www.",
        "",
    )


def is_same_domain(
    url: str,
    base_domain: str,
) -> bool:
    """Check whether URL belongs to the official domain."""

    return (
        normalize_domain(url)
        == base_domain
    )


def looks_like_pdf(url: str) -> bool:
    """Check whether URL looks like a PDF."""

    path = urlparse(url).path.lower()

    return (
        path.endswith(".pdf")
        or ".pdf?" in url.lower()
    )


def looks_like_annual_report_text(
    text: str,
) -> bool:
    """
    Determine whether visible page/link text
    is related to annual reports.
    """

    text = text.lower()

    keywords = [
        "annual report",
        "annual reports",
        "financial report",
        "financial reports",
        "annual financial",
        "yearly report",
        "reports and disclosures",
        "reports & disclosures",
        "investor relations",
        "investors",
        "financials",
    ]

    return any(
        keyword in text
        for keyword in keywords
    )


def extract_years(
    text: str,
) -> List[str]:
    """
    Extract FY patterns such as:

        2025-26
        2024-25
        2025–26
        FY 2025-26
        2025/26
    """

    text = (
        text
        .replace("–", "-")
        .replace("—", "-")
    )

    patterns = [
        r"\b(20\d{2})\s*-\s*(\d{2})\b",
        r"\bFY\s*(20\d{2})\s*[-/]\s*(\d{2})\b",
        r"\b(20\d{2})\s*/\s*(\d{2})\b",
    ]

    results = []

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):

            first = match.group(1)
            second = match.group(2)

            if len(second) == 2:
                year = f"{first}-{second}"
            else:
                year = (
                    f"{first}-{second[-2:]}"
                )

            if year not in results:
                results.append(year)

    return results


# ===================================================================
# GEMINI RATE-LIMITED REQUEST
# ===================================================================

def generate_gemini_with_retry(
    prompt: str,
) -> Optional[Any]:
    """
    Call Gemini Flash-Lite with rate-limit handling.

    Handles:
        - HTTP 429
        - quota errors
        - rate-limit errors
        - HTTP 500
        - HTTP 503
        - temporary unavailability

    Retry strategy:

        Attempt 1
             ↓
           error
             ↓
          30 sec
             ↓
        Attempt 2
             ↓
           error
             ↓
          60 sec
             ↓
        Attempt 3
             ↓
           error
             ↓
         120 sec
             ↓
        Attempt 4
             ↓
          give up

    No model fallback is used.
    """

    total_attempts = (
        GEMINI_MAX_RETRIES + 1
    )

    for attempt in range(
        total_attempts
    ):

        try:

            logger.info(
                "Gemini request using %s "
                "(attempt %d/%d)...",
                GEMINI_MODEL,
                attempt + 1,
                total_attempts,
            )

            response = (
                client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type=(
                            "application/json"
                        ),
                        tools=[
                            types.Tool(
                                google_search=(
                                    types.GoogleSearch()
                                )
                            )
                        ],
                    ),
                )
            )

            logger.info(
                "Gemini request successful."
            )

            return response

        except Exception as exc:

            # -------------------------------------------------------
            # PRINT FULL GEMINI ERROR DETAILS
            # -------------------------------------------------------

            logger.error(
                "\n"
                "================ GEMINI ERROR ================\n"
                "Exception type: %s\n"
                "Exception: %s\n"
                "Exception repr: %r\n"
                "================================================",
                type(exc).__name__,
                str(exc),
                exc,
            )

            error_text = str(exc).lower()

            # -------------------------------------------------------
            # Detect rate-limit/quota errors
            # -------------------------------------------------------

            is_rate_limit = any(
                phrase in error_text
                for phrase in [
                    "429",
                    "quota",
                    "rate limit",
                    "resource exhausted",
                    "too many requests",
                ]
            )

            # -------------------------------------------------------
            # Detect temporary server errors
            # -------------------------------------------------------

            is_temporary = any(
                phrase in error_text
                for phrase in [
                    "500",
                    "503",
                    "unavailable",
                    "deadline exceeded",
                    "internal server error",
                    "service unavailable",
                ]
            )

            # -------------------------------------------------------
            # Permanent error
            # -------------------------------------------------------

            if not (
                is_rate_limit
                or is_temporary
            ):

                logger.error(
                    "Gemini request failed permanently: %s",
                    exc,
                )

                return None

            # -------------------------------------------------------
            # No retries remaining
            # -------------------------------------------------------

            if attempt >= GEMINI_MAX_RETRIES:

                logger.error(
                    "Gemini retry limit reached. "
                    "Giving up on this request."
                )

                return None

            # -------------------------------------------------------
            # Exponential backoff
            # -------------------------------------------------------

            backoff = min(
                GEMINI_INITIAL_BACKOFF
                * (2 ** attempt),
                GEMINI_MAX_BACKOFF,
            )

            logger.warning(
                "\n"
                "Gemini rate limit/temporary error detected.\n"
                "Full error above.\n"
                "Retrying in %d seconds...",
                backoff,
            )

            time.sleep(backoff)

    return None


# ===================================================================
# GEMINI: OFFICIAL WEBSITE DISCOVERY ONLY
# ===================================================================

def find_official_company_websites(
    company: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Use Gemini Flash-Lite + Google Search grounding
    ONLY to identify possible official company websites.

    Gemini does NOT search for annual reports.
    """

    company_name = company.get(
        "name",
        "",
    ).strip()

    symbol = company.get(
        "symbol",
        "",
    ).strip()

    sector = company.get(
        "sector"
    )

    logger.info(
        "Finding official website for %s (%s) "
        "using Gemini + Google Search grounding...",
        company_name,
        symbol,
    )

    prompt = f"""
You are identifying the official corporate website
of a company.

Company name:
{company_name}

Stock symbol:
{symbol}

Sector:
{sector or "Unknown"}

Use Google Search grounding ONLY to identify
the company's official corporate website.

STRICT RULES:

1. Return ONLY the company's own official
   corporate website.

2. Do NOT search for annual reports.

3. Do NOT return annual report PDF URLs.

4. Do NOT return NSE.

5. Do NOT return BSE.

6. Do NOT return Moneycontrol.

7. Do NOT return Screener.

8. Do NOT return Economic Times.

9. Do NOT return Bloomberg.

10. Do NOT return LinkedIn.

11. Do NOT return Facebook, Instagram,
    or other social media.

12. Do NOT return a registrar, broker,
    financial portal, directory, news website,
    or other third-party website.

13. Prefer the company's current official
    corporate domain.

14. If the company has changed its domain
    or uses a parent/group corporate website,
    identify the website that actually represents
    the company.

15. Return up to 3 possible official corporate
    website candidates only when genuinely
    necessary.

Return ONLY valid JSON in this exact format:

{{
  "websites": [
    {{
      "url": "https://example.com",
      "reason": "Official corporate website"
    }}
  ]
}}

Do not include markdown.
Do not include explanations outside the JSON.
"""

    response = generate_gemini_with_retry(
        prompt
    )

    if response is None:
        return []

    try:

        raw_text = response.text.strip()

        data = json.loads(
            raw_text
        )

        websites = data.get(
            "websites",
            [],
        )

        if not isinstance(
            websites,
            list,
        ):

            logger.warning(
                "Gemini returned an invalid "
                "website list."
            )

            return []

        results = []

        for item in websites:

            if not isinstance(
                item,
                dict,
            ):
                continue

            url = item.get(
                "url"
            )

            if not url or not isinstance(
                url,
                str,
            ):
                continue

            url = clean_url(
                url
            )

            results.append(
                {
                    "url": url,
                    "reason": item.get(
                        "reason",
                        "Gemini identified "
                        "this as the official website",
                    ),
                    "source": (
                        "gemini_flash_lite_"
                        "google_search"
                    ),
                }
            )

        logger.info(
            "Gemini returned %d official "
            "website candidate(s).",
            len(results),
        )

        for index, website in enumerate(
            results,
            start=1,
        ):

            logger.info(
                "Website candidate %d: %s",
                index,
                website["url"],
            )

        return results[:3]

    except json.JSONDecodeError as exc:

        logger.error(
            "Gemini returned invalid JSON: %s",
            exc,
        )

        return []

    except Exception as exc:

        logger.exception(
            "Failed to process Gemini response: %s",
            exc,
        )

        return []


# ===================================================================
# WEBSITE VALIDATION
# ===================================================================

def verify_website(
    url: str,
) -> Optional[Dict[str, Any]]:
    """
    Verify that an official website candidate
    is reachable.
    """

    url = clean_url(
        url
    )

    logger.info(
        "Checking website: %s",
        url,
    )

    try:

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:

            logger.warning(
                "Website returned HTTP %s: %s",
                response.status_code,
                url,
            )

            return None

        final_url = clean_url(
            response.url
        )

        content_type = (
            response.headers
            .get(
                "Content-Type",
                "",
            )
            .lower()
        )

        if "text/html" not in content_type:

            logger.warning(
                "Website did not return HTML: "
                "%s (%s)",
                final_url,
                content_type,
            )

            return None

        return {
            "url": final_url,
            "domain": normalize_domain(
                final_url
            ),
            "status_code": (
                response.status_code
            ),
            "content_type": content_type,
        }

    except requests.RequestException as exc:

        logger.warning(
            "Unable to access %s: %s",
            url,
            exc,
        )

        return None


def find_verified_official_website(
    website_candidates: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """
    Check Gemini's website candidates.

    IMPORTANT:
    This function does NOT call Gemini again.
    """

    for candidate in website_candidates:

        url = candidate.get(
            "url"
        )

        if not url:
            continue

        verified = verify_website(
            url
        )

        if verified:

            verified["source"] = (
                candidate.get(
                    "source",
                    "gemini_flash_lite_"
                    "google_search",
                )
            )

            verified["reason"] = (
                candidate.get(
                    "reason",
                    "",
                )
            )

            logger.info(
                "Verified official website: %s",
                verified["url"],
            )

            return verified

    logger.warning(
        "None of the discovered official "
        "website candidates are reachable."
    )

    return None


# ===================================================================
# PAGE FETCHING
# ===================================================================

def fetch_page(
    url: str,
) -> Optional[BeautifulSoup]:
    """Fetch an HTML page."""

    try:

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return None

        content_type = (
            response.headers
            .get(
                "Content-Type",
                "",
            )
            .lower()
        )

        if "text/html" not in content_type:
            return None

        return BeautifulSoup(
            response.text,
            "html.parser",
        )

    except requests.RequestException:

        return None


# ===================================================================
# ANNUAL REPORT PAGE DISCOVERY
# ===================================================================

def find_report_pages(
    website_url: str,
    max_pages: int = MAX_PAGES_TO_CRAWL,
) -> List[str]:
    """
    Crawl ONLY the verified official domain.

    Look for pages related to:

    - Annual Reports
    - Investor Relations
    - Financial Reports
    - Reports & Disclosures
    - Financials
    """

    base_domain = normalize_domain(
        website_url
    )

    queue = deque(
        [clean_url(website_url)]
    )

    visited = set()

    report_pages = []

    while (
        queue
        and len(visited) < max_pages
    ):

        current_url = queue.popleft()

        if current_url in visited:
            continue

        if not is_same_domain(
            current_url,
            base_domain,
        ):
            continue

        visited.add(
            current_url
        )

        logger.info(
            "Crawling official page: %s",
            current_url,
        )

        soup = fetch_page(
            current_url
        )

        if soup is None:
            continue

        page_text = soup.get_text(
            " ",
            strip=True,
        )

        title = ""

        if soup.title:

            title = soup.title.get_text(
                " ",
                strip=True,
            )

        combined_text = (
            f"{title} {page_text}"
        )

        if looks_like_annual_report_text(
            combined_text
        ):

            report_pages.append(
                current_url
            )

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href"
            )

            if not href:
                continue

            absolute_url = urljoin(
                current_url,
                href,
            )

            absolute_url = clean_url(
                absolute_url
            )

            if not is_same_domain(
                absolute_url,
                base_domain,
            ):
                continue

            # PDFs are handled later.
            if looks_like_pdf(
                absolute_url
            ):
                continue

            link_text = link.get_text(
                " ",
                strip=True,
            )

            if looks_like_annual_report_text(
                link_text
            ):

                if absolute_url not in visited:
                    queue.appendleft(
                        absolute_url
                    )

            else:

                if absolute_url not in visited:
                    queue.append(
                        absolute_url
                    )

    # Remove duplicates.
    unique_pages = []

    for page in report_pages:

        if page not in unique_pages:
            unique_pages.append(
                page
            )

    logger.info(
        "Found %d potential annual/investor "
        "report page(s).",
        len(unique_pages),
    )

    return unique_pages


# ===================================================================
# REPORT LINK EXTRACTION
# ===================================================================

def extract_report_links(
    report_pages: List[str],
    official_domain: str,
) -> List[Dict[str, Any]]:
    """
    Extract report links ONLY from
    official-domain pages.
    """

    candidates = []

    for page_url in report_pages:

        logger.info(
            "Extracting report links from: %s",
            page_url,
        )

        soup = fetch_page(
            page_url
        )

        if soup is None:
            continue

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href"
            )

            if not href:
                continue

            absolute_url = urljoin(
                page_url,
                href,
            )

            absolute_url = clean_url(
                absolute_url
            )

            if not is_same_domain(
                absolute_url,
                official_domain,
            ):
                continue

            link_text = link.get_text(
                " ",
                strip=True,
            )

            context = (
                f"{link_text} "
                f"{absolute_url}"
            )

            years = extract_years(
                context
            )

            is_report = (
                looks_like_pdf(
                    absolute_url
                )
                or looks_like_annual_report_text(
                    context
                )
            )

            if not is_report:
                continue

            candidates.append(
                {
                    "url": absolute_url,
                    "title": link_text,
                    "source_page": page_url,
                    "financial_years": years,
                }
            )

    # Deduplicate URLs.
    unique = {}

    for candidate in candidates:

        url = candidate["url"]

        if url not in unique:

            unique[url] = candidate

        else:

            existing_years = (
                unique[url].get(
                    "financial_years",
                    [],
                )
            )

            for year in candidate.get(
                "financial_years",
                [],
            ):

                if year not in existing_years:
                    existing_years.append(
                        year
                    )

    results = list(
        unique.values()
    )

    logger.info(
        "Found %d official report "
        "candidate URL(s).",
        len(results),
    )

    return results[
        :MAX_REPORT_LINKS
    ]


# ===================================================================
# REPORT URL VALIDATION
# ===================================================================

def validate_report_url(
    url: str,
    official_domain: str,
) -> bool:
    """
    Validate that the report URL is:

    - Same official domain
    - Reachable
    - PDF/report content
    """

    if not is_same_domain(
        url,
        official_domain,
    ):
        return False

    try:

        response = session.head(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        # Some servers do not support HEAD.
        if response.status_code >= 400:

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True,
            )

        if response.status_code >= 400:
            return False

        final_url = clean_url(
            response.url
        )

        if not is_same_domain(
            final_url,
            official_domain,
        ):
            return False

        content_type = (
            response.headers
            .get(
                "Content-Type",
                "",
            )
            .lower()
        )

        return (
            "pdf" in content_type
            or looks_like_pdf(
                final_url
            )
        )

    except requests.RequestException:

        return False


# ===================================================================
# REPORT MATCHING
# ===================================================================

def find_report_for_year(
    candidates: List[Dict[str, Any]],
    financial_year: str,
) -> Optional[Dict[str, Any]]:
    """
    Find the best report candidate
    for a specific financial year.
    """

    target = (
        financial_year
        .replace("–", "-")
        .replace("—", "-")
    )

    # First pass:
    # explicitly extracted financial year.
    for candidate in candidates:

        years = candidate.get(
            "financial_years",
            [],
        )

        normalized_years = [
            y.replace("–", "-")
             .replace("—", "-")
            for y in years
        ]

        if target in normalized_years:
            return candidate

    # Second pass:
    # directly search title + URL.
    for candidate in candidates:

        text = (
            f"{candidate.get('title', '')} "
            f"{candidate.get('url', '')}"
        )

        normalized_text = (
            text
            .replace("–", "-")
            .replace("—", "-")
        )

        if target in normalized_text:
            return candidate

    return None


# ===================================================================
# MAIN SERVICE
# ===================================================================

def search_annual_reports(
    company: Dict[str, Any],
    current_financial_year: str,
    previous_financial_year: str,
) -> Dict[str, Any]:
    """
    Search for annual reports through
    the company's official website.

    Gemini:
        Official website identification ONLY.

    Python:
        Website validation
        Same-domain crawling
        Annual report page discovery
        Report URL extraction
        Report URL validation
        Financial-year matching
    """

    company_name = company.get(
        "name",
        "",
    )

    symbol = company.get(
        "symbol",
        "",
    )

    logger.info(
        "Searching annual reports for "
        "%s (%s)...",
        company_name,
        symbol,
    )

    # ---------------------------------------------------------------
    # STEP 1
    # Gemini finds official website.
    # ---------------------------------------------------------------

    website_candidates = (
        find_official_company_websites(
            company
        )
    )

    if not website_candidates:

        return {
            "status": "not_found",
            "company": company_name,
            "symbol": symbol,
            "official_website": None,
            "current_report": None,
            "previous_report": None,
            "candidates": [],
        }

    # ---------------------------------------------------------------
    # STEP 2
    # Python verifies website.
    # ---------------------------------------------------------------

    official_website = (
        find_verified_official_website(
            website_candidates
        )
    )

    if not official_website:

        return {
            "status": "not_found",
            "company": company_name,
            "symbol": symbol,
            "official_website": {
                "candidates": website_candidates,
            },
            "current_report": None,
            "previous_report": None,
            "candidates": [],
        }

    official_url = (
        official_website["url"]
    )

    official_domain = (
        official_website["domain"]
    )

    # ---------------------------------------------------------------
    # STEP 3
    # Crawl ONLY official website.
    # ---------------------------------------------------------------

    report_pages = find_report_pages(
        official_url
    )

    if not report_pages:

        return {
            "status": "not_found",
            "company": company_name,
            "symbol": symbol,
            "official_website": official_website,
            "current_report": None,
            "previous_report": None,
            "candidates": [],
        }

    # ---------------------------------------------------------------
    # STEP 4
    # Extract report URLs.
    # ---------------------------------------------------------------

    report_candidates = (
        extract_report_links(
            report_pages,
            official_domain,
        )
    )

    if not report_candidates:

        return {
            "status": "not_found",
            "company": company_name,
            "symbol": symbol,
            "official_website": official_website,
            "current_report": None,
            "previous_report": None,
            "candidates": [],
        }

    # ---------------------------------------------------------------
    # STEP 5
    # Validate report URLs.
    # ---------------------------------------------------------------

    validated_candidates = []

    for candidate in report_candidates:

        url = candidate["url"]

        logger.info(
            "Validating report URL: %s",
            url,
        )

        if validate_report_url(
            url,
            official_domain,
        ):

            candidate["validated"] = True

            validated_candidates.append(
                candidate
            )

    logger.info(
        "Validated %d report URL(s).",
        len(validated_candidates),
    )

    # ---------------------------------------------------------------
    # STEP 6
    # Match current + previous FY.
    # ---------------------------------------------------------------

    current_report = (
        find_report_for_year(
            validated_candidates,
            current_financial_year,
        )
    )

    previous_report = (
        find_report_for_year(
            validated_candidates,
            previous_financial_year,
        )
    )

    # ---------------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------------

    if (
        current_report
        and previous_report
    ):

        status = "found"

    elif (
        current_report
        or previous_report
    ):

        status = "partial"

    else:

        status = "not_found"

    return {
        "status": status,
        "company": company_name,
        "symbol": symbol,
        "official_website": official_website,
        "current_report": current_report,
        "previous_report": previous_report,
        "candidates": validated_candidates,
    }


# ===================================================================
# CLI TEST
# ===================================================================

if __name__ == "__main__":

    test_company = {
        "symbol": "AONESTEELS",
        "name": "A One Steels India Limited",
        "sector": None,
    }

    result = search_annual_reports(
        test_company,
        current_financial_year="2025-26",
        previous_financial_year="2024-25",
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )