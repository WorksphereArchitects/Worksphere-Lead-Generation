"""WorkSphere financial Gemini extraction service.

This service is used ONLY for companies that are insufficient in the primary
yfinance financial pre-filter. It extracts annual revenue from current and
previous annual-report documents. It does not qualify companies and does not
write to Supabase.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import deque
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.5-flash-lite"
MAX_FLASH_ATTEMPTS = 3
INITIAL_BACKOFF_SECONDS = 4.0
MAX_BACKOFF_SECONDS = 30.0
MAX_REQUESTS_PER_MINUTE = 5
MAX_INPUT_TOKENS_PER_REQUEST = 200_000
MAX_INPUT_TOKENS_PER_MINUTE = 250_000
FINANCIAL_CONTEXT_TOKENS_TARGET = 20_000
MAX_FINANCIAL_CANDIDATES = 40
FINANCIAL_CONTEXT_RADIUS = 4
MAX_OUTPUT_TOKENS = 16_384

FINANCIAL_KEYWORD_PATTERNS = [
    r"\bfinancial performance\b",
    r"\brevenue from sale of products and services\b",
    r"\brevenue from operations\b",
    r"\btotal revenue\b",
    r"\btotal income\b",
    r"\brevenue\b",
    r"\bsales\b",
    r"\byear[- ]over[- ]year\b",
    r"\byoy\b",
    r"\bgrowth\b",
    r"\bprevious year\b",
    r"\bcorresponding previous period\b",
]

LAST_MODEL_RUN_METADATA: dict[str, Any] = {}

class GeminiRateLimiter:
    """
    Conservative sliding-window limiter.

    Guarantees:
      - no more than 5 requests in any 60-second window
      - estimated input tokens stay below 250k in any 60-second window
    """

    def __init__(
        self,
        max_requests: int = MAX_REQUESTS_PER_MINUTE,
        max_input_tokens: int = MAX_INPUT_TOKENS_PER_MINUTE,
    ):
        self.max_requests = max_requests
        self.max_input_tokens = max_input_tokens
        self.calls: deque[float] = deque()
        self.tokens: deque[tuple[float, int]] = deque()

    def _purge(self) -> None:
        cutoff = time.monotonic() - 60

        while self.calls and self.calls[0] <= cutoff:
            self.calls.popleft()

        while self.tokens and self.tokens[0][0] <= cutoff:
            self.tokens.popleft()

    def wait_for_capacity(self, estimated_input_tokens: int) -> None:
        if estimated_input_tokens > MAX_INPUT_TOKENS_PER_REQUEST:
            raise ValueError(
                f"Request is too large: ~{estimated_input_tokens:,} input tokens. "
                f"Maximum allowed by this POC is "
                f"{MAX_INPUT_TOKENS_PER_REQUEST:,}."
            )

        while True:
            self._purge()

            request_count = len(self.calls)
            token_count = sum(tokens for _, tokens in self.tokens)

            request_ok = request_count < self.max_requests
            token_ok = (
                token_count + estimated_input_tokens
                <= self.max_input_tokens
            )

            if request_ok and token_ok:
                return

            waits = []

            if self.calls:
                waits.append(
                    max(0.0, 60 - (time.monotonic() - self.calls[0]))
                )

            if self.tokens:
                waits.append(
                    max(0.0, 60 - (time.monotonic() - self.tokens[0][0]))
                )

            sleep_for = max(waits, default=1.0)
            print(
                f"Rate-limit guard: sleeping {sleep_for:.1f}s "
                f"(requests={request_count}/5, "
                f"input_tokens={token_count:,}/250,000)"
            )
            time.sleep(sleep_for)

    def record(self, estimated_input_tokens: int) -> None:
        now = time.monotonic()
        self.calls.append(now)
        self.tokens.append((now, estimated_input_tokens))


def estimate_tokens(text: str) -> int:
    """
    Conservative approximation for rate-limit planning.

    We intentionally over-estimate slightly rather than depending on
    another tokenizer/API call just to calculate usage.
    """
    if not text:
        return 0

    # Rough English/document estimate.
    return max(1, int(len(text) / 3.5))



def _build_financial_candidates(
    raw_text: str,
    source_sentences: list[str],
    start_candidate_id: int,
) -> tuple[str, dict[int, dict[str, Any]], dict[str, int]]:
    """Build a targeted retrieval context for annual financial metrics.

    This retrieval path is intentionally independent of WorkSphere event
    retrieval. Revenue and growth frequently appear in a financial-performance
    page or financial-statement table and may not contain event vocabulary.

    Candidate IDs continue the same registry used by business-event retrieval,
    so Gemini can cite financial source candidates in the same response.
    """
    if not source_sentences:
        return "", {}, {
            "financial_candidates": 0,
            "financial_context_chars": 0,
            "financial_context_tokens": 0,
        }

    compiled_patterns = [
        re.compile(pattern, flags=re.IGNORECASE)
        for pattern in FINANCIAL_KEYWORD_PATTERNS
    ]

    scored_indexes: list[tuple[int, int]] = []

    for index, sentence in enumerate(source_sentences):
        score = 0
        lowered = sentence.lower()

        for pattern in compiled_patterns:
            if pattern.search(lowered):
                score += 1

        # Give stronger weight to phrases that are much more likely to identify
        # the annual financial-performance section rather than incidental uses
        # of words such as "growth" or "sales".
        if re.search(
            r"financial performance|revenue from (sale of products and services|operations)|total revenue|total income",
            lowered,
            flags=re.IGNORECASE,
        ):
            score += 5

        # Revenue numbers and percentages together are especially useful for
        # the exact metric we need.
        if re.search(r"revenue|sales", lowered, flags=re.IGNORECASE) and re.search(
            r"%|crore|cr\.?|million|billion|growth",
            lowered,
            flags=re.IGNORECASE,
        ):
            score += 3

        if score > 0:
            scored_indexes.append((score, index))

    # Highest-confidence financial locations first. Keep source order later so
    # Gemini sees coherent report context rather than a random ranking.
    scored_indexes.sort(key=lambda item: (-item[0], item[1]))

    selected_centres: list[int] = []
    for _, index in scored_indexes:
        if any(abs(index - existing) <= FINANCIAL_CONTEXT_RADIUS for existing in selected_centres):
            continue

        selected_centres.append(index)
        if len(selected_centres) >= MAX_FINANCIAL_CANDIDATES:
            break

    selected_centres.sort()

    registry: dict[int, dict[str, Any]] = {}
    context_parts: list[str] = []
    next_id = start_candidate_id

    for centre in selected_centres:
        start_index = max(0, centre - FINANCIAL_CONTEXT_RADIUS)
        end_index = min(
            len(source_sentences),
            centre + FINANCIAL_CONTEXT_RADIUS + 1,
        )

        window_sentences = source_sentences[start_index:end_index]
        financial_excerpt = " ".join(window_sentences).strip()

        if not financial_excerpt:
            continue

        candidate_id = next_id
        next_id += 1

        packet = (
            f"Financial source context.\n"
            f"Source sentence index: {centre + 1}\n"
            f"Financial context:\n{financial_excerpt}"
        )

        registry[candidate_id] = {
            "candidate_id": candidate_id,
            "source_sentence_index": centre,
            "source_sentence": source_sentences[centre],
            "source_sentence_indexes": list(range(start_index, end_index)),
            "source_excerpt": financial_excerpt,
            "packet": packet,
            "candidate_kind": "financial",
        }

        packet_with_id = (
            f"[SOURCE_CANDIDATE_ID: {candidate_id}]\n{packet}"
        )

        trial = "\n---\n".join(context_parts + [packet_with_id])
        if estimate_tokens(trial) > FINANCIAL_CONTEXT_TOKENS_TARGET:
            break

        context_parts.append(packet_with_id)

    context = "\n---\n".join(context_parts)
    stats = {
        "financial_candidates": len(registry),
        "financial_context_chars": len(context),
        "financial_context_tokens": estimate_tokens(context),
    }

    print(
        "Financial retrieval context: "
        f"{stats['financial_context_chars']:,} chars "
        f"(~{stats['financial_context_tokens']:,} estimated tokens), "
        f"{stats['financial_candidates']} candidates"
    )

    return context, registry, stats


FINANCIAL_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "available": {"type": "BOOLEAN"},
        "financial_year": {"type": "STRING", "nullable": True},
        "revenue": {"type": "NUMBER", "nullable": True},
        "source_candidate_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "page": {"type": "INTEGER", "nullable": True},
    },
    "required": ["available", "financial_year", "revenue", "source_candidate_ids", "page"],
}

SYSTEM_INSTRUCTION = """
You are WorkSphere's financial extraction layer.

Your ONLY task is to extract the annual company-level revenue from the supplied
annual-report financial evidence. You are NOT deciding whether the company is
qualified. You are NOT calculating qualification.

Rules:
1. Use only the supplied source context.
2. Prefer consolidated annual figures when both consolidated and standalone
   figures are supplied.
3. Extract the annual company-level revenue for the report year represented by
   this document.
4. Prefer Revenue from sale of products and services, Revenue from operations,
   Total Revenue, Revenue, Sales, or the report's equivalent annual metric.
5. Do not use quarterly, monthly, TTM, segment-only, or unrelated values.
6. Do not estimate or infer a missing revenue value.
7. The revenue must be the figure explicitly supported by the supplied evidence.
8. Return the SOURCE_CANDIDATE_ID values that directly support the revenue.
9. If reliable annual revenue cannot be identified, return available=false,
   revenue=null, and an empty source_candidate_ids array.
10. Return ONLY the JSON object matching the supplied schema.
"""

class GeminiJSONParseError(RuntimeError):
    pass

def _is_503_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return "503" in message and ("UNAVAILABLE" in message or "HIGH DEMAND" in message or "CURRENTLY EXPERIENCING" in message)

def _is_429_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return "429" in message or "RESOURCE_EXHAUSTED" in message or "TOO MANY REQUESTS" in message

def _extract_provider_retry_delay(exc: Exception) -> float | None:
    message = str(exc)
    for pattern in [r"retryDelay[\"']?\s*[:=]\s*[\"']?([0-9]+(?:\.[0-9]+)?)s", r"retryDelay[^0-9]*([0-9]+(?:\.[0-9]+)?)s"]:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None

def _quota_retry_delay(exc: Exception) -> float:
    provider_delay = _extract_provider_retry_delay(exc)
    if provider_delay is not None:
        return max(1.0, provider_delay + random.uniform(0.5, 2.0))
    return 20.0 + random.uniform(0.5, 2.0)

def _backoff_delay(attempt_number: int) -> float:
    base = min(INITIAL_BACKOFF_SECONDS * (2 ** max(0, attempt_number - 1)), MAX_BACKOFF_SECONDS)
    if attempt_number == 1:
        return base
    return min(base + random.uniform(0.0, base * 0.5), MAX_BACKOFF_SECONDS)

def _get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")
    return genai.Client(api_key=api_key)

def _parse_response(response) -> dict[str, Any]:
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        finish_reason = None
        try:
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
        except Exception:
            pass
        raise GeminiJSONParseError(
            f"Gemini returned invalid/incomplete JSON; finish_reason={finish_reason!r}; chars={len(text)}"
        ) from exc

def _resolve_financial_output(result: dict[str, Any], registry: dict[int, dict[str, Any]], report_year: Any) -> dict[str, Any]:
    raw = dict(result or {})
    revenue = raw.get("revenue")
    try:
        revenue = float(revenue) if revenue is not None and revenue != "" else None
    except (TypeError, ValueError):
        revenue = None

    ids = []
    for value in raw.get("source_candidate_ids") or []:
        try:
            cid = int(value)
        except (TypeError, ValueError):
            continue
        if cid in registry and cid not in ids:
            ids.append(cid)
    ids.sort(key=lambda cid: (registry[cid]["source_sentence_index"], cid))

    excerpts = []
    sentence_indexes = []
    for cid in ids:
        item = registry[cid]
        for idx in item.get("source_sentence_indexes", [item["source_sentence_index"]]):
            if idx not in sentence_indexes:
                sentence_indexes.append(idx)
        excerpt = item.get("source_excerpt") or item.get("source_sentence")
        if excerpt and excerpt not in excerpts:
            excerpts.append(excerpt)

    return {
        "available": bool(raw.get("available") and revenue is not None and ids),
        "financial_year": raw.get("financial_year") or report_year,
        "revenue": revenue,
        "source_candidate_ids": ids,
        "source_sentence_indexes": sorted(sentence_indexes),
        "excerpt": " ".join(excerpts),
        "page": raw.get("page"),
        "source_resolution_status": "resolved" if revenue is not None and ids and excerpts else "unresolved",
    }

def extract_report_revenue(
    raw_text: str,
    *,
    company_name: str,
    financial_year: str | None,
    report_label: str,
    client=None,
    limiter: GeminiRateLimiter | None = None,
) -> dict[str, Any]:
    """Extract revenue from one annual report."""
    from applications.services.evidence_extractor import split_into_sentences

    sentences = split_into_sentences(raw_text)
    context, registry, retrieval_stats = _build_financial_candidates(
        raw_text=raw_text,
        source_sentences=sentences,
        start_candidate_id=1,
    )

    if not context:
        return {
            "available": False,
            "financial_year": financial_year,
            "revenue": None,
            "source_candidate_ids": [],
            "source_sentence_indexes": [],
            "excerpt": "",
            "page": None,
            "source_resolution_status": "unresolved",
            "report_label": report_label,
            "retrieval_stats": retrieval_stats,
        }

    client = client or _get_client()
    limiter = limiter or GeminiRateLimiter()

    prompt = f"""
Extract the annual revenue from this annual report.

Company: {company_name}
Report year: {financial_year or 'Unknown'}
Report: {report_label}

Return ONLY the JSON object matching the supplied schema.

SOURCE CONTEXT:
{context}
"""

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=FINANCIAL_RESPONSE_SCHEMA,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    def generate(model: str):
        request_tokens = estimate_tokens(SYSTEM_INSTRUCTION + prompt)
        limiter.wait_for_capacity(request_tokens)
        limiter.record(request_tokens)
        return client.models.generate_content(model=model, contents=prompt, config=config)

    fallback_reason = None
    flash_attempts = 0
    for attempt in range(1, MAX_FLASH_ATTEMPTS + 1):
        flash_attempts = attempt
        try:
            response = generate(MODEL)
            result = _parse_response(response)
            LAST_MODEL_RUN_METADATA.clear()
            LAST_MODEL_RUN_METADATA.update({
                "model_attempted": MODEL, "model_used": MODEL,
                "flash_attempts": flash_attempts, "fallback_used": False,
                "fallback_reason": None,
            })
            resolved = _resolve_financial_output(result, registry, financial_year)
            resolved["report_label"] = report_label
            resolved["retrieval_stats"] = retrieval_stats
            return resolved
        except Exception as exc:
            if _is_503_error(exc):
                if attempt < MAX_FLASH_ATTEMPTS:
                    time.sleep(_backoff_delay(attempt))
                    continue
                fallback_reason = "503_UNAVAILABLE"
                break
            if _is_429_error(exc):
                if attempt < MAX_FLASH_ATTEMPTS:
                    time.sleep(_quota_retry_delay(exc))
                    continue
                fallback_reason = "429_RESOURCE_EXHAUSTED"
                break
            raise

    response = generate(FALLBACK_MODEL)
    result = _parse_response(response)
    LAST_MODEL_RUN_METADATA.clear()
    LAST_MODEL_RUN_METADATA.update({
        "model_attempted": MODEL, "model_used": FALLBACK_MODEL,
        "flash_attempts": flash_attempts, "fallback_used": True,
        "fallback_reason": fallback_reason,
    })
    resolved = _resolve_financial_output(result, registry, financial_year)
    resolved["report_label"] = report_label
    resolved["retrieval_stats"] = retrieval_stats
    return resolved

def extract_two_annual_report_revenues(
    current_report_text: str,
    previous_report_text: str,
    *,
    company_name: str,
    current_financial_year: str | None,
    previous_financial_year: str | None,
    client=None,
    limiter: GeminiRateLimiter | None = None,
) -> dict[str, Any]:
    """Extract revenue independently from current and previous annual reports."""
    shared_client = client or _get_client()
    shared_limiter = limiter or GeminiRateLimiter()

    current = extract_report_revenue(
        current_report_text, company_name=company_name,
        financial_year=current_financial_year, report_label="current_report",
        client=shared_client, limiter=shared_limiter,
    )
    previous = extract_report_revenue(
        previous_report_text, company_name=company_name,
        financial_year=previous_financial_year, report_label="previous_report",
        client=shared_client, limiter=shared_limiter,
    )

    return {"current": current, "previous": previous, "model_metadata": dict(LAST_MODEL_RUN_METADATA)}
