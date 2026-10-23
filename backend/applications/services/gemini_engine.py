"""WorkSphere Gemini reasoning engine.

Production extraction from the Gemini POC.

Responsibilities:
    - prepare retrieved evidence context for Gemini
    - enforce Gemini request/token rate limits
    - call Gemini with structured output
    - retry temporary provider failures and fall back to Flash-Lite
    - resolve Gemini-selected source candidate IDs to exact source text
    - orchestrate one complete annual-report processing run

This module deliberately does NOT:
    - define database models
    - implement Supabase CRUD internally
    - implement NSE/Google Drive internals
    - validate/reject evidence with a deterministic validator
    - contain Flask route definitions
    - contain CLI code

Production flow:
    annual report
        -> retrieval
        -> Gemini reasoning (business signals)
        -> source resolution
        -> Supabase evidence
        -> processing-run completion
"""

from __future__ import annotations

import json
import os
import random
import re
import socket
import time
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from dotenv import load_dotenv
from google import genai
from google.genai import types

from applications.services.annual_report_ingestion import (
    extract_report_text,
    load_report_from_company,
)
from applications.services.annual_reports import (
    get_annual_report,
    claim_report_for_processing,
    mark_report_failed,
    mark_report_processed,
    update_annual_report,
)
from applications.services.evidence_extractor import (
    extract_evidence_context,
    split_into_sentences,
)
from applications.services.evidence_service import (
    create_evidence_batch,
)
from applications.services.processing_runs import (
    complete_processing_run,
    create_processing_run,
    fail_processing_run,
)
from applications.services.supabase_client import supabase

load_dotenv()


# ============================================================
# GEMINI / RATE LIMIT CONFIG
# ============================================================

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
FALLBACK_MODEL = os.getenv(
    "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"
)

LAST_MODEL_RUN_METADATA: dict[str, Any] = {}

# Retry policy:
#   1) Flash attempt
#   2) 503 -> exponential backoff
#   3) 503 -> jittered backoff
#   4) 503 -> fall back to Flash-Lite

# Maximum number of Gemini generation attempts for a single processing request.
# Retries are used for transient provider/network failures.
MAX_FLASH_ATTEMPTS = 3

# Initial delay, in seconds, before retrying a failed Gemini request.
INITIAL_BACKOFF_SECONDS = 4.0

# Maximum delay, in seconds, between retry attempts.
MAX_BACKOFF_SECONDS = 60.0

# Maximum number of Gemini API requests our application allows per minute.
# The stated provider limit is 5 RPM; we intentionally operate below it.
MAX_REQUESTS_PER_MINUTE = 1

# Maximum total context window supported by the configured Gemini model.
# This is the model capability ceiling (1,048,576 input/output context tokens),
# not the application's annual-report evidence budget.
MAX_MODEL_INPUT_TOKENS = 1048576

# Maximum number of input tokens allowed in a single Gemini API request.
# This limits the annual-report evidence and prompt sent to Gemini.
MAX_INPUT_TOKENS_PER_REQUEST = int(
    os.getenv("GEMINI_MAX_INPUT_TOKENS", "200000")
)

# Maximum number of input tokens our application allows across Gemini
# requests within a one-minute rate-limit window.
# The stated provider limit is 250,000 input tokens per minute.
MAX_INPUT_TOKENS_PER_MINUTE = int(
    os.getenv("GEMINI_INPUT_TOKENS_PER_MINUTE", "250000")
)

# Maximum estimated input-token budget allocated to retrieved annual-report
# evidence for a single Gemini request.
# This is an INPUT budget only. Output tokens are not subtracted from it.
# The retrieval stage reserves additional input-side prompt overhead below.
MAX_CONTEXT_TOKENS_TARGET = int(
    os.getenv("GEMINI_CONTEXT_TOKEN_BUDGET", "190000")
)

# Maximum number of evidence candidates considered during retrieval and
# relevance selection before the final Gemini context is assembled.
MAX_CANDIDATES = int(
    os.getenv("GEMINI_MAX_CANDIDATES", "350")
)

# Maximum number of characters retained from an individual retrieved
# evidence passage before it is included in the Gemini context.
MAX_EXCERPT_CHARS = int(
    os.getenv("GEMINI_MAX_PASSAGE_CHARS", "6000")
)

# Maximum character budget used while assembling retrieved annual-report
# evidence before the final token-budget validation.
# This is a retrieval-stage cap; MAX_CONTEXT_TOKENS_TARGET remains the
# authoritative token-based evidence budget.
MAX_TOTAL_CONTEXT_CHARS = MAX_CONTEXT_TOKENS_TARGET * 3

# Maximum number of output tokens Gemini is allowed to generate for the
# structured annual-report intelligence JSON.
# This is an output ceiling, not a target. It is separate from the input-token
# request/TPM budgets and is not subtracted from them.
MAX_OUTPUT_TOKENS = int(
    os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "60000")
)

# Maximum number of characters retained for an individual evidence excerpt
# that is persisted with an extracted intelligence signal.
MAX_EVIDENCE_EXCERPT_CHARS = 1000

# ============================================================
# RATE LIMITER
# ============================================================

class GeminiRateLimiter:
    """
    Conservative sliding-window limiter.

    Guarantees:
      - no more than MAX_REQUESTS_PER_MINUTE requests in any 60-second window
      - estimated input tokens stay below MAX_INPUT_TOKENS_PER_MINUTE
        in any 60-second window
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
                f"(requests={request_count}/{self.max_requests}, "
                f"input_tokens={token_count:,}/{self.max_input_tokens:,})"
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
# LOCAL RETRIEVAL
# ============================================================



def build_retrieval_context(
    raw_text: str,
    company_name: str,
) -> tuple[str, dict[str, int], dict[int, dict[str, Any]]]:
    """Build Gemini context for both business events and financial metrics.

    Business-event retrieval keeps the existing broad recall behavior. A
    dedicated financial retrieval pass is then added to the same candidate
    registry so Gemini can extract annual revenue and revenue growth even when
    those values live in a financial-performance table rather than an event
    passage.
    """
    print("\nRunning existing local retrieval engine with expanded LLM context...")

    packets = extract_evidence_context(
        raw_text,
        company_name=company_name,
        # Keep the retriever's relevance ordering while using a local window
        # that retains enough adjacent text to resolve context and event state.
        context_radius=8,
        max_candidates=MAX_CANDIDATES,
        max_context_chars=MAX_TOTAL_CONTEXT_CHARS,
    )

    print(f"Expanded LLM context packets: {len(packets)}")

    source_sentences = split_into_sentences(raw_text)
    candidate_registry: dict[int, dict[str, Any]] = {}
    selected_registry: dict[int, dict[str, Any]] = {}
    context_parts: list[str] = []
    seen_passages: set[str] = set()
    # The context/evidence budget is an INPUT budget. Output tokens are
    # controlled separately by MAX_OUTPUT_TOKENS and must not be subtracted
    # from the provider's input-token TPM/request budget.
    #
    # Reserve only input-side overhead for the system instruction, prompt
    # instructions, company/report metadata, and formatting.
    INPUT_PROMPT_OVERHEAD_RESERVE = 10_000
    context_budget = min(
        MAX_CONTEXT_TOKENS_TARGET,
        MAX_INPUT_TOKENS_PER_REQUEST - INPUT_PROMPT_OVERHEAD_RESERVE,
    )
    if context_budget <= 0:
        raise ValueError(
            "Gemini input budget is too small to leave room for prompt overhead."
        )

    for candidate_id, packet in enumerate(packets, start=1):
        match = re.search(
            r"Source sentence index:\s*(\d+)",
            packet,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        sentence_index = int(match.group(1)) - 1
        if not (0 <= sentence_index < len(source_sentences)):
            continue

        candidate_registry[candidate_id] = {
            "candidate_id": candidate_id,
            "source_sentence_index": sentence_index,
            "source_sentence": source_sentences[sentence_index],
            "packet": packet,
            "candidate_kind": "event",
        }

    for candidate_id, packet in enumerate(packets, start=1):
        candidate = candidate_registry.get(candidate_id)
        if candidate is None:
            continue

        center = candidate["source_sentence_index"]
        passage_sentences = [source_sentences[center]]
        left = center - 1
        right = center + 1
        while left >= 0 or right < len(source_sentences):
            grew = False
            if left >= 0:
                proposed = " ".join([source_sentences[left], *passage_sentences])
                if len(proposed) <= MAX_EXCERPT_CHARS:
                    passage_sentences.insert(0, source_sentences[left])
                    left -= 1
                    grew = True
            if right < len(source_sentences):
                proposed = " ".join([*passage_sentences, source_sentences[right]])
                if len(proposed) <= MAX_EXCERPT_CHARS:
                    passage_sentences.append(source_sentences[right])
                    right += 1
                    grew = True
            if not grew:
                break

        passage = " ".join(passage_sentences)
        passage_key = re.sub(r"\s+", " ", passage).strip().casefold()
        if passage_key in seen_passages:
            continue
        seen_passages.add(passage_key)

        packet_with_id = (
            f"[SOURCE_CANDIDATE_ID: {candidate_id}]\n"
            f"Source sentence index: {center + 1}\n"
            f"Candidate relevance score: "
            f"{candidate['packet'].split('Candidate score: ')[-1].splitlines()[0]}\n"
            f"Source passage:\n{passage}"
        )
        trial = "\n---\n".join(context_parts + [packet_with_id])
        estimated = estimate_tokens(trial)

        if estimated > context_budget:
            continue

        context_parts.append(packet_with_id)
        selected_registry[candidate_id] = candidate

    context = "\n---\n".join(context_parts)
    estimated_tokens = estimate_tokens(context)

    # This is a final input-only check for the assembled context. The output
    # ceiling is checked separately against the model's total context window
    # in call_gemini().
    request_estimate = estimate_tokens(SYSTEM_INSTRUCTION + context)
    if request_estimate > MAX_INPUT_TOKENS_PER_REQUEST:
        raise ValueError(
            "Prepared Gemini evidence context exceeds "
            "GEMINI_MAX_INPUT_TOKENS. Reduce the context budget."
        )

    if request_estimate + MAX_OUTPUT_TOKENS > MAX_MODEL_INPUT_TOKENS:
        raise ValueError(
            "Prepared Gemini request exceeds the model input window after "
            "reserving the configured output budget."
        )

    stats = {
        "retrieved_candidates": len(packets),
        "gemini_packets": len(context_parts),
        "context_chars": len(context),
        "estimated_context_tokens": estimated_tokens,
        "source_candidate_count": len(selected_registry),
        "context_budget_tokens": context_budget,
        "candidates_truncated": max(0, len(candidate_registry) - len(selected_registry)),
    }

    print(
        f"Gemini retrieved context: {stats['context_chars']:,} chars "
        f"(~{stats['estimated_context_tokens']:,} estimated tokens)"
    )
    print(
        f"Source candidates available to Gemini: "
        f"{len(selected_registry)} selected from {len(candidate_registry)} retrieved"
    )

    return context, stats, selected_registry

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


def _is_transient_error(exc: Exception) -> bool:
    """Retry temporary HTTP responses and transport failures only."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    if status is not None:
        return status in {408, 425, 429} or 500 <= status <= 599
    return isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            ConnectionError,
            TimeoutError,
            socket.timeout,
        ),
    )


def _retry_reason(exc: Exception) -> str:
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return f"HTTP_{status}" if status else f"NETWORK_{type(exc).__name__}"


def _safe_processing_error(exc: Exception) -> str:
    """Keep credentials, request bodies, and provider response text out of persisted/API status."""

    # Console-only diagnostic detail during development.
    print(
        f"\n[Annual Report Debug] {type(exc).__name__}: {exc}",
        flush=True,
    )

    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)

    if status:
        return f"Gemini provider request failed (HTTP {status})."

    if isinstance(
        exc,
        (httpx.HTTPError, ConnectionError, TimeoutError, socket.timeout),
    ):
        return (
            "Gemini request failed because of a network error "
            f"({type(exc).__name__})."
        )

    return f"Annual-report processing failed ({type(exc).__name__})."


def _extract_provider_retry_delay(exc: Exception) -> float | None:
    """Extract Google's retryDelay (for example '19s') when present."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(str(retry_after))
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(
                        0.0,
                        (retry_at - datetime.now(timezone.utc)).total_seconds(),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass

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

    # MAX_INPUT_TOKENS_PER_REQUEST is an INPUT-token limit. Do not subtract
    # MAX_OUTPUT_TOKENS here: provider TPM is measured on input tokens.
    if estimated_input_tokens > MAX_INPUT_TOKENS_PER_REQUEST:
        raise ValueError(
            "Prepared Gemini request exceeds GEMINI_MAX_INPUT_TOKENS. "
            "Reduce the retrieved context or increase the configured "
            "input-token request budget."
        )

    # The model's context window is a separate constraint. This check uses
    # input + the configured maximum output because both directions must fit
    # within the model's total context capacity.
    if estimated_input_tokens + MAX_OUTPUT_TOKENS > MAX_MODEL_INPUT_TOKENS:
        raise ValueError(
            "Prepared Gemini request exceeds the model context window after "
            "accounting for the configured maximum output budget."
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
        # Validate input tokens against the input-token request limit.
        # MAX_OUTPUT_TOKENS is intentionally NOT subtracted here.
        if request_tokens > MAX_INPUT_TOKENS_PER_REQUEST:
            raise ValueError(
                "Prepared Gemini request exceeds GEMINI_MAX_INPUT_TOKENS. "
                "Reduce the retrieved context or increase the configured "
                "input-token request budget."
            )

        # Separately validate the model's total context capacity.
        if request_tokens + MAX_OUTPUT_TOKENS > MAX_MODEL_INPUT_TOKENS:
            raise ValueError(
                "Prepared Gemini request exceeds the model context window "
                "after accounting for the configured maximum output budget."
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
            if _is_transient_error(exc):
                fallback_reason = _retry_reason(exc)
                if attempt < MAX_FLASH_ATTEMPTS:
                    if _is_429_error(exc):
                        flash_429_retries += 1
                        delay = _quota_retry_delay(exc)
                    else:
                        delay = _backoff_delay(attempt)
                    print(
                        f"Gemini {MODEL} transient failure "
                        f"({fallback_reason}); retry {attempt + 1}/"
                        f"{MAX_FLASH_ATTEMPTS} in {delay:.1f}s."
                    )
                    time.sleep(delay)
                    continue
                break

            # Authentication, malformed requests, schema errors, etc. are not
            # recoverable through this fallback and should remain visible.
            raise

    print(
        f"\nGemini Flash unavailable. "
        f"Falling back to {FALLBACK_MODEL} "
        f"(reason={fallback_reason})..."
    )

    for fallback_attempt in range(1, 3):
        try:
            response = generate(FALLBACK_MODEL)
            break
        except Exception as exc:
            if not _is_transient_error(exc) or fallback_attempt == 2:
                raise
            delay = (
                _quota_retry_delay(exc)
                if _is_429_error(exc)
                else _backoff_delay(flash_attempts + fallback_attempt)
            )
            print(
                f"{FALLBACK_MODEL} transient failure "
                f"({_retry_reason(exc)}); retry in {delay:.1f}s."
            )
            time.sleep(delay)

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
    report_year: Any = None,
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
# PRODUCTION ANNUAL-REPORT ORCHESTRATION
# ============================================================

def _get_company(company_id: str) -> dict[str, Any]:
    """Fetch one company from Supabase."""
    response = (
        supabase
        .table("companies")
        .select("*")
        .eq("id", company_id)
        .maybe_single()
        .execute()
    )

    company = response.data

    if not company:
        raise RuntimeError(
            f"Company not found in Supabase: {company_id}"
        )

    return company


def _get_gemini_client():
    """Create the Gemini client from the backend environment."""
    import os

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set in the environment."
        )

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )


def _load_report_text(
    report: dict[str, Any],
    company: dict[str, Any],
) -> tuple[str, int, dict[str, Any]]:
    """
    Load the report text.

    If the Supabase record already points to a local PDF, use that exact
    report. Otherwise fetch the latest NSE report for the company using the
    existing ingestion service.

    Returns:
        raw_text, page_count, ingestion_metadata
    """
    local_file_path = report.get("local_file_path")

    if local_file_path:
        path = __import__("pathlib").Path(local_file_path)

        if path.exists():
            print(
                f"Using existing annual report PDF: {path}"
            )

            document = extract_report_text(path)

            return (
                document["raw_text"],
                document["page_count"],
                {
                    "local_file_path": str(path),
                    "google_drive_file_id": report.get(
                        "google_drive_file_id"
                    ),
                },
            )

    print(
        "Local annual-report PDF is unavailable. "
        "Fetching the latest NSE report..."
    )

    result = load_report_from_company(
        symbol=company["symbol"],
        company=company,
    )

    if not result:
        raise RuntimeError(
            f"No annual report could be loaded for "
            f"{company.get('symbol', 'company')}."
        )

    return (
        result["raw_text"],
        result["page_count"],
        {
            "local_file_path": result.get("file_path"),
            "google_drive_file_id": result.get(
                "google_drive_file_id"
            ),
            "nse_url": result.get("nse_url"),
            "report_title": result.get("file_name"),
            "financial_year": result.get("financial_year"),
        },
    )


def process_annual_report(
    report_id: str,
    *,
    client=None,
    limiter: GeminiRateLimiter | None = None,
) -> dict[str, Any]:
    """
    Run the complete production annual-report intelligence pipeline.

    Flow:
        Supabase annual_reports
            -> report text
            -> local evidence retrieval
            -> Gemini reasoning
            -> exact source resolution
            -> Supabase evidence
            -> processing_runs completion

    There is intentionally NO deterministic evidence validator.
    Every Gemini signal is retained; unresolved signals are stored with
    source_resolution_status="unresolved".

    This function is the single backend orchestration entry point that a
    Flask route/background worker should call.
    """
    report = get_annual_report(report_id)

    if not report:
        raise LookupError(
            f"Annual report not found: {report_id}"
        )

    company = _get_company(
        report["company_id"]
    )

    # The conditional update prevents concurrent requests in separate Flask
    # workers from processing the same report at the same time.
    claim_report_for_processing(report_id)
    try:
        run = create_processing_run(
            company_id=company["id"],
            annual_report_id=report["id"],
            model_attempted=MODEL,
        )
    except Exception:
        try:
            mark_report_failed(report_id)
        except Exception:
            pass
        raise

    run_id = run["id"]

    try:
        print(
            f"\n{'=' * 70}\n"
            f"PROCESSING ANNUAL REPORT\n"
            f"Company: {company.get('name')} "
            f"({company.get('symbol')})\n"
            f"Financial year: {report.get('financial_year')}\n"
            f"Report ID: {report_id}\n"
            f"{'=' * 70}"
        )

        # ----------------------------------------------------
        # 1. Load exact annual-report text
        # ----------------------------------------------------

        raw_text, page_count, ingestion_metadata = (
            _load_report_text(
                report,
                company,
            )
        )

        # If ingestion had to fetch a new report, keep the existing
        # Supabase annual_reports row synchronized with its metadata.
        metadata_updates: dict[str, Any] = {}

        for field in (
            "local_file_path",
            "google_drive_file_id",
            "nse_url",
            "report_title",
        ):
            value = ingestion_metadata.get(field)

            if value is not None:
                metadata_updates[field] = value

        if ingestion_metadata.get("financial_year"):
            metadata_updates["financial_year"] = (
                ingestion_metadata["financial_year"]
            )

        if metadata_updates:
            update_annual_report(
                report_id,
                metadata_updates,
            )

        # ----------------------------------------------------
        # 2. Build retrieval context
        # ----------------------------------------------------

        context, retrieval_stats, candidate_registry = (
            build_retrieval_context(
                raw_text=raw_text,
                company_name=company["name"],
            )
        )

        # ----------------------------------------------------
        # 3. Create Gemini client + limiter
        # ----------------------------------------------------

        gemini_client = (
            client
            if client is not None
            else _get_gemini_client()
        )

        request_limiter = (
            limiter
            if limiter is not None
            else GeminiRateLimiter()
        )

        # ----------------------------------------------------
        # 4. Gemini reasoning
        # ----------------------------------------------------

        gemini_result = call_gemini(
            client=gemini_client,
            company_name=company["name"],
            report_year=report.get("financial_year"),
            context=context,
            limiter=request_limiter,
        )

        # ----------------------------------------------------
        # 5. Resolve Gemini-selected source candidates
        # ----------------------------------------------------

        resolved = resolve_gemini_output(
            result=gemini_result,
            candidate_registry=candidate_registry,
            report_year=report.get("financial_year"),
        )

        signals = resolved["signals"]
        unresolved_signals = resolved[
            "unresolved_signals"
        ]

        resolved_signal_count = len(
            signals
        ) - len(unresolved_signals)

        # ----------------------------------------------------
        # 6. Persist evidence
        # ----------------------------------------------------

        evidence_rows = create_evidence_batch(
            company_id=company["id"],
            source_type="annual_report",
            source_id=report["id"],
            financial_year=report.get(
                "financial_year"
            ),
            signals=signals,
        )

        # ----------------------------------------------------
        # 7. Mark annual report processed
        # ----------------------------------------------------

        drive_file_id = ingestion_metadata.get(
            "google_drive_file_id"
        )

        updated_report = mark_report_processed(
            report_id=report_id,
            page_count=page_count,
            google_drive_file_id=drive_file_id,
        )

        # ----------------------------------------------------
        # 9. Complete processing run
        # ----------------------------------------------------

        run_result = complete_processing_run(
            run_id,
            model_used=LAST_MODEL_RUN_METADATA.get(
                "model_used"
            ),
            fallback_reason=LAST_MODEL_RUN_METADATA.get(
                "fallback_reason"
            ),
            flash_attempts=LAST_MODEL_RUN_METADATA.get(
                "flash_attempts"
            ),
            candidate_count=len(
                candidate_registry
            ),
            signal_count=len(signals),
            resolved_signal_count=resolved_signal_count,
            unresolved_signal_count=len(
                unresolved_signals
            ),
        )

        print(
            f"\nProcessing complete: "
            f"{len(evidence_rows)} evidence rows stored."
        )

        return {
            "report": updated_report,
            "processing_run": run_result,
            "signals": signals,
            "negative_evidence": resolved[
                "negative_evidence"
            ],
            "unresolved_signals": unresolved_signals,
            "unresolved_negative_evidence": resolved[
                "unresolved_negative_evidence"
            ],
            "retrieval_stats": retrieval_stats,
            "model_metadata": dict(
                LAST_MODEL_RUN_METADATA
            ),
        }

    except Exception as error:
        error_message = _safe_processing_error(error)
        print(f"\nAnnual-report processing failed: {error_message}")

        try:
            fail_processing_run(run_id, error_message)
        except Exception as status_error:
            print(
                "Could not persist failed processing-run status "
                f"({type(status_error).__name__})."
            )

        try:
            mark_report_failed(report_id)
        except Exception as status_error:
            print(
                "Could not persist failed annual-report status "
                f"({type(status_error).__name__})."
            )

        # Preserve the processing exception even if either status update fails.
        raise
