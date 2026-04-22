"""Packet review-state API tests (US-8.3 send-to-manual-review).

Covers:
- `POST /api/packets/{id}/review` happy path for each valid state, and
  that the decision shows up on subsequent packet GETs under the new
  `review` block with the reviewer's name + timestamp.
- Validation — unknown state → 400, missing / short notes on `rejected`
  → 400, NULL state (no decision yet) → review block omitted.
- Re-transition: approving a packet that was previously in manual review
  replaces the state and stamps a new `transitioned_at`.
- RLS: a user in a different org gets 404 (not 403) on POST, so existence
  doesn't leak across tenants.
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


async def test_review_block_absent_before_decision(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Fresh packet has no review decision → `review` is null on GET."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["review"] is None

    await _cleanup_packets(seeded["org_id"])


async def test_send_to_manual_review_happy_path(client: AsyncClient, seeded, storage_tmp) -> None:
    """Customer admin flags for manual review → review block appears
    with state, notes, and the admin's name on the next GET."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/review",
        json={
            "state": "pending_manual_review",
            "notes": "Low ECV score — escalating to senior underwriter.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review["state"] == "pending_manual_review"
    assert "senior underwriter" in review["notes"]
    assert review["transitioned_by_name"]  # primary admin seeded name
    assert review["transitioned_at"]

    # Persists across a fresh GET.
    fetch = await client.get(
        f"/api/packets/{packet_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    fetched_review = fetch.json()["review"]
    assert fetched_review["state"] == "pending_manual_review"
    assert fetched_review["transitioned_by_name"] == review["transitioned_by_name"]

    await _cleanup_packets(seeded["org_id"])


async def test_approve_then_reject_replaces_state(client: AsyncClient, seeded, storage_tmp) -> None:
    """Re-transition: approving and then rejecting swaps the state and
    updates the timestamp."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    approve = await client.post(
        f"/api/packets/{packet_id}/review",
        json={"state": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approve.status_code == 200
    first_ts = approve.json()["review"]["transitioned_at"]

    # Sleep a hair so the second transition's timestamp is strictly
    # greater than the first — we only compare for inequality.
    await asyncio.sleep(0.01)

    reject = await client.post(
        f"/api/packets/{packet_id}/review",
        json={
            "state": "rejected",
            "notes": "Income documents show conflicts that can't be reconciled.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reject.status_code == 200
    second = reject.json()["review"]
    assert second["state"] == "rejected"
    assert "income documents" in second["notes"].lower()
    assert second["transitioned_at"] != first_ts

    await _cleanup_packets(seeded["org_id"])


async def test_reject_requires_notes(client: AsyncClient, seeded, storage_tmp) -> None:
    """Rejecting without notes → 400. The rationale is part of the
    audit trail, so we require it up front."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    no_notes = await client.post(
        f"/api/packets/{packet_id}/review",
        json={"state": "rejected"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert no_notes.status_code == 400

    too_short = await client.post(
        f"/api/packets/{packet_id}/review",
        json={"state": "rejected", "notes": "bad"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert too_short.status_code == 400

    await _cleanup_packets(seeded["org_id"])


async def test_unknown_state_rejected(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/review",
        json={"state": "escalated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400

    await _cleanup_packets(seeded["org_id"])


async def test_review_404_cross_org(client: AsyncClient, seeded, storage_tmp) -> None:
    """A user in a different org cannot review this packet — RLS hides
    the row so the API returns 404, not 403."""
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
        resp = await client.post(
            f"/api/packets/{packet_id}/review",
            json={"state": "approved"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])


async def test_review_404_unknown_packet(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        f"/api/packets/{uuid.uuid4()}/review",
        json={"state": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
