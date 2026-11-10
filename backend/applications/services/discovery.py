import re
import requests
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urlsplit,
    urlunsplit,
)


GOOGLE_NEWS_RSS_URL = (
    "https://news.google.com/rss/search"
)


# Indian financial-year boundaries are calculated from the live system clock.
# Do not hardcode a financial-year label or start/end year.
INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def get_current_financial_year(reference_datetime=None):
    """Return the current Indian FY boundaries in Asia/Kolkata.

    The financial year runs from 1 April through 31 March. The returned end
    date is inclusive and is capped at today's local date for discovery.
    """
    if reference_datetime is None:
        local_now = datetime.now(INDIA_TIMEZONE)
    elif reference_datetime.tzinfo is None:
        local_now = reference_datetime.replace(tzinfo=INDIA_TIMEZONE)
    else:
        local_now = reference_datetime.astimezone(INDIA_TIMEZONE)

    today = local_now.date()
    start_year = today.year if today.month >= 4 else today.year - 1
    start_date = date(start_year, 4, 1)
    financial_year_end = date(start_year + 1, 3, 31)
    effective_end_date = min(today, financial_year_end)
    return start_date, effective_end_date


def _parse_published_date(value):
    """Parse an RSS publication timestamp into an India-local calendar date."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(INDIA_TIMEZONE).date()


def is_in_current_financial_year(published_at, reference_datetime=None):
    """Return True only when a valid publication date falls in the current FY."""
    published_date = _parse_published_date(published_at)
    if published_date is None:
        return False
    start_date, end_date = get_current_financial_year(reference_datetime)
    return start_date <= published_date <= end_date


def build_current_financial_year_query(search_query, reference_datetime=None):
    """Build a Google News query bounded to the current Indian financial year."""
    start_date, end_date = get_current_financial_year(reference_datetime)
    # Google News' before: operator is exclusive, so use the following day.
    exclusive_end = end_date + timedelta(days=1)
    return (
        f"{search_query} after:{start_date.isoformat()} "
        f"before:{exclusive_end.isoformat()}"
    )


DISCOVERY_QUERIES = {

    "investment": {
        "positive": [
            "investment",
            "investing",
            "invested",
            "capital expenditure",
            "capex",
            "funding",
        ],
        "negative": [
            "share investment",
            "stock investment",
            "investor sentiment",
            "share price",
            "stock price",
            "mutual fund",
            "market investment",
            "investment guru",
            "trade idea",
            "target price",
        ],
    },

    "capacity_expansion": {
        "positive": [
            "capacity expansion",
            "capacity increase",
            "increase capacity",
            "additional capacity",
            "production capacity",
            "capacity addition",
            "capacity expansion plans",
        ],
        "negative": [],
    },

    "facility_expansion": {
        "positive": [
            "facility expansion",
            "plant expansion",
            "factory expansion",
            "manufacturing expansion",
            "facility expansion plans",
        ],
        "negative": [],
    },

    "new_facility": {
        "positive": [
            "new facility",
            "new plant",
            "new factory",
            "new manufacturing facility",
            "greenfield",
            "new office",
            "new headquarters",
            "new campus",
            "data centre",
            "data center",
        ],
        "negative": [],
    },

    "hiring": {
        "positive": [
            "hiring",
            "recruitment",
            "recruiting",
            "new employees",
            "workforce expansion",
            "jobs added",
            "new jobs",
            "job openings",
            "recruitment drive",
            "hiring drive",
        ],
        "negative": [
            "layoffs",
            "layoff",
            "job cuts",
            "job cut",
            "job losses",
            "workforce reduction",
            "workforce reductions",
            "downsizing",
            "redundancies",
            "redundancy",
            "employees cut",
            "employees laid off",
            "staff cuts",
            "staff reduction",
        ],
    },

    "workforce_reduction": {
        "positive": [
            "layoffs",
            "layoff",
            "job cuts",
            "job cut",
            "job losses",
            "workforce reduction",
            "workforce reductions",
            "downsizing",
            "redundancies",
            "redundancy",
            "employees cut",
            "employees laid off",
            "staff cuts",
            "staff reduction",
        ],
        "negative": [],
    },

    "leadership_change": {
        "positive": [
            "new CEO",
            "new CFO",
            "new COO",
            "new CTO",
            "new CHRO",
            "appointed CEO",
            "appointed CFO",
            "appointed COO",
            "appointed CTO",
            "appointed director",
            "named CEO",
            "named CFO",
            "named COO",
        ],
        "negative": [],
    },

    "acquisition": {
        "positive": [
            "acquisition",
            "acquire",
            "acquired",
            "takeover",
            "buyout",
        ],
        "negative": [],
    },

    "merger": {
        "positive": [
            "merger",
            "merged",
            "amalgamation",
            "demerger",
        ],
        "negative": [],
    },

    "contract_partnership": {
        "positive": [
            "contract award",
            "wins contract",
            "new contract",
            "partnership",
            "strategic alliance",
            "joint venture",
            "collaboration agreement",
        ],
        "negative": [],
    },

    "financial_results": {
        "positive": [
            "financial results",
            "quarterly results",
            "annual results",
            "earnings results",
        ],
        "negative": [],
    },

    "fundraising": {
        "positive": [
            "fundraising",
            "funding round",
            "raises funding",
            "raises capital",
            "debt funding",
        ],
        "negative": [],
    },

    "product_service": {
        "positive": [
            "launches new product",
            "new product launch",
            "launches new service",
            "new service launch",
        ],
        "negative": [],
    },

    "divestiture": {
        "positive": [
            "divestiture",
            "divests",
            "sells business",
            "sale of business",
            "business sale",
        ],
        "negative": [],
    },

    "regulatory_development": {
        "positive": [
            "regulatory approval",
            "regulatory clearance",
            "environmental clearance",
            "regulatory order",
        ],
        "negative": [],
    },

    "operational_change": {
        "positive": [
            "operational change",
            "operations expansion",
            "production restart",
            "plant shutdown",
            "new business unit",
        ],
        "negative": [],
    },

    "technology_transformation": {
        "positive": [
            "digital transformation",
            "digitalisation",
            "digitization",
            "automation",
            "artificial intelligence",
            "machine learning",
            "technology transformation",
        ],
        "negative": [],
    },

    "sustainability": {
        "positive": [
            "net zero",
            "net-zero",
            "decarbonisation",
            "decarbonization",
            "sustainability",
            "renewable energy",
            "zero emission",
            "zero emissions",
            "clean energy",
        ],
        "negative": [],
    },
}


def normalize_text(text):
    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip().lower()


def build_google_news_rss_url(
    company_name,
    query,
    days=None,
):
    search_query = (
        f'"{company_name}" {query}'
    )

    return build_google_news_query_url(search_query, days)


def build_google_news_query_url(search_query, days=None):
    if days:
        search_query += f" when:{days}d"

    encoded_query = quote(search_query)

    return (
        f"{GOOGLE_NEWS_RSS_URL}"
        f"?q={encoded_query}"
        f"&hl=en-IN"
        f"&gl=IN"
        f"&ceid=IN:en"
    )


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)


def clean_feed_text(value):
    """Strip embedded HTML from RSS text and return readable plain text."""
    if not value:
        return None

    parser = _PlainTextHTMLParser()
    parser.feed(str(value))
    parser.close()
    return " ".join(parser.parts).strip() or None


def extract_xml_text(
    element,
    tag_names,
):
    for child in element.iter():

        local_name = (
            child.tag.split("}")[-1]
        )

        if local_name in tag_names:

            return clean_feed_text("".join(child.itertext()))

    return None


def extract_link(element):

    for child in element:

        local_name = (
            child.tag.split("}")[-1]
        )

        if local_name != "link":
            continue

        if child.text and child.text.strip():
            return child.text.strip()

        href = child.attrib.get("href")

        if href:
            return href.strip()

    return None


def normalize_published_at(value):
    if not value:
        return None
    try:
        published = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return None
    if published.tzinfo is None:
        return published.replace(tzinfo=timezone.utc).isoformat()
    return published.isoformat()


def parse_rss_feed(feed_url):

    response = requests.get(
        feed_url,
        timeout=20,
        headers={
            "User-Agent": (
                "Worksphere-Market-"
                "Intelligence/0.1"
            )
        },
    )

    response.raise_for_status()

    root = ET.fromstring(
        response.content
    )

    entries = []

    for element in root.iter():

        local_name = (
            element.tag.split("}")[-1]
        )

        if local_name not in {
            "item",
            "entry",
        }:
            continue

        title = extract_xml_text(
            element,
            {"title"},
        )

        summary = extract_xml_text(
            element,
            {
                "description",
                "summary",
                "content",
            },
        )

        link = extract_link(element)

        published_at_raw = extract_xml_text(
            element,
            {
                "pubDate",
                "published",
                "updated",
            },
        )

        publisher_element = next(
            (
                child
                for child in element.iter()
                if child.tag.split("}")[-1] == "source"
            ),
            None,
        )
        publisher = (
            " ".join(publisher_element.itertext()).strip()
            if publisher_element is not None
            else None
        )
        publisher_url = (
            publisher_element.attrib.get("url")
            if publisher_element is not None
            else None
        )
        entry_id = extract_xml_text(element, {"guid", "id"})

        if not link:
            continue

        entries.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": normalize_published_at(published_at_raw),
                "published_at_raw": published_at_raw,
                "publisher": publisher,
                "publisher_url": publisher_url,
                "entry_id": entry_id,
            }
        )

    return entries


def detect_event_types(text):

    normalized_text = normalize_text(
        text
    )

    detected_types = []

    for event_type, config in (
        DISCOVERY_QUERIES.items()
    ):

        positive_terms = config.get(
            "positive",
            [],
        )

        negative_terms = config.get(
            "negative",
            [],
        )

        has_positive = any(
            normalize_text(term)
            in normalized_text
            for term in positive_terms
        )

        has_negative = any(
            normalize_text(term)
            in normalized_text
            for term in negative_terms
        )

        if has_positive and not has_negative:

            detected_types.append(
                event_type
            )

    return detected_types


def filter_entries(
    entries,
    company_name,
    event_type,
):

    filtered = []

    company_name_normalized = (
        normalize_text(company_name)
    )

    if event_type not in DISCOVERY_QUERIES:
        return filtered

    for entry in entries:

        title = (
            entry.get("title")
            or ""
        )

        summary = (
            entry.get("summary")
            or ""
        )

        combined_text = (
            f"{title} {summary}"
        )

        normalized_text = normalize_text(
            combined_text
        )

        if (
            company_name_normalized
            not in normalized_text
        ):
            continue

        detected_types = (
            detect_event_types(
                combined_text
            )
        )

        if event_type not in detected_types:
            continue

        entry["event_types"] = (
            detected_types
        )

        filtered.append(entry)

    return filtered


def normalize_url(url):
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""

    host = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port:
        host = f"{host}:{port}"
    if parsed.username or parsed.password:
        return ""

    tracking_keys = {
        "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
        "igshid", "ref_src", "ref_url", "cmpid", "campaignid",
    }
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in tracking_keys
        and not key.casefold().startswith("utm_")
    ]
    query.sort()

    return urlunsplit((
        parsed.scheme.lower(),
        host,
        parsed.path.rstrip("/"),
        urlencode(query, doseq=True),
        "",
    ))


def deduplicate_entries(entries):

    seen = set()
    results = []

    for entry in entries:

        url = entry.get("url")

        if not url:
            continue

        normalized = normalize_url(url)

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)

        entry["normalized_url"] = (
            normalized
        )

        results.append(entry)

    return results


NEWS_SEARCH_TERMS = (
    "investment", "capital expenditure", "expansion", "new facility",
    "new plant", "new office", "contract", "partnership", "acquisition",
    "merger", "leadership", "financial results", "fundraising", "hiring",
    "product launch", "technology transformation", "data center", "capacity",
    "regulatory development",
)


def discover_company_news(company, aliases=None, days=None, max_articles=None):
    """Discover company news published in the current Indian financial year.

    ``days`` is retained for call-site compatibility but is intentionally not
    used as the date boundary. The financial year is always derived from the
    current Asia/Kolkata system date. ``max_articles`` is an optional safety
    cap; by default no candidates are truncated.
    """
    company_name = (company.get("name") or "").strip()
    symbol = (company.get("symbol") or "").strip()
    if not company_name:
        raise ValueError("A registered company name is required.")

    terms = [company_name, symbol, *(aliases or [])]
    unique_terms = []
    seen_terms = set()
    for term in terms:
        term = str(term or "").strip()
        if term and term.casefold() not in seen_terms:
            seen_terms.add(term.casefold())
            unique_terms.append(term)

    company_query = " OR ".join(
        f'"{term.replace(chr(34), "")}"' for term in unique_terms[:8]
    )
    event_query = " OR ".join(f'"{term}"' for term in NEWS_SEARCH_TERMS)
    search_query = f"({company_query}) ({event_query})"
    rss_query = build_current_financial_year_query(search_query)
    rss_url = build_google_news_query_url(rss_query)

    start_date, end_date = get_current_financial_year()
    entries = parse_rss_feed(rss_url)
    articles = []
    duplicate_count = 0
    malformed_count = 0
    missing_date_count = 0
    out_of_period_count = 0
    truncated_count = 0
    eligible_count = 0
    seen_urls = set()

    for entry in entries:
        title = (entry.get("title") or "").strip()
        source_url = (entry.get("url") or "").strip()
        normalized_url = normalize_url(source_url)
        if not title or not normalized_url:
            malformed_count += 1
            continue

        published_date = _parse_published_date(entry.get("published_at"))
        if published_date is None:
            missing_date_count += 1
            continue
        if not (start_date <= published_date <= end_date):
            out_of_period_count += 1
            continue

        if normalized_url in seen_urls:
            duplicate_count += 1
            continue
        seen_urls.add(normalized_url)
        eligible_count += 1

        if max_articles is not None and len(articles) >= max_articles:
            truncated_count += 1
            continue

        article_text = f"{title} {entry.get('summary') or ''}"
        articles.append({
            **entry,
            "url": source_url,
            "normalized_url": normalized_url,
            "event_types": detect_event_types(article_text),
            "discovery_query": "company plus business-event terms",
            "discovery_source": "google_news_rss",
            "rss_url": rss_url,
            "financial_year_start": start_date.isoformat(),
            "financial_year_end": end_date.isoformat(),
        })

    return {
        "articles": articles,
        "entry_count": len(entries),
        "eligible_count": eligible_count,
        "duplicate_count": duplicate_count,
        "malformed_count": malformed_count,
        "missing_date_count": missing_date_count,
        "out_of_period_count": out_of_period_count,
        "truncated_count": truncated_count,
        "metadata": {
            "provider": "google_news_rss",
            "financial_year_start": start_date.isoformat(),
            "financial_year_end": end_date.isoformat(),
            "financial_year_timezone": "Asia/Kolkata",
            "lookback_days_ignored": days,
            "entry_count": len(entries),
            "eligible_count": eligible_count,
            "duplicate_count": duplicate_count,
            "malformed_count": malformed_count,
            "missing_date_count": missing_date_count,
            "out_of_period_count": out_of_period_count,
            "truncated_count": truncated_count,
        },
    }


def discover_from_rss(
    company_name,
    event_types=None,
    days=7,
):

    if not company_name:
        raise ValueError(
            "company_name is required."
        )

    if event_types is None:

        event_types = list(
            DISCOVERY_QUERIES.keys()
        )

    discovered = []

    for event_type in event_types:

        if event_type not in DISCOVERY_QUERIES:
            continue

        queries = (
            DISCOVERY_QUERIES[
                event_type
            ].get(
                "positive",
                [],
            )
        )

        for query in queries:

            rss_url = (
                build_google_news_rss_url(
                    company_name,
                    query,
                    days,
                )
            )

            try:

                entries = (
                    parse_rss_feed(
                        rss_url
                    )
                )

                filtered = (
                    filter_entries(
                        entries,
                        company_name,
                        event_type,
                    )
                )
                filtered = [
                    entry for entry in filtered
                    if is_in_current_financial_year(entry.get("published_at"))
                ]

                for entry in filtered:

                    entry[
                        "discovery_query"
                    ] = query

                    entry[
                        "discovery_source"
                    ] = "google_news_rss"

                    entry[
                        "rss_url"
                    ] = rss_url

                    discovered.append(
                        entry
                    )

            except requests.RequestException as error:

                print(
                    "[Discovery] RSS request "
                    f"failed: {rss_url}"
                )

                print(
                    f"[Discovery] Error: {error}"
                )

            except ET.ParseError as error:

                print(
                    "[Discovery] Invalid RSS/XML: "
                    f"{rss_url}"
                )

                print(
                    f"[Discovery] Error: {error}"
                )

    return deduplicate_entries(
        discovered
    )


if __name__ == "__main__":

    company = input(
        "\nEnter company name: "
    ).strip()

    if not company:
        print(
            "Company name is required."
        )
        exit()

    days_input = input(
        "Search articles from last "
        "how many days? [30]: "
    ).strip()

    days = (
        int(days_input)
        if days_input
        else 30
    )

    print(
        f"\nSearching RSS for: {company}"
    )

    fy_start, fy_end = get_current_financial_year()
    print(f"Financial year window: {fy_start} to {fy_end} (Asia/Kolkata)\n")

    results = discover_from_rss(
        company_name=company,
        event_types=[
            "investment",
            "capacity_expansion",
            "facility_expansion",
            "new_facility",
            "hiring",
            "workforce_reduction",
            "leadership_change",
            "acquisition",
            "merger",
            "technology_transformation",
            "sustainability",
        ],
        days=days,
    )

    print(
        f"Found {len(results)} "
        "candidate articles.\n"
    )

    for index, result in enumerate(
        results,
        start=1,
    ):

        print(
            f"{index}. {result['title']}"
        )

        print(
            f"   URL: {result['url']}"
        )

        print(
            "   Event: "
            f"{', '.join(result['event_types'])}"
        )

        print(
            "   Query: "
            f"{result['discovery_query']}"
        )

        print()
