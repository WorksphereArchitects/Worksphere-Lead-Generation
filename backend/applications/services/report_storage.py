"""Durable Supabase Storage helpers for annual-report PDFs."""

from __future__ import annotations

import hashlib
from pathlib import Path

from applications.services.supabase_client import supabase

BUCKET = "annual-reports"


def object_path(report_id: str) -> str:
    return f"reports/{report_id}.pdf"


def download_report(report_id: str, destination: Path) -> Path | None:
    path = object_path(report_id)
    try:
        content = supabase.storage.from_(BUCKET).download(path)
    except Exception:
        return None
    if not content or not bytes(content).startswith(b"%PDF-"):
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bytes(content))
    return destination


def upload_report(report_id: str, file_path: Path) -> dict[str, str | int]:
    content = file_path.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise ValueError("Cannot persist a non-PDF annual report.")
    path = object_path(report_id)
    supabase.storage.from_(BUCKET).upload(
        path,
        content,
        {"content-type": "application/pdf", "upsert": "false"},
    )
    return {
        "bucket": BUCKET,
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
