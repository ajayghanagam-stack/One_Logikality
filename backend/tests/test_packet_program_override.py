"""Packet-level loan-program confirmation + override tests (US-3.11 / US-3.12).

Covers:
- ECV pipeline persists a confirmation verdict keyed off the declared
  program (conventional → confirmed; fha → conflict + suggested).
- `POST /api/packets/{id}/program-override` happy path: a customer
  admin can change the effective program and the override shows up on
  the next GET (`packet.program_override` includes the overrider's
  full name).
- Validation: unknown program ids → 400, short reason → 400.
- AuthZ: 401 unauth, 403 for customer_user + platform_admin, 404
  cross-org (RLS).
- `DELETE /api/packets/{id}/program-override` clears the four fields.
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


async def _upload_and_wait(
    client: AsyncClient, token: str, program_id: str = "conventional"
) -> str:
    files = {"files": ("doc.pdf", io.BytesIO(b"%PDF-1.4\nfake"), "application/pdf")}
    resp = await client.post(
        "/api/packets",
        data={"declared_program_id": program_id},
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


# --- confirmation persistence ----------------------------------------


async def test_confirmation_confirmed_for_conventional(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Conventional declaration → ECV stamps a `confirmed` verdict with
    no suggested alternative."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token, program_id="conventional")

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    conf = resp.json()["packet"]["program_confirmation"]
    assert conf is not None
    assert conf["status"] == "confirmed"
    assert conf["suggested_program_id"] is None
    assert "conforming" in conf["evidence"].lower()
    assert "Note" in conf["documents_analyzed"]

    await _cleanup_packets(seeded["org_id"])


async def test_confirmation_conflict_for_fha(client: AsyncClient, seeded, storage_tmp) -> None:
    """FHA declaration on a packet whose documents don't evidence FHA
    → `conflict` + suggested = `conventional`."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token, program_id="fha")

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    conf = resp.json()["packet"]["program_confirmation"]
    assert conf["status"] == "conflict"
    assert conf["suggested_program_id"] == "conventional"

    await _cleanup_packets(seeded["org_id"])


# --- override happy path ---------------------------------------------


async def test_override_happy_path(client: AsyncClient, seeded, storage_tmp) -> None:
    """Customer admin changes the declared program to FHA with a reason
    → override block appears on the dashboard with the admin's name."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token, program_id="conventional")

    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "Loan officer confirmed FHA refinance."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    override = resp.json()["program_override"]
    assert override["program_id"] == "fha"
    assert override["reason"] == "Loan officer confirmed FHA refinance."
    assert override["overridden_by_name"] is not None  # seed admin has a full_name

    # And it surfaces on the dashboard too.
    dash = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert dash.status_code == 200
    assert dash.json()["packet"]["program_override"]["program_id"] == "fha"

    await _cleanup_packets(seeded["org_id"])


async def test_override_delete_clears(client: AsyncClient, seeded, storage_tmp) -> None:
    """DELETE wipes all four override fields."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    post = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "Revised program per loan officer."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post.status_code == 200

    delete = await client.delete(
        f"/api/packets/{packet_id}/program-override",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete.status_code == 200
    assert delete.json()["program_override"] is None

    await _cleanup_packets(seeded["org_id"])


async def test_override_delete_is_idempotent(client: AsyncClient, seeded, storage_tmp) -> None:
    """Reverting a packet with no override returns 200 and null override."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.delete(
        f"/api/packets/{packet_id}/program-override",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["program_override"] is None

    await _cleanup_packets(seeded["org_id"])


# --- validation ------------------------------------------------------


async def test_override_rejects_unknown_program(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "not-a-real-program", "reason": "Long enough reason."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "unknown program id" in resp.json()["detail"]

    await _cleanup_packets(seeded["org_id"])


async def test_override_rejects_short_reason(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "ok"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "at least" in resp.json()["detail"]

    await _cleanup_packets(seeded["org_id"])


# --- authz / RLS ------------------------------------------------------


async def test_override_requires_auth(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "Some reason."},
    )
    assert resp.status_code == 401
    await _cleanup_packets(seeded["org_id"])


async def test_override_rejects_customer_user(client: AsyncClient, seeded, storage_tmp) -> None:
    """Per Plan.md, packet-level overrides swap the whole rule baseline
    — that's a customer-admin-level call, not a customer-user call."""
    admin_email, admin_pw = seeded["customer_admin"]
    admin_token = await _login(client, admin_email, admin_pw)
    packet_id = await _upload_and_wait(client, admin_token)

    user_email, user_pw = seeded["customer_user"]
    user_token = await _login(client, user_email, user_pw)
    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "Regular user should be blocked."},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403
    await _cleanup_packets(seeded["org_id"])


async def test_override_rejects_platform_admin(client: AsyncClient, seeded, storage_tmp) -> None:
    cust_email, cust_pw = seeded["customer_admin"]
    cust_token = await _login(client, cust_email, cust_pw)
    packet_id = await _upload_and_wait(client, cust_token)

    pf_email, pf_pw = seeded["platform_admin"]
    pf_token = await _login(client, pf_email, pf_pw)
    resp = await client.post(
        f"/api/packets/{packet_id}/program-override",
        json={"program_id": "fha", "reason": "Platform admin shouldn't touch this."},
        headers={"Authorization": f"Bearer {pf_token}"},
    )
    assert resp.status_code == 403
    await _cleanup_packets(seeded["org_id"])


async def test_override_cross_org_is_404(client: AsyncClient, seeded, storage_tmp) -> None:
    """RLS: an admin in another org can't see — or override — someone
    else's packet."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

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
        resp = await client.post(
            f"/api/packets/{packet_id}/program-override",
            json={"program_id": "fha", "reason": "Cross-org attempt should fail."},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_user})
            await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": other_org})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])
