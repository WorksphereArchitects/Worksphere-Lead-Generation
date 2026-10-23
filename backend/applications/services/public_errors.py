"""Helpers for exposing bounded error summaries to API clients."""

from __future__ import annotations

import re


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@")


def safe_error_summary(value: object, fallback: str = "Operation failed.") -> str:
    """Return only a short first-line summary with common secrets redacted."""
    if not value:
        return fallback

    message = str(value).splitlines()[0].strip()
    if not message or "traceback (most recent call last)" in message.casefold():
        return fallback

    message = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", message)
    message = _BEARER_TOKEN.sub("Bearer [redacted]", message)
    message = _URL_CREDENTIALS.sub(r"\1[redacted]@", message)
    return message[:300]
