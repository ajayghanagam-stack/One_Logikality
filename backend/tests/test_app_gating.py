"""App-gating tests (US-5.1 / US-5.2 / US-5.3).

Covers `GET /api/packets/{id}/ecv`'s `app_gating` field:
- Subscribed+enabled apps appear; unsubscribed apps are omitted.
- Disabled subscriptions are omitted (they're not launchable).
- An app whose required MISMO types are all present → `ready` with
  empty `missing_docs`.
- An app with a missing required MISMO type → `blocked`, with the
  missing entry in `missing_docs` carrying mismo_type + name + reason.
- ECV itself has no manifest and always reports `ready`.

The seeded canned inventory has `STATE_DISCLOSURE` as `missing`, which
is the key lever the compliance-blocked case depends on.
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


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    tmp = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(settings, "storage_path", str(tmp))
    yield tmp


@pytest_asyncio.fixture
async def subscriptions(seeded) -> AsyncIterator[None]:
    """Subscribe the seeded org to a representative mix of apps.

    - ecv: enabled (foundational — will land in the payload with no
      manifest, always `ready`).
    - compliance: enabled — its manifest lists `STATE_DISCLOSURE`,
      which the canned inventory ships as `missing`, so this is the
      blocked case.
    - income-calc: enabled — every required doc type is present in the
      canned inventory, so this is the ready case.
    - title-search: subscribed but **disabled** — should be omitted.
    - title-exam: never subscribed — should be omitted.
    """
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'ecv', true), (:o, 'compliance', true), "
                "(:o, 'income-calc', true), (:o, 'title-search', false)"
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


async def test_app_gating_includes_only_enabled_subscriptions(
    client: AsyncClient, seeded, subscriptions, storage_tmp
) -> None:
    """Only subscribed+enabled apps are gating candidates. `title-search`
    is subscribed-but-disabled; `title-exam` is never subscribed. Both
    should be absent from the payload."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    app_ids = {g["app_id"] for g in resp.json()["app_gating"]}
    assert app_ids == {"ecv", "compliance", "income-calc"}

    await _cleanup_packets(seeded["org_id"])


async def test_compliance_blocked_by_missing_state_disclosure(
    client: AsyncClient, seeded, subscriptions, storage_tmp
) -> None:
    """Compliance needs STATE_DISCLOSURE; the canned inventory ships it
    as `missing`. Expect `blocked` + one missing-doc entry with a
    human-readable name and the manifest reason."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    gating_by_id = {g["app_id"]: g for g in resp.json()["app_gating"]}
    compliance = gating_by_id["compliance"]
    assert compliance["status"] == "blocked"
    missing_types = [m["mismo_type"] for m in compliance["missing_docs"]]
    assert missing_types == ["STATE_DISCLOSURE"]
    missing = compliance["missing_docs"][0]
    assert missing["name"] == "State-specific Disclosure"
    assert "state-specific" in missing["reason"].lower()

    await _cleanup_packets(seeded["org_id"])


async def test_income_calc_ready_when_all_docs_present(
    client: AsyncClient, seeded, subscriptions, storage_tmp
) -> None:
    """Income-calc's manifest is fully satisfied by the canned inventory,
    so the app reports `ready` with an empty missing list."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    gating_by_id = {g["app_id"]: g for g in resp.json()["app_gating"]}
    income = gating_by_id["income-calc"]
    assert income["status"] == "ready"
    assert income["missing_docs"] == []

    await _cleanup_packets(seeded["org_id"])


async def test_ecv_app_is_always_ready(
    client: AsyncClient, seeded, subscriptions, storage_tmp
) -> None:
    """ECV has no required-docs manifest — it processes whatever is
    uploaded and is the source of other apps' inventories, so gating
    ECV on ECV output would be circular."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    ecv = next(g for g in resp.json()["app_gating"] if g["app_id"] == "ecv")
    assert ecv["status"] == "ready"
    assert ecv["missing_docs"] == []

    await _cleanup_packets(seeded["org_id"])


async def test_app_gating_empty_when_no_subscriptions(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """An org with no subscriptions at all gets an empty `app_gating`
    list — the launcher panel simply has nothing to show."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/ecv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["app_gating"] == []

    await _cleanup_packets(seeded["org_id"])
