"""Shared PDF page loading utilities for the micro-app pipeline stages.

The classify stage loads pages truncated to 400 chars/page (enough to
identify document types). The extract stage uses 4 000 chars/page. The
micro-app derivation pipelines need the *full* page text — legal language
in title commitments and income documents cannot be meaningfully analysed
from 400-char snippets.

Exports `load_doc_pages(packet_id, mismo_types, max_chars)` which reads every
uploaded PDF for a packet, slices to the page ranges belonging to the
requested document types (using the `EcvDocument` rows written by classify),
and returns the assembled text up to `max_chars` per page.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from typing import Sequence

from pypdf import PdfReader
from sqlalchemy import select

from app.adapters.storage_local import get_storage
from app.db import SessionLocal
from app.models import EcvDocument, PacketFile
from app.pipeline.extract import _parse_pages_range

log = logging.getLogger(__name__)

_DEFAULT_MAX_CHARS = 8000


async def load_doc_pages(
    packet_id: uuid.UUID,
    mismo_types: Sequence[str],
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> list[tuple[int, str]]:
    """Return (page_number, text) pairs for pages belonging to the given
    MISMO document types within `packet_id`.

    Pages are sourced by:
    1. Reading the classified `EcvDocument` rows to find which page ranges
       belong to each requested MISMO type.
    2. Loading all uploaded PDFs and extracting text with pypdf.
    3. Slicing to the identified ranges, truncating each page to `max_chars`.

    Returns an empty list if no documents of the requested types were
    classified or if pypdf extracted no text from those pages.
    """
    async with SessionLocal() as session:
        docs = (
            (
                await session.execute(
                    select(EcvDocument)
                    .where(EcvDocument.packet_id == packet_id)
                    .where(EcvDocument.mismo_type.in_(list(mismo_types)))
                    .where(EcvDocument.status == "found")
                    .order_by(EcvDocument.doc_number)
                )
            )
            .scalars()
            .all()
        )
        files = (
            (
                await session.execute(
                    select(PacketFile)
                    .where(PacketFile.packet_id == packet_id)
                    .order_by(PacketFile.created_at)
                )
            )
            .scalars()
            .all()
        )

    if not docs:
        return []

    storage = get_storage()
    raw_pages: dict[int, str] = {}
    global_page = 1
    for f in files:
        if f.content_type not in ("application/pdf", "application/x-pdf"):
            continue
        try:
            data = await storage.get(f.storage_key)
        except Exception:
            log.exception("page_utils: failed to read %s", f.storage_key)
            continue
        extracted = await asyncio.to_thread(_read_pdf, data)
        for text in extracted:
            raw_pages[global_page] = text
            global_page += 1

    if not raw_pages:
        return []

    result: list[tuple[int, str]] = []
    seen_pages: set[int] = set()
    for doc in docs:
        page_range = _parse_pages_range(doc.pages_display)
        if page_range is None:
            continue
        first, last = page_range
        for n in range(first, last + 1):
            if n in seen_pages:
                continue
            text = raw_pages.get(n, "")
            if text:
                result.append((n, text[:max_chars]))
                seen_pages.add(n)

    result.sort(key=lambda t: t[0])
    return result


def _read_pdf(data: bytes) -> list[str]:
    """Extract full text from each page of a PDF. Returns one string per
    page; empty string for image-only or corrupt pages."""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        log.exception("page_utils: pypdf failed to open PDF (%d bytes)", len(data))
        return []
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text.strip())
    return pages
