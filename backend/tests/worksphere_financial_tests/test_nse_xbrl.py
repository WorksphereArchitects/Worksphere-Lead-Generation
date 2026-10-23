import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import xml.etree.ElementTree as ET


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

CSV_FILE = BASE_DIR / "financial_test_output" / "nsepython_annual_results.csv"

OUTPUT_DIR = BASE_DIR / "financial_test_output"
OUTPUT_DIR.mkdir(exist_ok=True)

RAW_XML_FILE = OUTPUT_DIR / "asianpaint_xbrl_raw.xml"
CANDIDATES_FILE = OUTPUT_DIR / "asianpaint_xbrl_revenue_candidates.csv"

TARGET_SYMBOL = "SCHAEFFLER"

# ---------------------------------------------------------
# HTTP SESSION
# ---------------------------------------------------------

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml,text/xml,text/html,*/*",
    "Referer": "https://www.nseindia.com/",
})


# ---------------------------------------------------------
# LOAD NSEPYTHON CSV
# ---------------------------------------------------------

print("=" * 80)
print("NSEPYTHON → XBRL REVENUE TEST")
print("=" * 80)

print(f"\nReading CSV:")
print(CSV_FILE)

if not CSV_FILE.exists():
    raise FileNotFoundError(
        f"CSV not found: {CSV_FILE}"
    )

df = pd.read_csv(CSV_FILE)

print(f"\nTotal rows: {len(df)}")
print(f"Columns: {list(df.columns)}")


# ---------------------------------------------------------
# CHECK REQUIRED COLUMNS
# ---------------------------------------------------------

required_columns = [
    "symbol",
    "companyName",
    "financialYear",
    "consolidated",
    "audited",
    "xbrl",
]

missing = [
    column
    for column in required_columns
    if column not in df.columns
]

if missing:
    raise ValueError(
        f"Missing required columns: {missing}"
    )


# ---------------------------------------------------------
# FIND TARGET COMPANY
# ---------------------------------------------------------

company_df = df[
    df["symbol"]
    .astype(str)
    .str.upper()
    .eq(TARGET_SYMBOL)
].copy()

print(f"\nRows for {TARGET_SYMBOL}: {len(company_df)}")

if company_df.empty:
    print("\nAvailable symbols:")
    print(df["symbol"].dropna().astype(str).head(50).tolist())
    raise ValueError(
        f"{TARGET_SYMBOL} was not found in the CSV."
    )


# ---------------------------------------------------------
# SHOW TARGET COMPANY RESULTS
# ---------------------------------------------------------

print("\nTarget company annual results:")

display_columns = [
    "symbol",
    "companyName",
    "financialYear",
    "period",
    "audited",
    "consolidated",
    "xbrl",
]

available_display_columns = [
    column
    for column in display_columns
    if column in company_df.columns
]

print(
    company_df[available_display_columns]
    .to_string(index=False)
)


# ---------------------------------------------------------
# SELECT CONSOLIDATED RESULT
# ---------------------------------------------------------

def is_consolidated(value):
    value = str(value).strip().lower()

    return (
        value == "consolidated"
        or value == "yes"
        or value == "true"
        or value == "1"
    )


consolidated_df = company_df[
    company_df["consolidated"].apply(is_consolidated)
].copy()


if consolidated_df.empty:
    raise ValueError(
        f"No consolidated result found for {TARGET_SYMBOL}."
    )


# ---------------------------------------------------------
# SELECT LATEST ANNUAL RESULT
# ---------------------------------------------------------

# Try to sort by filing date if available.
if "filingDate" in consolidated_df.columns:

    consolidated_df["filingDate_parsed"] = pd.to_datetime(
        consolidated_df["filingDate"],
        errors="coerce"
    )

    consolidated_df = consolidated_df.sort_values(
        "filingDate_parsed",
        ascending=False
    )


selected = consolidated_df.iloc[0]

xbrl_url = str(selected["xbrl"]).strip()

financial_year = str(
    selected["financialYear"]
).strip()

print("\n" + "-" * 80)
print("SELECTED NSE RESULT")
print("-" * 80)

print(f"Symbol:         {selected['symbol']}")
print(f"Company:        {selected['companyName']}")
print(f"Financial year: {financial_year}")
print(f"Audited:        {selected['audited']}")
print(f"Consolidated:   {selected['consolidated']}")
print(f"XBRL URL:       {xbrl_url}")


# ---------------------------------------------------------
# VALIDATE XBRL URL
# ---------------------------------------------------------

if not xbrl_url or xbrl_url.lower() == "nan":
    raise ValueError(
        "Selected NSE result does not contain an XBRL URL."
    )

if not xbrl_url.startswith("http"):
    raise ValueError(
        f"Invalid XBRL URL: {xbrl_url}"
    )


# ---------------------------------------------------------
# DOWNLOAD XBRL
# ---------------------------------------------------------

print("\n" + "-" * 80)
print("DOWNLOADING XBRL")
print("-" * 80)

print(f"GET {xbrl_url}")

response = session.get(
    xbrl_url,
    timeout=30
)

print(f"HTTP status: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type')}")
print(f"Content length: {len(response.content):,} bytes")

response.raise_for_status()


# ---------------------------------------------------------
# SAVE RAW XML
# ---------------------------------------------------------

RAW_XML_FILE.write_bytes(response.content)

print(f"\nRaw XBRL saved to:")
print(RAW_XML_FILE)


# ---------------------------------------------------------
# PARSE XML
# ---------------------------------------------------------

print("\n" + "-" * 80)
print("PARSING XBRL")
print("-" * 80)

try:
    root = ET.fromstring(response.content)
except ET.ParseError as error:
    print("\nXML parsing failed.")

    print("\nFirst 2,000 characters:")
    print(response.text[:2000])

    raise error


print(f"Root tag: {root.tag}")


# ---------------------------------------------------------
# INSPECT TAGS
# ---------------------------------------------------------

all_elements = list(root.iter())

print(f"Total XML elements: {len(all_elements)}")


tags = {}

for element in all_elements:

    tag = element.tag

    if "}" in tag:
        tag = tag.split("}", 1)[1]

    tags[tag] = tags.get(tag, 0) + 1


print("\nMost common XBRL tags:")

for tag, count in sorted(
    tags.items(),
    key=lambda item: item[1],
    reverse=True
)[:100]:

    print(f"{count:5}  {tag}")


# ---------------------------------------------------------
# SEARCH REVENUE-RELATED TAGS
# ---------------------------------------------------------

print("\n" + "-" * 80)
print("REVENUE-RELATED XBRL TAGS")
print("-" * 80)

revenue_keywords = [
    "revenue",
    "income",
    "sales",
    "turnover",
    "operation",
]


revenue_tags = []

for tag in tags:

    tag_lower = tag.lower()

    if any(
        keyword in tag_lower
        for keyword in revenue_keywords
    ):
        revenue_tags.append(tag)


for tag in sorted(revenue_tags):

    print(tag)


# ---------------------------------------------------------
# EXTRACT REVENUE CANDIDATES
# ---------------------------------------------------------

print("\n" + "-" * 80)
print("REVENUE CANDIDATES")
print("-" * 80)

candidates = []


for element in all_elements:

    original_tag = element.tag

    if "}" in original_tag:
        clean_tag = original_tag.split("}", 1)[1]
    else:
        clean_tag = original_tag

    tag_lower = clean_tag.lower()

    if not any(
        keyword in tag_lower
        for keyword in revenue_keywords
    ):
        continue

    text = (element.text or "").strip()

    if not text:
        continue

    # Ignore extremely long text blocks.
    if len(text) > 500:
        continue

    attributes = {}

    for key, value in element.attrib.items():

        if "}" in key:
            key = key.split("}", 1)[1]

        attributes[key] = value

    candidates.append({
        "tag": clean_tag,
        "value": text,
        "attributes": str(attributes),
    })


candidates_df = pd.DataFrame(candidates)


if candidates_df.empty:

    print(
        "\nNo revenue-related values were found using "
        "the initial keyword search."
    )

else:

    print(
        f"\nFound {len(candidates_df)} "
        "revenue-related candidates."
    )

    print(
        candidates_df.head(100).to_string(index=False)
    )

    candidates_df.to_csv(
        CANDIDATES_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(
        f"\nCandidates saved to:\n"
        f"{CANDIDATES_FILE}"
    )


# ---------------------------------------------------------
# PRINT SAMPLE RAW XML
# ---------------------------------------------------------

print("\n" + "-" * 80)
print("RAW XML SAMPLE")
print("-" * 80)

print(response.text[:5000])

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)