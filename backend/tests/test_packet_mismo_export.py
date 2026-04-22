"""ECV MISMO 3.6 XML export tests (US-8.2).

Covers:
- Happy path: customer admin downloads the XML; response is well-formed
  MISMO 3.6 with the expected DEAL_SETS/DEAL/LOAN/DOCUMENT structure
  and a Logikality-namespaced EXTENSION block.
- Document inventory is represented with MISMO document classifications.
- Review decision lands in the EXTENSION when the packet has been acted
  on (feedback loop for US-8.3).
- RLS: cross-org fetch returns 404, not 403.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.security import hash_password

_MISMO_NS = "http://www.mismo.org/residential/2009/schemas"
_LOGIKALITY_NS = "https://logikality.com/schemas/ecv/1"


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
    resp = await client.post(
        "/api/packets",
        data={"declared_program_id": "conventional"},
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


def _q(tag: str, ns: str = _MISMO_NS) -> str:
    return f"{{{ns}}}{tag}"


async def test_export_mismo_happy_path(client: AsyncClient, seeded, storage_tmp) -> None:
    """Customer admin downloads the MISMO XML — response is well-formed
    XML with the MESSAGE envelope and the DEAL_SET/LOAN/DOCUMENT tree
    the downstream integrations expect."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/export/mismo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/xml")
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert f"ecv-mismo-{packet_id[:8]}.xml" in disposition

    # Parse and sanity-check the structure.
    root = ET.fromstring(resp.content)
    assert root.tag == _q("MESSAGE")
    assert root.attrib.get("MISMOReferenceModelIdentifier") == "3.6.0"

    version = root.find(f"{_q('ABOUT_VERSIONS')}/{_q('ABOUT_VERSION')}")
    assert version is not None
    assert version.findtext(_q("DataVersionIdentifier")) == "3.6.0"

    loan = root.find(
        f"{_q('DEAL_SETS')}/{_q('DEAL_SET')}/{_q('DEALS')}/{_q('DEAL')}/{_q('LOANS')}/{_q('LOAN')}"
    )
    assert loan is not None
    # The declared program was "conventional" at upload → MortgageType is Conventional.
    assert loan.findtext(f"{_q('TERMS_OF_LOAN')}/{_q('MortgageType')}") == "Conventional"
    # Packet UUID surfaces as the lender loan identifier.
    assert (
        loan.findtext(f"{_q('LOAN_IDENTIFIERS')}/{_q('LOAN_IDENTIFIER')}/{_q('LoanIdentifier')}")
        == packet_id
    )

    documents = root.findall(
        f"{_q('DEAL_SETS')}/{_q('DEAL_SET')}/{_q('DEALS')}/{_q('DEAL')}/"
        f"{_q('DOCUMENT_SETS')}/{_q('DOCUMENT_SET')}/{_q('DOCUMENTS')}/{_q('DOCUMENT')}"
    )
    assert len(documents) > 0, "inventory should include at least one classified doc"

    ecv_ext = root.find(
        f"{_q('DEAL_SETS')}/{_q('DEAL_SET')}/{_q('DEALS')}/{_q('DEAL')}/"
        f"{_q('EXTENSION')}/{_q('OTHER')}/{_q('ECV_VALIDATION', _LOGIKALITY_NS)}"
    )
    assert ecv_ext is not None
    overall = ecv_ext.findtext(_q("OverallScorePercent", _LOGIKALITY_NS))
    assert overall is not None and 0 <= float(overall) <= 100

    await _cleanup_packets(seeded["org_id"])


async def test_export_mismo_includes_review_decision(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Once a reviewer acts on the packet, the decision rides in the
    Logikality EXTENSION so downstream consumers see it alongside the
    ECV findings."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    review = await client.post(
        f"/api/packets/{packet_id}/review",
        json={
            "state": "rejected",
            "notes": "Income documents show conflicts that can't be reconciled.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert review.status_code == 200, review.text

    resp = await client.get(
        f"/api/packets/{packet_id}/export/mismo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    review_el = root.find(
        f"{_q('DEAL_SETS')}/{_q('DEAL_SET')}/{_q('DEALS')}/{_q('DEAL')}/"
        f"{_q('EXTENSION')}/{_q('OTHER')}/{_q('ECV_VALIDATION', _LOGIKALITY_NS)}/"
        f"{_q('ReviewDecision', _LOGIKALITY_NS)}"
    )
    assert review_el is not None
    assert review_el.findtext(_q("State", _LOGIKALITY_NS)) == "rejected"
    assert "income documents" in (review_el.findtext(_q("Notes", _LOGIKALITY_NS)) or "").lower()

    await _cleanup_packets(seeded["org_id"])


async def test_export_mismo_404_unknown_packet(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/export/mismo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_export_mismo_404_cross_org(client: AsyncClient, seeded, storage_tmp) -> None:
    """A user in a different org cannot download the XML — RLS hides the
    row, so the API returns 404, not 403."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    other_org_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]

    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, type) "
                "VALUES (:id, :name, :slug, 'Mortgage Lender')"
            ),
            {"id": other_org_id, "name": f"Other Org {suffix}", "slug": f"other-{suffix}"},
        )
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, full_name, role, org_id, is_primary_admin) "
                "VALUES (:id, :email, :pw, :name, 'customer_admin', :org, true)"
            ),
            {
                "id": other_user_id,
                "email": f"other-{suffix}@acme.test",
                "pw": hash_password("pw-other"),
                "name": "Other Admin",
                "org": other_org_id,
            },
        )
        await session.commit()

    try:
        other_token = await _login(client, f"other-{suffix}@acme.test", "pw-other")
        resp = await client.get(
            f"/api/packets/{packet_id}/export/mismo",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])
