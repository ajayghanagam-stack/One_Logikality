"""Test-only canned-data seed helpers.

Before M4 the ECV pipeline persisted canned rows from
`app.pipeline.ecv_data` for every packet. M4 replaced that with real
classify / extract / validate stages; the canned tuples remain in
`app.pipeline.ecv_data` solely as test fixtures, and this module owns
the insertion helpers that use them.

Tests that need a fully-populated ECV dashboard (sections + line items
+ documents) call `seed_canned_ecv(packet_id, org_id)` in their setup
rather than expecting the pipeline to write the rows.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EcvDocument, EcvLineItem, EcvSection
from app.pipeline.ecv_data import DOCUMENT_INVENTORY, ECV_LINE_ITEMS, ECV_SECTIONS


async def seed_canned_sections(
    session: AsyncSession, *, packet_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Insert the canned 13 sections + 58 line items for a packet.

    Writes happen inside the caller's session and are NOT committed here
    — the caller is responsible for `session.commit()` so tests can batch
    multiple seed helpers into one transaction if they want.
    """
    section_rows = [
        EcvSection(
            packet_id=packet_id,
            org_id=org_id,
            section_number=sec["id"],
            name=sec["name"],
            weight=sec["weight"],
            score=sec["score"],
        )
        for sec in ECV_SECTIONS
    ]
    session.add_all(section_rows)
    await session.flush()

    section_by_number = {s.section_number: s for s in section_rows}
    line_item_rows: list[EcvLineItem] = []
    for section_number, items in ECV_LINE_ITEMS.items():
        parent = section_by_number[section_number]
        for item in items:
            line_item_rows.append(
                EcvLineItem(
                    section_id=parent.id,
                    packet_id=packet_id,
                    org_id=org_id,
                    item_code=item["id"],
                    check_description=item["check"],
                    result_text=item["result"],
                    confidence=item["confidence"],
                )
            )
    session.add_all(line_item_rows)


async def seed_canned_documents(
    session: AsyncSession, *, packet_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Insert the canned 25-doc MISMO inventory for a packet.

    Used by app-gating tests that depend on `STATE_DISCLOSURE` being
    `missing` (drives the compliance-blocked case), and by any other
    test that asserts against the canned document counts.
    """
    doc_rows: list[EcvDocument] = []
    for doc in DOCUMENT_INVENTORY:
        issue = doc.get("page_issue")
        doc_rows.append(
            EcvDocument(
                packet_id=packet_id,
                org_id=org_id,
                doc_number=doc["id"],
                name=doc["name"],
                mismo_type=doc["mismo_type"],
                pages_display=doc["pages"],
                page_count=doc["page_count"],
                confidence=doc["confidence"],
                status=doc["status"],
                category=doc["category"],
                page_issue_type=issue["type"] if issue else None,
                page_issue_detail=issue["detail"] if issue else None,
                page_issue_affected_page=issue["affected_page"] if issue else None,
            )
        )
    session.add_all(doc_rows)


async def seed_canned_ecv(
    session: AsyncSession, *, packet_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Seed both sections+items and documents in one call. Still does
    not commit — caller owns the transaction boundary."""
    await seed_canned_sections(session, packet_id=packet_id, org_id=org_id)
    await seed_canned_documents(session, packet_id=packet_id, org_id=org_id)
