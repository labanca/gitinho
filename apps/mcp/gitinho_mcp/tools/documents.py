"""Document → markdown conversion via the MarkItDown library.

Called by the chat app when a user uploads a PDF/DOCX/PPTX/XLSX so the
LLM gets a markdown preview prepended to the message. Conversion runs
locally — no external service required.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import tempfile
from pathlib import Path
from typing import Any

from markitdown import MarkItDown

from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import get_context

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".rtf",
    ".odt",
    ".epub",
    ".html",
    ".htm",
    ".md",
    ".txt",
}


def _ext_from_filename(filename: str) -> str:
    return Path(filename).suffix.lower()


def _convert_sync(path: str) -> str:
    md = MarkItDown()
    return md.convert(path).text_content


@mcp.tool()
async def convert_document(
    content_base64: str,
    filename: str,
) -> dict[str, Any]:
    """Convert a document (PDF, DOCX, PPTX, XLSX, etc.) to markdown.

    Receives the file as base64 and a filename (extension is used to
    pick the right parser). Returns a dict with the markdown content and
    metadata. Errors return `{"ok": false, "error": "..."}` instead of
    raising — the chat app should degrade gracefully if conversion fails.

    Size cap is `DOCUMENT_INGEST_MAX_MB` (default 25 MB). Larger inputs
    are rejected before decoding.
    """
    ctx = await get_context()
    max_bytes = ctx.settings.DOCUMENT_INGEST_MAX_MB * 1024 * 1024

    if len(content_base64) > max_bytes * 4 // 3 + 64:
        return {
            "ok": False,
            "error": f"file exceeds {ctx.settings.DOCUMENT_INGEST_MAX_MB} MB limit",
            "filename": filename,
        }

    ext = _ext_from_filename(filename)
    if ext not in _SUPPORTED_EXTENSIONS:
        return {
            "ok": False,
            "error": f"unsupported extension '{ext}'",
            "filename": filename,
        }

    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return {"ok": False, "error": f"invalid base64: {exc}", "filename": filename}

    if len(raw) > max_bytes:
        return {
            "ok": False,
            "error": f"file exceeds {ctx.settings.DOCUMENT_INGEST_MAX_MB} MB limit",
            "filename": filename,
        }

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        markdown = await asyncio.to_thread(_convert_sync, tmp_path)
    except Exception as exc:  # noqa: BLE001 — surface conversion errors as data
        return {
            "ok": False,
            "error": f"conversion failed: {exc.__class__.__name__}: {exc}",
            "filename": filename,
        }
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "ok": True,
        "filename": filename,
        "size_bytes": len(raw),
        "markdown": markdown,
    }
