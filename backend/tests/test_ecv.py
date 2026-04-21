"""ECV dashboard endpoint tests (US-3.5 – 3.10, 3.13).

Covers `GET /api/packets/{id}/ecv`:
- 404 for unknown packets and cross-org reads (RLS).
- Happy-path: after the stub finishes, the endpoint returns the full
  canned payload — 13 sections / 58 line items / 25 docs — plus a
  top-line summary the dashboard can render without re-aggregating.
- 409 while the packet is still processing (before the `score` stage
  has persisted any rows).
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
from app.pipeline.ecv_data import DOCUMENT_INVENTORY, ECV_LINE_ITEMS, ECV_SECTIONS
from app.security import hash_password


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    """Zero out the per-stage delay so the stub finishes before each
    POST response returns (httpx ASGI transport runs background tasks
    synchronously)."""
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
    """Upload a trivial packet and poll until the stub completes."""
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
        # CASCADE from packets takes out ecv_sections / documents /
        # line_items, so we only need to delete the packet rows.
        await session.execute(text("DELETE FROM packets WHERE org_id = :o"), {"o": org_id})
        await session.commit()


# --- happy path ------------------------------------------------------


async def test_ecv_dashboard_round_trip(client: AsyncClient, seeded, storage_tmp) -> None:
    """After the stub finishes, the dashboard endpoint returns the
    canned 13-section / 58-item / 25-doc payload plus a summary block."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["packet"]["id"] == packet_id
    assert payload["packet"]["status"] == "completed"

    expected_line_item_count = sum(len(v) for v in ECV_LINE_ITEMS.values())

    summary = payload["summary"]
    assert summary["auto_approve_threshold"] == 90
    assert summary["confidence_threshold"] == 85
    assert summary["critical_threshold"] == 50
    assert summary["total_items"] == expected_line_item_count
    # passed + review + critical must partition the line items.
    assert (
        summary["passed_items"] + summary["review_items"] + summary["critical_items"]
        == expected_line_item_count
    )
    assert summary["documents_found"] + summary["documents_missing"] == len(DOCUMENT_INVENTORY)
    # The canned data has exactly 2 missing docs (Radon + Flood).
    assert summary["documents_missing"] == 2
    # Rounded to 1dp; the canned weights roll up to ~89.0.
    assert 80.0 < summary["overall_score"] < 100.0

    # Sections line up 1:1 with the seed.
    assert len(payload["sections"]) == len(ECV_SECTIONS)
    assert [s["section_number"] for s in payload["sections"]] == [s["id"] for s in ECV_SECTIONS]
    # Each section carries its line items sorted by item_code.
    first = payload["sections"][0]
    assert first["name"] == ECV_SECTIONS[0]["name"]
    assert first["score"] == float(ECV_SECTIONS[0]["score"])
    assert [i["item_code"] for i in first["line_items"]] == [it["id"] for it in ECV_LINE_ITEMS[1]]

    # Document inventory echoes the seed, including the per-page
    # issues (blank_page / low_quality / rotated).
    assert len(payload["documents"]) == len(DOCUMENT_INVENTORY)
    by_num = {d["doc_number"]: d for d in payload["documents"]}
    assert by_num[6]["page_issue"]["type"] == "blank_page"
    assert by_num[8]["page_issue"]["type"] == "low_quality"
    assert by_num[11]["page_issue"]["type"] == "rotated"
    assert by_num[24]["status"] == "missing"
    assert by_num[24]["page_issue"] is None

    await _cleanup_packets(seeded["org_id"])


async def test_ecv_dashboard_requires_auth(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(f"/api/packets/{packet_id}/ecv")
    assert resp.status_code == 401
    await _cleanup_packets(seeded["org_id"])


async def test_ecv_dashboard_rejects_platform_admin(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    cust_email, cust_password = seeded["customer_admin"]
    cust_token = await _login(client, cust_email, cust_password)
    packet_id = await _upload_and_wait(client, cust_token)

    pf_email, pf_password = seeded["platform_admin"]
    pf_token = await _login(client, pf_email, pf_password)
    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {pf_token}"},
    )
    assert resp.status_code == 403
    await _cleanup_packets(seeded["org_id"])


# --- RLS -------------------------------------------------------------


async def test_ecv_dashboard_isolated_across_orgs(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    # Stand up a second org so we can try a cross-tenant read.
    other_org = uuid.uuid4()
    other_user = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    other_email = f"other-{suffix}@other.test"
    other_pw = "pw-other"
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, type) "
                "VALUES (:id, :name, :slug, 'Mortgage Lender')"
            ),
            {"id": other_org, "name": f"Other {suffix}", "slug": f"other-{suffix}"},
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
            f"/api/packets/{packet_id}/ecv",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_user})
            await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": other_org})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])


async def test_ecv_dashboard_404_for_unknown_packet(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# --- not-ready path --------------------------------------------------


async def test_ecv_dashboard_409_before_scoring(client: AsyncClient, seeded, storage_tmp) -> None:
    """A packet whose stub hasn't reached the `score` stage yet has no
    findings rows — the endpoint should say so with 409, not 500 and
    not a blank 200."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    # Insert a synthetic `uploaded` packet directly so we can hit the
    # endpoint before the stub ever runs.
    packet_id = uuid.uuid4()
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO packets (id, org_id, declared_program_id, status, created_by) "
                "VALUES (:id, :org, 'conventional', 'uploaded', :uid)"
            ),
            {
                "id": packet_id,
                "org": seeded["org_id"],
                "uid": seeded["customer_admin_id"],
            },
        )
        await session.commit()

    try:
        resp = await client.get(
            f"/api/packets/{packet_id}/ecv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert "not ready" in resp.json()["detail"]
    finally:
        await _cleanup_packets(seeded["org_id"])
