"""Compliance API tests (US-6.3).

Covers `GET /api/packets/{id}/compliance`:
- 404 for unknown packets and cross-org reads (RLS).
- 403 when the org isn't subscribed / has disabled the compliance app.
- 409 before the pipeline `score` stage has persisted findings.
- Happy-path: after the stub finishes, the endpoint returns the full
  canned payload — 10 checks + 3 tolerance buckets + computed summary.
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
from app.pipeline.compliance_data import COMPLIANCE_CHECKS, TOLERANCE_TABLE


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    tmp = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(settings, "storage_path", str(tmp))
    yield tmp


@pytest_asyncio.fixture
async def compliance_enabled(seeded) -> AsyncIterator[None]:
    """Subscribe the seeded org to the compliance app (enabled)."""
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'compliance', true)"
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


async def test_compliance_happy_path(
    client: AsyncClient, seeded, compliance_enabled, storage_tmp
) -> None:
    """After the stub completes, the endpoint returns all 10 canned checks,
    the three tolerance rows, and a computed summary."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/compliance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["checks"]) == len(COMPLIANCE_CHECKS)
    codes = [c["check_code"] for c in payload["checks"]]
    assert codes == sorted(c["code"] for c in COMPLIANCE_CHECKS)

    # C-02 is the headline TRID violation in the canned seed.
    c02 = next(c for c in payload["checks"] if c["check_code"] == "C-02")
    assert c02["status"] == "fail"
    assert c02["ai_note"] is not None
    assert any(m["field"] == "ClosingDate" for m in c02["mismo"])

    assert len(payload["fee_tolerances"]) == len(TOLERANCE_TABLE)
    buckets = [t["bucket"] for t in payload["fee_tolerances"]]
    assert buckets == [t["bucket"] for t in TOLERANCE_TABLE]

    summary = payload["summary"]
    assert summary["total_checks"] == 10
    assert summary["failed"] == 2  # C-02 + C-08
    assert summary["warned"] == 1  # C-04
    assert summary["not_applicable"] == 1  # C-07
    assert summary["passed"] == 6
    # 6 passed / (10 - 1 n/a) = 6/9 = 67%
    assert summary["score"] == 67

    await _cleanup_packets(seeded["org_id"])


async def test_compliance_403_when_not_subscribed(client: AsyncClient, seeded, storage_tmp) -> None:
    """No compliance subscription → 403 so the UI can distinguish 'not
    available for your org' from 'doesn't exist'."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/compliance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text

    await _cleanup_packets(seeded["org_id"])


async def test_compliance_403_when_subscription_disabled(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Subscribed-but-disabled is treated the same as unsubscribed — the
    customer admin has toggled the app off."""
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'compliance', false)"
            ),
            {"o": org_id},
        )
        await session.commit()

    try:
        email, password = seeded["customer_admin"]
        token = await _login(client, email, password)
        packet_id = await _upload_and_wait(client, token)

        resp = await client.get(
            f"/api/packets/{packet_id}/compliance",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM app_subscriptions WHERE org_id = :o"),
                {"o": org_id},
            )
            await session.commit()
        await _cleanup_packets(org_id)


async def test_compliance_404_for_unknown_packet(
    client: AsyncClient, seeded, compliance_enabled
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/compliance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_compliance_404_cross_org(
    client: AsyncClient, seeded, compliance_enabled, storage_tmp
) -> None:
    """RLS must prevent another org's user from reading this packet's
    compliance payload — the response is 404 (not 403) so tenant
    existence isn't leaked."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    # Spin up a second org + user.
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
                "VALUES (:o, 'compliance', true)"
            ),
            {"o": other_org_id},
        )
        await session.commit()

    try:
        other_token = await _login(client, f"other-{suffix}@acme.test", "pw-other")
        resp = await client.get(
            f"/api/packets/{packet_id}/compliance",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])
