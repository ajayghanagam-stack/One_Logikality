"""Customer-admin app-access tests (US-2.5 / US-2.6).

Exercises GET/PATCH on `/api/customer-admin/apps`. Each test seeds
a fresh org via `seeded` and inserts a handful of subscription rows
directly; the `seeded` fixture doesn't provision subscriptions
because other tests in the suite don't need them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.db import SessionLocal


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def seeded_with_subs(seeded) -> AsyncIterator[dict]:
    """Add ECV + compliance + title-search subscriptions to the seeded org.

    Picked that mix on purpose:
      - ECV: required app; disable attempts must 400.
      - compliance: disabled on creation so we can verify GET echoes the
        stored flag, not a default.
      - title-search: enabled; we'll flip it in the PATCH tests.
    """
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'ecv', true), (:o, 'compliance', false), "
                "(:o, 'title-search', true)"
            ),
            {"o": org_id},
        )
        await session.commit()
    try:
        yield seeded
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM app_subscriptions WHERE org_id = :o"),
                {"o": org_id},
            )
            await session.commit()


# --- GET /apps ---------------------------------------------------------


async def test_list_apps_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/customer-admin/apps")
    assert resp.status_code == 401


async def test_list_apps_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/apps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_apps_rejects_platform_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/apps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_apps_returns_every_app_with_state(
    client: AsyncClient, seeded_with_subs
) -> None:
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/apps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = {r["id"]: r for r in resp.json()}
    # Every app id from APP_IDS should appear.
    assert set(rows) == {"ecv", "title-search", "title-exam", "compliance", "income-calc"}
    # Subscribed + enabled (fixture).
    assert rows["ecv"] == {"id": "ecv", "subscribed": True, "enabled": True}
    assert rows["title-search"] == {"id": "title-search", "subscribed": True, "enabled": True}
    # Subscribed but disabled.
    assert rows["compliance"] == {"id": "compliance", "subscribed": True, "enabled": False}
    # Not subscribed → enabled is always false regardless.
    assert rows["title-exam"] == {"id": "title-exam", "subscribed": False, "enabled": False}
    assert rows["income-calc"] == {"id": "income-calc", "subscribed": False, "enabled": False}


async def test_list_apps_empty_when_no_subs(client: AsyncClient, seeded) -> None:
    # `seeded` alone has no subscription rows — every app should read as
    # subscribed=false, enabled=false.
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/apps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert all(r["subscribed"] is False and r["enabled"] is False for r in resp.json())


# --- PATCH /apps/{id} --------------------------------------------------


async def test_patch_app_requires_auth(client: AsyncClient) -> None:
    resp = await client.patch(
        "/api/customer-admin/apps/title-search",
        json={"enabled": False},
    )
    assert resp.status_code == 401


async def test_patch_app_rejects_customer_user(client: AsyncClient, seeded_with_subs) -> None:
    email, password = seeded_with_subs["customer_user"]
    token = await _login(client, email, password)
    resp = await client.patch(
        "/api/customer-admin/apps/title-search",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert resp.status_code == 403


async def test_patch_app_rejects_unknown_id(client: AsyncClient, seeded_with_subs) -> None:
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.patch(
        "/api/customer-admin/apps/not-a-real-app",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert resp.status_code == 400
    assert "unknown app id" in resp.json()["detail"]


async def test_patch_app_rejects_disabling_ecv(client: AsyncClient, seeded_with_subs) -> None:
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.patch(
        "/api/customer-admin/apps/ecv",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert resp.status_code == 400
    assert "ECV" in resp.json()["detail"]


async def test_patch_ecv_true_is_noop_allowed(client: AsyncClient, seeded_with_subs) -> None:
    # Re-enabling ECV when it's already on is a no-op but shouldn't error —
    # the invariant is "ECV must stay enabled", not "never PATCH ECV".
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.patch(
        "/api/customer-admin/apps/ecv",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": "ecv", "subscribed": True, "enabled": True}


async def test_patch_app_404_when_not_subscribed(client: AsyncClient, seeded_with_subs) -> None:
    # title-exam isn't in the seeded_with_subs fixture.
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.patch(
        "/api/customer-admin/apps/title-exam",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert resp.status_code == 404


async def test_patch_app_disables_subscribed_app(client: AsyncClient, seeded_with_subs) -> None:
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    # Flip title-search off.
    off = await client.patch(
        "/api/customer-admin/apps/title-search",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert off.status_code == 200
    assert off.json() == {"id": "title-search", "subscribed": True, "enabled": False}

    # GET reflects the new state.
    listed = await client.get(
        "/api/customer-admin/apps",
        headers={"Authorization": f"Bearer {token}"},
    )
    row = next(r for r in listed.json() if r["id"] == "title-search")
    assert row == {"id": "title-search", "subscribed": True, "enabled": False}


async def test_patch_app_enables_previously_disabled(client: AsyncClient, seeded_with_subs) -> None:
    email, password = seeded_with_subs["customer_admin"]
    token = await _login(client, email, password)
    # compliance starts disabled in the fixture.
    on = await client.patch(
        "/api/customer-admin/apps/compliance",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert on.status_code == 200
    assert on.json() == {"id": "compliance", "subscribed": True, "enabled": True}
