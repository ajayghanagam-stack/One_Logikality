"""Extractions endpoint tests (US-7.3 / US-7.4 — M3).

Covers `GET /api/packets/{id}/extractions`:
- Happy path: extractions seeded directly (the `extract_packet` stage is
  stubbed out in `conftest.py::_stub_extract`) come back grouped under
  their parent `EcvDocument` rows.
- Orphaned rows (document_id NULL) surface under the `Unassigned` bucket
  so re-classification doesn't hide real data.
- RLS isolation: a second org cannot read extractions belonging to the
  first via this endpoint.
- 404 for unknown packets.

Tests seed rows directly rather than round-tripping through the
Gemini Pro call — that path is covered by ruff / runtime import checks;
assertions here are about the API contract and RLS, not model output.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.models import EcvDocument, EcvExtraction, Packet
from app.security import hash_password


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    tmp = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(settings, "storage_path", str(tmp))
    yield tmp


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _upload_and_wait(client: AsyncClient, token: str) -> str:
    files = {"files": ("doc.pdf", io.BytesIO(b"%PDF-1.4\nfake"), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    packet_id = resp.json()["id"]
    for _ in range(50):
        fetch = await client.get(
            f"/api/packets/{packet_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if fetch.status_code == 200 and fetch.json()["status"] == "completed":
            return packet_id
        await asyncio.sleep(0.02)
    raise AssertionError("stub never reached `completed`")


async def _cleanup_packets(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM packets WHERE org_id = :o"), {"o": org_id})
        await session.commit()


async def _seed_extraction(
    *,
    packet_id: uuid.UUID,
    org_id: uuid.UUID,
    document_id: uuid.UUID | None,
    mismo_path: str,
    value: str,
    page_number: int | None,
    snippet: str | None,
    confidence: int = 95,
) -> None:
    """Insert one `EcvExtraction` row via SessionLocal (bypasses RLS)."""
    entity, _, field = mismo_path.rpartition(".")
    top_entity = entity.split(".")[-1].split("[")[0] if entity else field
    async with SessionLocal() as session:
        session.add(
            EcvExtraction(
                packet_id=packet_id,
                org_id=org_id,
                document_id=document_id,
                mismo_path=mismo_path,
                entity=top_entity,
                field=field,
                value=value,
                confidence=confidence,
                page_number=page_number,
                snippet=snippet,
            )
        )
        await session.commit()


async def _first_document_id(packet_id: uuid.UUID) -> uuid.UUID:
    """Return the doc_number=1 `EcvDocument` row for a packet."""
    async with SessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT id FROM ecv_documents WHERE packet_id = :p AND doc_number = 1"),
                {"p": packet_id},
            )
        ).one()
        return row[0]


# --- happy path -------------------------------------------------------


async def test_extractions_grouped_under_documents(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id_str = await _upload_and_wait(client, token)
    packet_id = uuid.UUID(packet_id_str)

    doc_id = await _first_document_id(packet_id)
    try:
        await _seed_extraction(
            packet_id=packet_id,
            org_id=seeded["org_id"],
            document_id=doc_id,
            mismo_path="DEAL.LOANS.LOAN[1].TERMS_OF_LOAN.LoanAmount",
            value="$400,000.00",
            page_number=2,
            snippet="Loan Amount: $400,000.00",
        )
        await _seed_extraction(
            packet_id=packet_id,
            org_id=seeded["org_id"],
            document_id=doc_id,
            mismo_path="DEAL.PARTIES.PARTY[1].INDIVIDUAL.NAME.FullName",
            value="JANE Q PUBLIC",
            page_number=1,
            snippet="Borrower Name: JANE Q PUBLIC",
        )

        resp = await client.get(
            f"/api/packets/{packet_id}/extractions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()

        assert payload["packet_id"] == packet_id_str
        assert len(payload["documents"]) == 1
        group = payload["documents"][0]
        assert group["document_id"] == str(doc_id)
        assert group["doc_number"] == 1
        # Sorted by mismo_path — DEAL.LOANS... comes before DEAL.PARTIES...
        paths = [e["mismo_path"] for e in group["extractions"]]
        assert paths == [
            "DEAL.LOANS.LOAN[1].TERMS_OF_LOAN.LoanAmount",
            "DEAL.PARTIES.PARTY[1].INDIVIDUAL.NAME.FullName",
        ]
        loan_row = group["extractions"][0]
        assert loan_row["value"] == "$400,000.00"
        assert loan_row["page_number"] == 2
        assert loan_row["snippet"] == "Loan Amount: $400,000.00"
        # `_seed_extraction` derives entity from the path's last segment
        # before the leaf — good enough for API-shape assertions here.
        assert loan_row["entity"] == "TERMS_OF_LOAN"
        assert loan_row["field"] == "LoanAmount"
        assert loan_row["confidence"] == 95
    finally:
        await _cleanup_packets(seeded["org_id"])


async def test_extractions_orphan_rows_surface_as_unassigned(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Rows whose `document_id` is NULL (SET NULL on re-classify) get
    their own group rather than being silently dropped."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id_str = await _upload_and_wait(client, token)
    packet_id = uuid.UUID(packet_id_str)

    try:
        await _seed_extraction(
            packet_id=packet_id,
            org_id=seeded["org_id"],
            document_id=None,
            mismo_path="DEAL.COLLATERALS.COLLATERAL[1].PROPERTY.StreetAddress",
            value="123 MAIN ST",
            page_number=None,
            snippet=None,
        )
        resp = await client.get(
            f"/api/packets/{packet_id}/extractions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        groups = resp.json()["documents"]
        assert len(groups) == 1
        orphan = groups[0]
        assert orphan["document_id"] is None
        assert orphan["doc_number"] is None
        assert orphan["name"] is None
        assert orphan["extractions"][0]["value"] == "123 MAIN ST"
    finally:
        await _cleanup_packets(seeded["org_id"])


async def test_extractions_empty_when_no_rows(client: AsyncClient, seeded, storage_tmp) -> None:
    """With the extractor stubbed out, a completed packet has zero
    extraction rows — the endpoint returns 200 + empty list, not 404."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id_str = await _upload_and_wait(client, token)

    try:
        resp = await client.get(
            f"/api/packets/{packet_id_str}/extractions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"packet_id": packet_id_str, "documents": []}
    finally:
        await _cleanup_packets(seeded["org_id"])


# --- RLS / auth -------------------------------------------------------


async def test_extractions_isolated_across_orgs(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id_str = await _upload_and_wait(client, token)
    packet_id = uuid.UUID(packet_id_str)

    doc_id = await _first_document_id(packet_id)
    await _seed_extraction(
        packet_id=packet_id,
        org_id=seeded["org_id"],
        document_id=doc_id,
        mismo_path="DEAL.LOANS.LOAN[1].TERMS_OF_LOAN.LoanAmount",
        value="$400,000.00",
        page_number=1,
        snippet=None,
    )

    other_org = uuid.uuid4()
    other_user = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    other_email = f"ext-other-{suffix}@other.test"
    other_pw = "pw-other"
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, type) "
                "VALUES (:id, :name, :slug, 'Mortgage Lender')"
            ),
            {"id": other_org, "name": f"Other {suffix}", "slug": f"ext-other-{suffix}"},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, org_id) "
                "VALUES (:id, :email, :pw, :name, 'customer_admin', :org)"
            ),
            {
                "id": other_user,
                "email": other_email,
                "pw": hash_password(other_pw),
                "name": "Other Admin",
                "org": other_org,
            },
        )
        await session.commit()

    try:
        other_token = await _login(client, other_email, other_pw)
        resp = await client.get(
            f"/api/packets/{packet_id_str}/extractions",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        # RLS hides the packet row entirely from the other org — that's
        # the first gate, so we never reach the extraction lookup.
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_user})
            await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": other_org})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])


async def test_extractions_requires_auth(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id_str = await _upload_and_wait(client, token)

    try:
        resp = await client.get(f"/api/packets/{packet_id_str}/extractions")
        assert resp.status_code == 401
    finally:
        await _cleanup_packets(seeded["org_id"])


async def test_extractions_404_for_unknown_packet(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/extractions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# --- Packet import sanity --------------------------------------------


def test_packet_model_imports() -> None:
    """Smoke-check: the new EcvExtraction model and Packet still import
    cleanly alongside each other. Guards against circular-import
    regressions introduced by the extract pipeline module."""
    assert EcvDocument.__tablename__ == "ecv_documents"
    assert Packet.__tablename__ == "packets"
    assert EcvExtraction.__tablename__ == "ecv_extractions"
