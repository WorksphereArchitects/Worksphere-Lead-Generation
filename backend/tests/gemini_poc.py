"""
WorkSphere Gemini POC
---------------------
Simple reasoning-layer test for annual reports.

Flow:
    annual_reports.py
        -> PDF download / text extraction
        -> existing evidence_extractor retrieval
        -> compact evidence packets
        -> Gemini structured reasoning
        -> source-candidate resolution
        -> exact source evidence

Gemini selects retrieved source candidates; the application resolves the exact
source wording from the annual report. No deterministic evidence validator is used.
This file does NOT write to PostgreSQL.

Rate-limit safety:
    - 5 requests/minute maximum (below a 10 RPM limit)
    - 200,000 estimated input tokens/request safety ceiling
    - 250,000 estimated input tokens/minute provider ceiling
    - up to ~190,000 tokens of relevant retrieved report context
    - normal single-request API, no Batch API

For an already-downloaded annual report:
    python gemini_poc.py --file storage/reports/your_report.pdf

For the annual_reports.py download flow:
    python gemini_poc.py --company 3PLAND

Environment:
    GEMINI_API_KEY=your_key
"""

from __future__ import annotations

import argparse
import json
import random
import time
import re
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from google import genai
from google.genai import types

# Reuse the CURRENT annual report ingestion pipeline.
from applications.services.annual_report_ingestion import (
    DOWNLOAD_FOLDER,
    extract_report_text,
    load_report_from_company as ingest_report_from_company,
)

from applications.services.companies import (
    get_company_by_symbol,
)

# Reuse the CURRENT local retrieval/extraction engine.
from applications.services.evidence_extractor import (
    extract_evidence_context,
    split_into_sentences,
)
from applications.services.evidence_service import (
    create_evidence_batch,
)

from applications.services.processing_runs import (
    create_processing_run,
    complete_processing_run,
    fail_processing_run,
)

from applications.services.annual_reports import (
    mark_report_processed,
    mark_report_failed,
)

# ============================================================
# GEMINI / RATE LIMIT CONFIG
# ============================================================

MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.5-flash-lite"

LAST_MODEL_RUN_METADATA: dict[str, Any] = {}

# Retry policy:
#   1) Flash attempt
#   2) 503 -> exponential backoff
#   3) 503 -> jittered backoff
#   4) 503 -> fall back to Flash-Lite
MAX_FLASH_ATTEMPTS = 3
INITIAL_BACKOFF_SECONDS = 4.0
MAX_BACKOFF_SECONDS = 30.0

# User's stated provider limit is 10 RPM.
# We deliberately operate at half that limit.
MAX_REQUESTS_PER_MINUTE = 5

# Conservative safety margins below the stated limits.
MAX_INPUT_TOKENS_PER_REQUEST = 200_000
MAX_INPUT_TOKENS_PER_MINUTE = 250_000

# Give Gemini substantially more relevant context while leaving room for the
# system instruction and prompt wrapper under the 200k request safety ceiling.
MAX_CONTEXT_TOKENS_TARGET = 190_000

# Retrieval expansion.
MAX_CANDIDATES = 350
MAX_EXCERPT_CHARS = 3000

# ~800k chars allows the expanded retriever to approach ~190k estimated tokens
# under the conservative 3.5 chars/token estimate.
MAX_TOTAL_CONTEXT_CHARS = 800_000

# Use Gemini's full supported output ceiling. This is a maximum, not a target.
# Do not impose an arbitrary signal-count limit.
MAX_OUTPUT_TOKENS = 65_536
MAX_EVIDENCE_EXCERPT_CHARS = 1000


# ============================================================
# RATE LIMITER
# ============================================================

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


# ============================================================
# SIMPLE TOKEN ESTIMATION
# ============================================================

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


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def truncate(text: str, max_chars: int) -> str:
    text = normalize(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


# ============================================================
# EXISTING ANNUAL REPORT PIPELINE
# ============================================================

def load_report_from_file(file_path: str) -> dict[str, Any]:
    """
    Use annual_reports.py's existing PDF text extraction.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Annual report not found: {path}")

    data = extract_report_text(path)

    # In --file mode annual_reports.py is not given a company record, so
    # symbol/year cannot be known reliably. Use the filename as a fallback
    # company label instead of hardcoding "Unknown".
    filename_label = path.stem.replace("_", " ").replace("-", " ").strip()

    return {
        "file_path": str(path),
        "company_name": filename_label or "Unknown",
        "symbol": None,
        "year": None,
        "raw_text": data["raw_text"],
        "page_count": data["page_count"],
    }


def load_report_from_company(symbol: str) -> dict[str, Any]:
    """
    Load the latest annual report for a company stored in Supabase.

    Flow:
        1. Resolve the company by NSE symbol from Supabase.
        2. Use the shared annual-report ingestion service.
        3. Extract the report text for the Gemini POC.
    """
    company = get_company_by_symbol(symbol)

    if company is None:
        raise ValueError(
            f"{symbol.upper()} was not found in the Supabase companies table."
        )

    print(f"Company: {company['name']}")
    print(f"Symbol: {company['symbol']}")
    print(f"Sector: {company.get('sector') or 'Unknown'}")

    if company.get("target_for_worksphere"):
        print("WorkSphere target: YES")
    else:
        print("WorkSphere target: NO (testing is still allowed)")

    result = ingest_report_from_company(
        symbol=company["symbol"],
        company=company,
    )

    return {
        "file_path": str(result["file_path"]),
        "company_name": company["name"],
        "symbol": company["symbol"],
        "sector": company.get("sector"),
        "target_for_worksphere": company.get("target_for_worksphere"),
        "classification_status": company.get("classification_status"),
        "year": result.get("financial_year"),
        "raw_text": result["raw_text"],
        "page_count": result["page_count"],
        "downloaded": result.get("downloaded", False),
        "local_cache_hit": result.get("local_cache_hit", False),
        "google_drive_file_id": result.get("google_drive_file_id"),
    }


# ============================================================
# LOCAL RETRIEVAL
# ============================================================

def build_retrieval_context(
    raw_text: str,
    company_name: str,
) -> tuple[str, dict[str, int], dict[int, dict[str, Any]]]:
    """Build up to ~190k tokens of relevant Gemini context.

    The extractor combines the original semantic retrieval with a broader
    event-discovery pass, then expands selected candidates into surrounding
    report context. We stop by estimated token count so Gemini gets much more
    coverage of secondary events without exceeding the request safety ceiling.
    """
    print("\nRunning existing local retrieval engine with expanded LLM context...")

    packets = extract_evidence_context(
        raw_text,
        company_name=company_name,
        context_radius=30,
        max_candidates=MAX_CANDIDATES,
        max_context_chars=MAX_TOTAL_CONTEXT_CHARS,
    )

    print(f"Expanded LLM context packets: {len(packets)}")

    # Build a stable source-candidate registry. Gemini selects these IDs;
    # it does not author the canonical evidence excerpt.
    source_sentences = split_into_sentences(raw_text)
    candidate_registry: dict[int, dict[str, Any]] = {}

    for candidate_id, packet in enumerate(packets, start=1):
        match = re.search(
            r"Source sentence index:\s*(\d+)",
            packet,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        # The extractor reports sentence indexes as human-readable 1-based
        # indexes; Python sentence lists are 0-based.
        sentence_index = int(match.group(1)) - 1
        if not (0 <= sentence_index < len(source_sentences)):
            continue

        candidate_registry[candidate_id] = {
            "candidate_id": candidate_id,
            "source_sentence_index": sentence_index,
            "source_sentence": source_sentences[sentence_index],
            "packet": packet,
        }

    context_parts = []

    for candidate_id, packet in enumerate(packets, start=1):
        if candidate_id not in candidate_registry:
            continue

        # Make the candidate ID visible to Gemini without changing the
        # retrieved source wording itself.
        packet_with_id = (
            f"[SOURCE_CANDIDATE_ID: {candidate_id}]\n{packet}"
        )
        trial = "\n---\n".join(context_parts + [packet_with_id])
        estimated = estimate_tokens(trial)

        if estimated > MAX_CONTEXT_TOKENS_TARGET:
            break

        context_parts.append(packet_with_id)

    context = "\n---\n".join(context_parts)
    estimated_tokens = estimate_tokens(context)

    # Hard safety check. The actual prompt/system text is added later, so
    # the context target is deliberately below the 200k request safety ceiling.
    if estimated_tokens > MAX_INPUT_TOKENS_PER_REQUEST:
        raise ValueError(
            f"Prepared Gemini context is too large: "
            f"~{estimated_tokens:,} estimated tokens."
        )

    stats = {
        "retrieved_candidates": len(packets),
        "gemini_packets": len(context_parts),
        "context_chars": len(context),
        "estimated_context_tokens": estimated_tokens,
        "source_candidate_count": len(candidate_registry),
    }

    print(
        f"Gemini retrieved context: {stats['context_chars']:,} chars "
        f"(~{stats['estimated_context_tokens']:,} estimated tokens)"
    )

    print(
        f"Source candidates available to Gemini: "
        f"{len(candidate_registry)}"
    )

    return context, stats, candidate_registry


# ============================================================
# SOURCE CANDIDATE RESOLUTION
# ============================================================

def _resolve_source_excerpt(
    signal: dict[str, Any],
    candidate_registry: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve Gemini-selected candidate IDs to exact source sentences.

    Gemini is never trusted to author the canonical excerpt. The application
    uses the candidate IDs to recover the original source wording.
    """
    evidence = signal.get("evidence") or {}
    raw_ids = evidence.get("source_candidate_ids") or []

    candidate_ids: list[int] = []
    for value in raw_ids:
        try:
            candidate_id = int(value)
        except (TypeError, ValueError):
            continue
        if candidate_id not in candidate_registry:
            continue
        if candidate_id not in candidate_ids:
            candidate_ids.append(candidate_id)

    # Preserve source order rather than Gemini's arbitrary selection order.
    candidate_ids.sort(
        key=lambda cid: (
            candidate_registry[cid]["source_sentence_index"],
            cid,
        )
    )

    sentences: list[str] = []
    sentence_indexes: list[int] = []

    for candidate_id in candidate_ids:
        item = candidate_registry[candidate_id]
        sentence = item["source_sentence"]
        index = item["source_sentence_index"]

        if sentence and index not in sentence_indexes:
            sentences.append(sentence)
            sentence_indexes.append(index)

    return {
        "candidate_ids": candidate_ids,
        "sentence_indexes": sentence_indexes,
        "excerpt": " ".join(sentences),
        "page": evidence.get("page"),
    }


# ============================================================
# GEMINI SCHEMA
# ============================================================

SIGNAL_TYPES = [
    "investment",
    "capacity_expansion",
    "facility_expansion",
    "new_facility",
    "facility_construction",
    "land_development",
    "plant_commissioning",
    "land_acquisition",
    "warehouse_distribution",
    "office_expansion",
    "geographic_expansion",
    "hiring",
    "workforce_reduction",
    "leadership_change",
    "acquisition",
    "merger",
    "technology_transformation",
    "sustainability",
]

EVENT_STATES = [
    "historical",
    "current",
    "ongoing",
    "planned",
    "proposed",
    "announced",
    "approved",
    "awaiting_approval",
    "under_construction",
    "commissioned",
    "completed",
    "cancelled",
    "deferred",
    "unknown",
]


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "signals": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "is_valid_signal": {"type": "BOOLEAN"},
                    "signal_type": {
                        "type": "STRING",
                        "enum": SIGNAL_TYPES,
                    },
                    "event_state": {
                        "type": "STRING",
                        "enum": EVENT_STATES,
                    },
                    "headline": {"type": "STRING"},
                    "summary": {"type": "STRING"},
                    "why_it_matters": {"type": "STRING"},
                    "company": {"type": "STRING", "nullable": True},
                    "location": {
                        "type": "OBJECT",
                        "properties": {
                            "mentions": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                            }
                        },
                        "required": ["mentions"],
                    },
                    "investment": {
                        "type": "OBJECT",
                        "properties": {
                            "values": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                            }
                        },
                        "required": ["values"],
                    },
                    "physical_scale": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "timeline": {
                        "type": "STRING",
                    },
                    "physical_consequence": {
                        "type": "STRING"
                    },
                    "supporting_facts": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "evidence": {
                        "type": "OBJECT",
                        "properties": {
                            "source_candidate_ids": {
                                "type": "ARRAY",
                                "items": {"type": "INTEGER"},
                            },
                            "page": {
                                "type": "INTEGER",
                                "nullable": True,
                            },
                        },
                        "required": ["source_candidate_ids", "page"],
                    },
                    "confidence": {
                        "type": "NUMBER"
                    },
                },
                "required": [
                    "is_valid_signal",
                    "signal_type",
                    "event_state",
                    "headline",
                    "summary",
                    "why_it_matters",
                    "company",
                    "location",
                    "investment",
                    "physical_scale",
                    "timeline",
                    "physical_consequence",
                    "supporting_facts",
                    "evidence",
                    "confidence",
                ],
            },
        },
        "negative_evidence": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING"},
                    "statement": {"type": "STRING"},
                    "source_candidate_ids": {
                        "type": "ARRAY",
                        "items": {"type": "INTEGER"},
                    },
                },
                "required": [
                    "category",
                    "statement",
                    "source_candidate_ids",
                ],
            },
        },
    },
    "required": [
        "signals",
        "negative_evidence",
    ],
}


SYSTEM_INSTRUCTION = """
You are the business-event reasoning layer for WorkSphere Market Intelligence.

Your task is to identify meaningful business events from the supplied annual-report
candidate passages and determine whether each event represents a potentially
relevant business opportunity or intelligence signal for WorkSphere.

CRITICAL RULES:

1. Use ONLY the supplied source excerpts.
1a. Every positive signal must select the smallest sufficient set of SOURCE_CANDIDATE_ID
values that directly supports the event.
1b. The SOURCE_CANDIDATE_ID values are provenance references, not facts to be invented.
1c. If no supplied candidate directly supports an event, do not return it as a valid signal.
2. Do not invent facts, dates, locations, amounts, acreage, project status, facilities,
   business activities, or strategic intentions.
3. Every positive signal MUST reference one or more SOURCE_CANDIDATE_ID values.
4. Do NOT author, paraphrase, truncate, or reconstruct the canonical evidence excerpt. The application will resolve the selected candidate IDs back to the exact source text.
5. If a fact is not explicitly supported by the supplied evidence, do not include it.
6. Do not turn historical financial tables, routine financial metrics, or generic
   governance language into business signals.
7. A monetary token by itself is NOT an investment signal.
8. Do not extract arbitrary words or company/address mentions as locations.
9. Merge multiple descriptions of the SAME underlying event into ONE signal.
10. Distinguish carefully between historical, current, ongoing, proposed, planned,
    approved, awaiting-approval, under-construction, commissioned, completed,
    cancelled, deferred, and other explicitly supported states.
11. Do not turn a proposal, intention, target, feasibility study, or future plan into
    a confirmed facility, construction project, acquisition, or completed activity.
12. Explicit negative statements such as "no change", "no new technology",
    "not commenced", or equivalent statements are negative evidence when they
    explicitly describe the absence of a meaningful business condition.
13. Do not treat generic negative wording or unrelated statements as negative
    business evidence. The negative statement must clearly refer to a meaningful
    business topic.
14. "why_it_matters" may describe a potential business implication, but must clearly
    distinguish inference from fact. It must not claim that WorkSphere has won work,
    that a project definitely exists, or that a future requirement is guaranteed.
15. If a candidate is not a meaningful WorkSphere-relevant event, set
    is_valid_signal=false.
16. Prefer distinct meaningful events rather than artificially collapsing unrelated
    events. However, do not create multiple signals merely because the same event is
    described in several places or under several classifications.
17. Use the full retrieved context to resolve meaning. Do not classify an event from
    the candidate sentence alone when surrounding context changes its meaning,
    status, scope, or business implication.
18. Do not classify existing ownership of land as a new land acquisition unless the
    supplied evidence explicitly states that the company acquired, purchased, or
    otherwise newly obtained the land.
19. Do not classify a lease renewal as facility expansion unless the supplied evidence
    explicitly describes expansion, new capacity, construction, development, or
    another physical change.
20. Do not classify a new product, product launch, customer win, partnership, or
    commercial agreement as a facility expansion unless the supplied evidence
    explicitly connects it to physical expansion, new capacity, construction,
    manufacturing infrastructure, or another meaningful operational change.

WORKSPHERE RELEVANCE:

21. Capture both DIRECT and INDIRECT business signals when they are explicitly
    supported by the source.

22. DIRECT signals are events that clearly indicate physical, operational, workplace,
    infrastructure, or organizational change. Examples include:
    - new facilities
    - facility construction
    - facility expansion
    - manufacturing capacity expansion
    - plant commissioning
    - R&D facility expansion
    - warehouse or distribution expansion
    - office expansion
    - land acquisition
    - land development
    - major physical infrastructure development
    - significant workforce expansion tied to an identifiable business expansion
    - major technology transformation involving physical or operational change

23. INDIRECT signals are meaningful business initiatives that may create a future
    requirement or opportunity but do NOT by themselves prove physical expansion.
    Examples include:
    - entry into a new manufacturing or business segment
    - new manufacturing capabilities
    - major technology platforms or transformation initiatives
    - planned new production capabilities
    - geographic expansion
    - establishment of new business functions or teams
    - strategic initiatives that could reasonably lead to operational or physical
      requirements

24. For INDIRECT signals, do NOT infer a facility, construction project, capacity
    expansion, or physical requirement unless the supplied evidence explicitly
    supports it. Instead, describe the event itself and explain the potential
    implication cautiously.

25. Product launches, new products, new customers, contracts, partnerships,
    agreements, revenue growth, profitability changes, or similar commercial events
    should generally NOT be treated as strong WorkSphere signals unless the supplied
    evidence explicitly connects them to a meaningful operational, physical,
    workplace, technology, geographic, or organizational change.

26. A business event can be relevant even when it is planned or future-oriented.
    Preserve its actual status such as planned, proposed, approved, or awaiting
    approval rather than upgrading it to a confirmed project.

27. Do not omit a distinct meaningful event merely because another related event has
    already been identified. If two events represent genuinely different business
    developments, they should remain separate signals.

28. The objective is to identify every distinct meaningful, evidence-backed business
    event present in the supplied evidence. Do not optimize for a short list of
    "strongest" signals. Recall matters: secondary capacity increases, geographic
    rollouts, store/branch/network expansion, facility augmentation, and similar
    operational developments must be captured when explicitly supported.
    The application preserves the selected source candidates for downstream review.

OUTPUT PRINCIPLES:

29. Every returned signal must be independently supported by the supplied source.
30. Keep the event description factual and concise.
31. Evidence source wording is preserved by the application from the selected SOURCE_CANDIDATE_ID values; do not rewrite the source text yourself.
32. Use surrounding context to determine the correct event type and state.
33. Clearly distinguish facts from potential implications.
34. Never manufacture a project, facility, investment, acquisition, expansion,
    location, timeline, or business requirement that is not supported by the source.
"""


# ============================================================
# GEMINI CALL
# ============================================================

def _is_503_error(exc: Exception) -> bool:
    """Return True only for Gemini's temporary 503/unavailable response."""
    message = str(exc).upper()
    return (
        "503" in message
        and (
            "UNAVAILABLE" in message
            or "HIGH DEMAND" in message
            or "CURRENTLY EXPERIENCING" in message
        )
    )


def _is_429_error(exc: Exception) -> bool:
    """Return True for Gemini RESOURCE_EXHAUSTED / HTTP 429 responses."""
    message = str(exc).upper()
    return (
        "429" in message
        or "RESOURCE_EXHAUSTED" in message
        or "TOO MANY REQUESTS" in message
    )


def _extract_provider_retry_delay(exc: Exception) -> float | None:
    """Extract Google's retryDelay (for example '19s') when present."""
    message = str(exc)

    patterns = [
        r"retryDelay[\"']?\s*[:=]\s*[\"']?([0-9]+(?:\.[0-9]+)?)s",
        r"retryDelay[^0-9]*([0-9]+(?:\.[0-9]+)?)s",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    return None


def _quota_retry_delay(exc: Exception) -> float:
    """Use Google's retryDelay when supplied, with a small jitter margin."""
    provider_delay = _extract_provider_retry_delay(exc)

    # The provider's delay is authoritative when present. Add only a small
    # jitter so the next request is less likely to land exactly on the quota
    # boundary. Never sleep less than 1 second.
    if provider_delay is not None:
        return max(1.0, provider_delay + random.uniform(0.5, 2.0))

    # If Google's response does not contain retryDelay, use a conservative
    # default rather than immediately hammering the quota again.
    return 20.0 + random.uniform(0.5, 2.0)


def _backoff_delay(attempt_number: int) -> float:
    """Exponential backoff with jitter, capped for a single POC request."""
    base = min(
        INITIAL_BACKOFF_SECONDS * (2 ** max(0, attempt_number - 1)),
        MAX_BACKOFF_SECONDS,
    )

    # The first retry uses straightforward exponential backoff.
    # Later retries add jitter so concurrent requests do not synchronize.
    if attempt_number == 1:
        return base

    return min(base + random.uniform(0.0, base * 0.5), MAX_BACKOFF_SECONDS)


def _generate_with_model(client, model, contents, config):
    """Single Gemini request; exceptions are intentionally propagated."""
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )


def _parse_gemini_response(response) -> dict[str, Any]:
    """Convert Gemini's JSON response into the dict expected downstream."""
    text = getattr(response, "text", None)

    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        finish_reason = None
        try:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
        except Exception:
            pass

        preview = text[:1200].replace("\n", "\\n")
        raise GeminiJSONParseError(
            "Gemini returned incomplete/invalid JSON. "
            f"finish_reason={finish_reason!r}; response_chars={len(text)}; "
            f"preview={preview!r}"
        ) from exc


class GeminiJSONParseError(RuntimeError):
    """Raised when Gemini generated a response that cannot be parsed as JSON."""


def _build_compact_retry_prompt(
    company_name: str,
    report_year: Any,
    context: str,
) -> str:
    """Build a second-pass prompt when the first JSON response was truncated."""
    return f"""
Analyze the annual report evidence below for WorkSphere.

Company: {company_name or "Unknown"}
Report year: {report_year or "Unknown"}

The previous generation was incomplete JSON. Re-run the reasoning with the
same full evidence set, but make each field VERY COMPACT. Do NOT omit distinct
relevant signals just to shorten the response.

Return ONLY the JSON object matching the supplied response schema.

COMPACT OUTPUT RULES:
- Return ALL meaningful WorkSphere-relevant signals; do NOT reduce the number of signals.
- Return ALL meaningful negative_evidence items that are explicitly supported.
- Merge duplicate descriptions of the SAME underlying event, but do not omit distinct events.
- Keep headline, summary, why_it_matters, timeline, and physical_consequence to one short sentence each.
- supporting_facts: maximum 2 short items.
- physical_scale: maximum 2 short items.
- location.mentions: maximum 2 items.
- investment.values: maximum 2 items.
- evidence.source_candidate_ids MUST contain the source candidate IDs that support the event.
- Do not author or reproduce source excerpts; the application resolves them from those IDs.
- Do not invent anything.
- Finish the complete JSON object.

SOURCE CONTEXT:
{context}
"""


def call_gemini(
    client,
    company_name: str,
    report_year: Any,
    context: str,
    limiter: GeminiRateLimiter,
) -> dict[str, Any]:
    """Call Flash with 503/429 handling, then fall back to Flash-Lite.

    503 behavior:
        Flash -> exponential/jitter retry -> Flash-Lite after 3 failed attempts.

    429 behavior:
        Respect Google's retryDelay -> retry Flash once -> Flash-Lite if the
        quota error persists. A 429 is never treated as a generic crash.

    The full retrieved context is preserved. No context reduction is used as
    a workaround for provider quota errors.
    """
    global LAST_MODEL_RUN_METADATA

    prompt = f"""
Analyze the annual report evidence below for WorkSphere.

Company: {company_name or "Unknown"}
Report year: {report_year or "Unknown"}

The following passages were retrieved locally from the annual report.
They are evidence candidates, NOT conclusions.

The context is intentionally large and may contain multiple surrounding
passages from the same report. Reason across the supplied context before
deciding whether an event is real, its state, and its signal type.
Each retrieved packet has a SOURCE_CANDIDATE_ID. Use those IDs as the
evidence provenance for each signal; do not rewrite the source excerpt.

Return ONLY the JSON object matching the supplied response schema.

OUTPUT RULES — IMPORTANT:
- FIRST mentally enumerate every distinct business event supported by the supplied context.
- THEN return ALL qualifying events; do not select only the largest, newest, or most physical projects.
- Treat secondary operational and geographic developments as candidates too, including capacity increases, facility/site augmentation, production scale-ups, store/branch/network expansion, new geographic presence, planned projects, acquisitions, mergers/amalgamations, and leadership changes.
- A smaller event is still valid if it is explicit, distinct, and meaningful. Do not omit it merely because a larger related event exists.
- Do not impose an arbitrary limit on the number of signals or negative_evidence items.
- Merge duplicate descriptions of the SAME underlying event, but do not omit distinct events.
- Keep headline, summary, why_it_matters, timeline, physical_consequence concise.
- supporting_facts: maximum 3 short items per signal.
- physical_scale: maximum 3 short items per signal.
- location.mentions: maximum 3 items.
- investment.values: maximum 3 items.
- evidence.source_candidate_ids MUST contain the source candidate IDs that support the event.
- Do NOT author an evidence excerpt; the application resolves exact source wording from those IDs.
- Do NOT repeat the same event as multiple signal types.
- If there are no valid signals, return an empty signals array.
- Always finish the complete JSON object. Do not stop mid-string or mid-array.

SOURCE CONTEXT:
{context}
"""

    estimated_input_tokens = estimate_tokens(
        SYSTEM_INSTRUCTION + prompt
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    def generate(model: str, request_prompt: str = prompt):
        """Reserve quota before the provider call, then make one request.

        Recording before the request is intentionally conservative: if Google
        accepts the request and then returns 429/503, the attempt is still
        counted against our local safety window and we avoid immediately
        sending another 145k-token request.
        """
        request_tokens = estimate_tokens(
            SYSTEM_INSTRUCTION + request_prompt
        )
        limiter.wait_for_capacity(request_tokens)
        limiter.record(request_tokens)
        return _generate_with_model(
            client=client,
            model=model,
            contents=request_prompt,
            config=config,
        )

    def compact_generate(model: str):
        compact_prompt = _build_compact_retry_prompt(
            company_name=company_name,
            report_year=report_year,
            context=context,
        )
        return generate(model, compact_prompt)

    flash_attempts = 0
    flash_429_retries = 0
    fallback_reason = None

    for attempt in range(1, MAX_FLASH_ATTEMPTS + 1):
        flash_attempts = attempt

        try:
            print(
                f"\nGemini Flash attempt "
                f"{attempt}/{MAX_FLASH_ATTEMPTS}..."
            )
            response = generate(MODEL)

            print("Gemini Flash succeeded.")
            LAST_MODEL_RUN_METADATA = {
                "model_attempted": MODEL,
                "model_used": MODEL,
                "flash_attempts": flash_attempts,
                "flash_429_retries": flash_429_retries,
                "fallback_used": False,
                "fallback_reason": None,
            }

            try:
                return _parse_gemini_response(response)
            except GeminiJSONParseError as parse_exc:
                print(
                    "Gemini Flash generated incomplete JSON. "
                    "Retrying once with a compact-output prompt..."
                )

                try:
                    compact_response = compact_generate(MODEL)
                except Exception as compact_exc:
                    if _is_429_error(compact_exc):
                        delay = _quota_retry_delay(compact_exc)
                        print(
                            "Gemini Flash compact retry hit 429 "
                            "RESOURCE_EXHAUSTED. "
                            f"Waiting {delay:.1f}s before one final Flash retry..."
                        )
                        time.sleep(delay)
                        compact_response = compact_generate(MODEL)
                    else:
                        raise

                try:
                    return _parse_gemini_response(compact_response)
                except GeminiJSONParseError:
                    raise RuntimeError(
                        "Gemini produced incomplete JSON twice. "
                        "The large retrieved input context was accepted, but the model "
                        "did not complete the structured output."
                    ) from parse_exc

        except Exception as exc:
            if _is_503_error(exc):
                if attempt < MAX_FLASH_ATTEMPTS:
                    delay = _backoff_delay(attempt)
                    print(
                        f"Gemini Flash returned 503. "
                        f"Retrying after {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    continue

                fallback_reason = "503_UNAVAILABLE"
                break

            if _is_429_error(exc):
                # Google provides a concrete retryDelay for quota exhaustion.
                # Respect it once, then stop retrying Flash and use Lite.
                if flash_429_retries < 1:
                    flash_429_retries += 1
                    delay = _quota_retry_delay(exc)
                    provider_delay = _extract_provider_retry_delay(exc)
                    provider_text = (
                        f"Google retryDelay={provider_delay:.1f}s; "
                        if provider_delay is not None
                        else "Google did not provide retryDelay; "
                    )
                    print(
                        "Gemini Flash returned 429 RESOURCE_EXHAUSTED. "
                        f"{provider_text}waiting {delay:.1f}s before retry..."
                    )
                    time.sleep(delay)
                    continue

                fallback_reason = "429_RESOURCE_EXHAUSTED"
                break

            # Authentication, malformed requests, schema errors, etc. are not
            # recoverable through this fallback and should remain visible.
            raise

    print(
        f"\nGemini Flash unavailable. "
        f"Falling back to {FALLBACK_MODEL} "
        f"(reason={fallback_reason})..."
    )

    try:
        response = generate(FALLBACK_MODEL)
    except Exception as exc:
        if _is_429_error(exc):
            delay = _quota_retry_delay(exc)
            provider_delay = _extract_provider_retry_delay(exc)
            provider_text = (
                f"Google retryDelay={provider_delay:.1f}s; "
                if provider_delay is not None
                else "Google did not provide retryDelay; "
            )
            print(
                f"{FALLBACK_MODEL} also returned 429 RESOURCE_EXHAUSTED. "
                f"{provider_text}waiting {delay:.1f}s and retrying once..."
            )
            time.sleep(delay)
            response = generate(FALLBACK_MODEL)
        else:
            raise

    print(f"{FALLBACK_MODEL} succeeded.")

    LAST_MODEL_RUN_METADATA = {
        "model_attempted": MODEL,
        "model_used": FALLBACK_MODEL,
        "flash_attempts": flash_attempts,
        "flash_429_retries": flash_429_retries,
        "fallback_used": True,
        "fallback_reason": fallback_reason,
    }

    try:
        return _parse_gemini_response(response)
    except GeminiJSONParseError as parse_exc:
        print(
            f"{FALLBACK_MODEL} generated incomplete JSON. "
            "Retrying once with a compact-output prompt..."
        )

        try:
            compact_response = compact_generate(FALLBACK_MODEL)
        except Exception as compact_exc:
            if _is_429_error(compact_exc):
                delay = _quota_retry_delay(compact_exc)
                print(
                    f"{FALLBACK_MODEL} compact retry hit 429. "
                    f"Waiting {delay:.1f}s and retrying once..."
                )
                time.sleep(delay)
                compact_response = compact_generate(FALLBACK_MODEL)
            else:
                raise

        try:
            return _parse_gemini_response(compact_response)
        except GeminiJSONParseError:
            raise RuntimeError(
                f"{FALLBACK_MODEL} produced incomplete JSON twice."
            ) from parse_exc

def resolve_gemini_output(
    result: dict[str, Any],
    candidate_registry: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    Resolve Gemini-selected source candidates to exact annual-report text.

    Gemini is the reasoning layer. There is deliberately NO deterministic
    evidence validator in this POC.

    Every Gemini signal is retained. When Gemini supplies valid
    SOURCE_CANDIDATE_ID values, the application resolves those IDs back to
    the exact original source sentences. If a signal cannot be resolved,
    it is retained with a source_resolution_status of "unresolved" rather
    than being rejected by another rules engine.
    """

    resolved_signals: list[dict[str, Any]] = []
    unresolved_signals: list[dict[str, Any]] = []

    for signal_index, signal in enumerate(
        result.get("signals", []),
        start=1,
    ):
        resolved = _resolve_source_excerpt(
            signal,
            candidate_registry,
        )

        enriched = dict(signal)
        evidence = dict(signal.get("evidence") or {})

        evidence.update(
            {
                "source_candidate_ids": resolved["candidate_ids"],
                "source_sentence_indexes": resolved["sentence_indexes"],
                "excerpt": resolved["excerpt"],
                "page": resolved["page"],
            }
        )

        enriched["evidence"] = evidence
        enriched["source_resolution_status"] = (
            "resolved"
            if resolved["candidate_ids"] and resolved["excerpt"]
            else "unresolved"
        )

        if enriched["source_resolution_status"] == "unresolved":
            enriched["source_resolution_reason"] = (
                "Gemini did not provide source candidate IDs that could be "
                "resolved to exact annual-report source text."
            )
            unresolved_signals.append(enriched)

        resolved_signals.append(enriched)

    resolved_negative_evidence: list[dict[str, Any]] = []
    unresolved_negative_evidence: list[dict[str, Any]] = []

    for item in result.get("negative_evidence", []):
        resolved = _resolve_source_excerpt(
            {
                "evidence": {
                    "source_candidate_ids": item.get(
                        "source_candidate_ids",
                        [],
                    ),
                    "page": None,
                }
            },
            candidate_registry,
        )

        enriched = dict(item)
        enriched["source_candidate_ids"] = resolved["candidate_ids"]
        enriched["source_sentence_indexes"] = resolved["sentence_indexes"]
        enriched["excerpt"] = resolved["excerpt"]

        if resolved["candidate_ids"] and resolved["excerpt"]:
            enriched["source_resolution_status"] = "resolved"
            resolved_negative_evidence.append(enriched)
        else:
            enriched["source_resolution_status"] = "unresolved"
            enriched["source_resolution_reason"] = (
                "Negative evidence could not be resolved to exact "
                "annual-report source text."
            )
            unresolved_negative_evidence.append(enriched)

    return {
        "signals": resolved_signals,
        "negative_evidence": resolved_negative_evidence,
        "unresolved_signals": unresolved_signals,
        "unresolved_negative_evidence": unresolved_negative_evidence,
    }


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simple WorkSphere Gemini annual-report POC"
    )

    source = parser.add_mutually_exclusive_group(required=True)

    source.add_argument(
        "--file",
        help="Path to an already downloaded annual-report PDF.",
    )

    source.add_argument(
        "--company",
        help="NSE symbol stored in the Supabase companies table.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 70)
    print("WorkSphere Gemini POC")
    print("=" * 70)

    if args.file:
        report = load_report_from_file(args.file)
    else:
        report = load_report_from_company(args.company)

    raw_text = report["raw_text"]

    print(f"Company: {report['company_name']}")
    print(f"Symbol: {report['symbol']}")
    print(f"Year: {report['year']}")
    print(f"Pages: {report['page_count']}")
    print(
        f"Raw characters: "
        f"{len(raw_text):,}"
    )

    if report.get(
        "local_cache_hit"
    ):
        print(
            "Report source: LOCAL CACHE "
            "(no download)"
        )
    elif report.get(
        "downloaded"
    ):
        print(
            "Report source: NSE DOWNLOAD"
        )
    else:
        print(
            "Report source: LOCAL FILE"
        )

    context, retrieval_stats, candidate_registry = build_retrieval_context(
        raw_text,
        report["company_name"],
    )

    api_key = __import__("os").getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Add it to your environment before running the Gemini call."
        )

    client = genai.Client(
        api_key=api_key
    )

    limiter = GeminiRateLimiter()

    result = call_gemini(
        client=client,
        company_name=report["company_name"],
        report_year=report["year"],
        context=context,
        limiter=limiter,
    )
    model_run_metadata = LAST_MODEL_RUN_METADATA.copy()

    source_resolution = resolve_gemini_output(
        result,
        candidate_registry,
    )

    output = {
        "report": {
            "company": report["company_name"],
            "symbol": report["symbol"],
            "sector": report.get(
                "sector",
                ""
            ),
                "classification_status": report.get(
                "classification_status",
                ""
            ),
            "target_for_worksphere": report.get(
                "target_for_worksphere",
                ""
            ),
            "year": report["year"],
            "file": report["file_path"],
            "downloaded": report.get(
                "downloaded",
                False
            ),
            "local_cache_hit": report.get(
                "local_cache_hit",
                False
            ),
        },
        "retrieval": retrieval_stats,
        "model_run": model_run_metadata,
        "gemini": result,
        "source_resolution": source_resolution,
        "rate_limit_policy": {
            "max_rpm": MAX_REQUESTS_PER_MINUTE,
            "provider_rpm_limit_assumed": 10,
            "max_input_tokens_per_request": MAX_INPUT_TOKENS_PER_REQUEST,
            "max_input_tokens_per_minute": MAX_INPUT_TOKENS_PER_MINUTE,
        },
    }

    output_path = Path("gemini_poc_result.json")

    output_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print("GEMINI RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n" + "=" * 70)
    print("SOURCE RESOLUTION")
    print("=" * 70)

    print(
        f"Gemini signals: "
        f"{len(source_resolution['signals'])}"
    )

    print(
        f"Resolved source signals: "
        f"{len(source_resolution['signals']) - len(source_resolution['unresolved_signals'])}"
    )

    print(
        f"Unresolved source signals: "
        f"{len(source_resolution['unresolved_signals'])}"
    )

    print(
        f"Resolved negative evidence: "
        f"{len(source_resolution['negative_evidence'])}"
    )

    print(
        f"Unresolved negative evidence: "
        f"{len(source_resolution['unresolved_negative_evidence'])}"
    )

    print(
        "\nNo deterministic evidence validator is used. "
        "Gemini output is retained and source text is resolved "
        "from the selected candidate IDs."
    )

    print(
        f"\nSaved result to: {output_path}"
    )


if __name__ == "__main__":
    main()
