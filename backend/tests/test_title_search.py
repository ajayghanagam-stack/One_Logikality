"""Title Search & Abstraction API tests (US-6.1).

Covers `GET /api/packets/{id}/title-search`:
- 404 for unknown packets and cross-org reads (RLS).
- 403 when the org isn't subscribed / has disabled the title-search app.
- Happy-path: after the stub finishes, the endpoint returns the full
  canned payload — 7 flags + severity counts + property summary blob.
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
from app.pipeline.title_search_data import PROPERTY_SUMMARY, TITLE_FLAGS


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    tmp = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(settings, "storage_path", str(tmp))
    yield tmp


@pytest_asyncio.fixture
async def title_search_enabled(seeded) -> AsyncIterator[None]:
    """Subscribe the seeded org to the title-search app (enabled)."""
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'title-search', true)"
            ),
            {"o": org_id},
        )
        await session.commit()
    try:
        yield
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM app_subscriptions WHERE org_id = :o"),
                {"o": org_id},
            )
            await session.commit()


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


async def test_title_search_happy_path(
    client: AsyncClient, seeded, title_search_enabled, storage_tmp
) -> None:
    """After the stub completes, the endpoint returns all 7 canned flags,
    the severity counts, and the property summary blob."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-search",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # 7 flags, in order by sort_order (which matches TITLE_FLAGS).
    assert len(payload["flags"]) == len(TITLE_FLAGS)
    numbers = [f["number"] for f in payload["flags"]]
    assert numbers == [f["number"] for f in TITLE_FLAGS]

    # Severity rollup matches the demo mix: 2 critical, 2 high, 2 medium,
    # 1 low.
    counts = payload["severity_counts"]
    assert counts["critical"] == 2
    assert counts["high"] == 2
    assert counts["medium"] == 2
    assert counts["low"] == 1
    assert counts["total"] == 7

    # Flag 1 — unreleased mortgage, the headline critical finding.
    f1 = next(f for f in payload["flags"] if f["number"] == 1)
    assert f1["severity"] == "critical"
    assert f1["flag_type"] == "Unreleased Mortgage"
    assert f1["ai_rec"]["decision"] == "reject"
    assert f1["ai_rec"]["confidence"] == 97
    assert any(m["field"] for m in f1["mismo"])
    assert f1["source"]["doc_type"]
    assert len(f1["evidence"]) >= 1

    # Property summary round-trips as a dict with the expected keys.
    summary = payload["property_summary"]
    for key in (
        "property_identification",
        "physical_attributes",
        "chain_of_title",
        "mortgages",
        "liens",
        "taxes",
        "title_insurance",
    ):
        assert key in summary, f"missing property summary key: {key}"
    # The chain-of-title list is non-empty and preserves order.
    assert isinstance(summary["chain_of_title"], list)
    assert len(summary["chain_of_title"]) == len(PROPERTY_SUMMARY["chain_of_title"])

    await _cleanup_packets(seeded["org_id"])


async def test_title_search_403_when_not_subscribed(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """No title-search subscription → 403."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-search",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text

    await _cleanup_packets(seeded["org_id"])


async def test_title_search_404_for_unknown_packet(
    client: AsyncClient, seeded, title_search_enabled
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/title-search",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_title_search_404_cross_org(
    client: AsyncClient, seeded, title_search_enabled, storage_tmp
) -> None:
    """RLS must prevent another org's user from reading this packet's
    title-search payload — the response is 404 (not 403) so tenant
    existence isn't leaked."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    other_org_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    from app.security import hash_password

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
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'title-search', true)"
            ),
            {"o": other_org_id},
        )
        await session.commit()

    try:
        other_token = await _login(client, f"other-{suffix}@acme.test", "pw-other")
        resp = await client.get(
            f"/api/packets/{packet_id}/title-search",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])
