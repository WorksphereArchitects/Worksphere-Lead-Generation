# import hashlib
# import requests
# from bs4 import BeautifulSoup

# def fetch_url(url):
#     response = requests.get(url, timeout=20, headers={
#         "user-Agent": "Worksphere-Market-Intelligence/0.1"
#     })

#     response.raise_for_status()
#     content_type = response.headers.get("Content-Type", "")
#     if "text/html" not in content_type.lower():
#         raise ValueError(f"Unsupported content type: {content_type}")

#     soup = BeautifulSoup(response.text, "html.parser")

#     for element in soup(["scripts", "style", "noscript"]):
#         element.decompose()

#     title = soup.title.get_text(strip=True) if soup.title else None

#     raw_text = soup.get_text(
#         separator="\n",
#         strip=True
#     )

#     content_hash = hashlib.sha256(
#         raw_text.encode("utf-8")
#     ).hexdigest()

#     canonical_url = response.url

#     return {
#         "url": url,
#         "canonical_url": canonical_url,
#         "title": title,
#         "content_type": content_type,
#         "http_status": response.status_code,
#         "content_hash": content_hash,
#         "raw_text": raw_text,
#         "metadata_json": {
#             "content_length": len(response.content)
#         }
#     }

import hashlib
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


def fetch_url(url):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "user-Agent": "Worksphere-Market-Intelligence/0.1"
        }
    )

    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()

    # ============================================================
    # PDF
    # ============================================================

    if "application/pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):

        reader = PdfReader(BytesIO(response.content))

        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)

        raw_text = "\n\n".join(pages).strip()

        content_hash = hashlib.sha256(
            raw_text.encode("utf-8")
        ).hexdigest()

        return {
            "url": url,
            "canonical_url": response.url,
            "title": None,
            "content_type": content_type or "application/pdf",
            "http_status": response.status_code,
            "content_hash": content_hash,
            "raw_text": raw_text,
            "metadata_json": {
                "content_length": len(response.content),
                "document_type": "pdf",
                "page_count": len(reader.pages)
            }
        }

    # ============================================================
    # HTML
    # ============================================================

    if "text/html" in content_type:

        soup = BeautifulSoup(response.text, "html.parser")

        for element in soup(["scripts", "style", "noscript"]):
            element.decompose()

        title = (
            soup.title.get_text(strip=True)
            if soup.title
            else None
        )

        raw_text = soup.get_text(
            separator="\n",
            strip=True
        )

        content_hash = hashlib.sha256(
            raw_text.encode("utf-8")
        ).hexdigest()

        return {
            "url": url,
            "canonical_url": response.url,
            "title": title,
            "content_type": content_type,
            "http_status": response.status_code,
            "content_hash": content_hash,
            "raw_text": raw_text,
            "metadata_json": {
                "content_length": len(response.content),
                "document_type": "html"
            }
        }

    # ============================================================
    # Unsupported
    # ============================================================

    raise ValueError(
        f"Unsupported content type: {content_type}"
    )