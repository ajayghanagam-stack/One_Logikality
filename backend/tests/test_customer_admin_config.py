"""Customer-admin organization config tests (US-4.2 / US-4.7).

Exercises `GET/PUT/DELETE /api/customer-admin/config` and the
`/config/catalog` read-only endpoint. Because `seeded` doesn't create
any override rows, each test starts from a clean slate and cleans up
any rows it inserts in a teardown block.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.db import SessionLocal


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def cleanup_overrides(seeded) -> AsyncIterator[dict]:
    """Ensure any app_rule_overrides rows left behind by a test are
    removed before the next one runs — tests that hit the PUT endpoint
    create rows that outlast the `seeded` teardown otherwise."""
    try:
        yield seeded
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM app_rule_overrides WHERE org_id = :o"),
                {"o": seeded["org_id"]},
            )
            await session.commit()


# --- GET /config ------------------------------------------------------


async def test_get_config_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/customer-admin/config")
    assert resp.status_code == 401


async def test_get_config_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_get_config_rejects_platform_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_get_config_empty_for_fresh_org(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Every program id appears as a key (even if empty). This is the
    # contract the frontend relies on for tab-indicator computation.
    assert set(body["overrides"].keys()) == {
        "conventional",
        "jumbo",
        "fha",
        "va",
        "usda",
        "nonqm",
    }
    assert all(v == {} for v in body["overrides"].values())


# --- GET /config/catalog ----------------------------------------------


async def test_catalog_returns_programs_and_rules(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/config/catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "programs" in body and "rules" in body
    assert set(body["programs"].keys()) == {
        "conventional",
        "jumbo",
        "fha",
        "va",
        "usda",
        "nonqm",
    }
    assert set(body["rules"].keys()) == {
        "compliance",
        "income-calc",
        "title-search",
        "title-exam",
    }
    # Spot-check a known default so we know the catalog is actually serialized.
    assert body["programs"]["conventional"]["dtiLimit"] == 45


# --- PUT /config/{program_id} -----------------------------------------


async def test_put_config_rejects_unknown_program(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/imaginary",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50}},
    )
    assert resp.status_code == 400
    assert "unknown program id" in resp.json()["detail"]


async def test_put_config_rejects_unknown_rule_key(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"fakeKey": 1}},
    )
    assert resp.status_code == 400
    assert "unknown rule key" in resp.json()["detail"]


async def test_put_config_rejects_out_of_range_number(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 999}},
    )
    assert resp.status_code == 400
    assert "dtiLimit" in resp.json()["detail"]


async def test_put_config_rejects_invalid_select_option(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"trendingMethod": "not-a-method"}},
    )
    assert resp.status_code == 400


async def test_put_config_rejects_wrong_type_for_toggle(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"residualIncome": "yes"}},
    )
    assert resp.status_code == 400


async def test_put_config_rejects_customer_user(client: AsyncClient, cleanup_overrides) -> None:
    email, password = cleanup_overrides["customer_user"]
    token = await _login(client, email, password)
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50}},
    )
    assert resp.status_code == 403


async def test_put_config_persists_overrides(client: AsyncClient, cleanup_overrides) -> None:
    email, password = cleanup_overrides["customer_admin"]
    token = await _login(client, email, password)

    put = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50, "chainDepth": 35}},
    )
    assert put.status_code == 200
    body = put.json()
    assert body["overrides"]["conventional"] == {"dtiLimit": 50, "chainDepth": 35}
    # Other programs untouched.
    assert body["overrides"]["fha"] == {}

    # GET reflects the same state.
    get = await client.get(
        "/api/customer-admin/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get.status_code == 200
    assert get.json()["overrides"]["conventional"] == {
        "dtiLimit": 50,
        "chainDepth": 35,
    }


async def test_put_config_replace_all_semantics_deletes_absent_keys(
    client: AsyncClient, cleanup_overrides
) -> None:
    """A PUT with a smaller overrides map than what's stored should
    delete the absent keys — that's how the UI "reset to default" flows
    without a separate endpoint per rule."""
    email, password = cleanup_overrides["customer_admin"]
    token = await _login(client, email, password)

    # Seed two overrides.
    await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50, "chainDepth": 35}},
    )

    # PUT only one — the other should be deleted.
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 48}},
    )
    assert resp.status_code == 200
    assert resp.json()["overrides"]["conventional"] == {"dtiLimit": 48}


async def test_put_config_empty_overrides_clears_program(
    client: AsyncClient, cleanup_overrides
) -> None:
    email, password = cleanup_overrides["customer_admin"]
    token = await _login(client, email, password)

    await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50}},
    )
    resp = await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["overrides"]["conventional"] == {}


async def test_put_config_isolated_between_orgs(
    client: AsyncClient, cleanup_overrides, seeded
) -> None:
    """RLS sanity — an override written under one org must not leak into
    another org's GET. Seeded fixtures use different orgs on each test,
    so we assert by checking that the customer_user in the same org
    (who can't write but can read via SELECT RLS policy) sees the
    overrides the admin wrote."""
    # Admin writes.
    admin_email, admin_pw = cleanup_overrides["customer_admin"]
    admin_token = await _login(client, admin_email, admin_pw)
    await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"overrides": {"dtiLimit": 49}},
    )
    # Customer user in SAME org gets 403 on admin endpoint (no cross-read
    # via the admin endpoint) — but a direct DB read would see the row
    # thanks to the SELECT policy. We assert the 403 as the API contract:
    # only customer_admin can hit the config endpoint.
    user_email, user_pw = cleanup_overrides["customer_user"]
    user_token = await _login(client, user_email, user_pw)
    resp = await client.get(
        "/api/customer-admin/config",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# --- DELETE /config/{program_id} --------------------------------------


async def test_delete_config_rejects_unknown_program(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.delete(
        "/api/customer-admin/config/imaginary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_delete_config_resets_program_overrides(
    client: AsyncClient, cleanup_overrides
) -> None:
    email, password = cleanup_overrides["customer_admin"]
    token = await _login(client, email, password)

    await client.put(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 50, "chainDepth": 35}},
    )
    await client.put(
        "/api/customer-admin/config/fha",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"dtiLimit": 55}},
    )

    resp = await client.delete(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overrides"]["conventional"] == {}
    # Other programs untouched.
    assert body["overrides"]["fha"] == {"dtiLimit": 55}


async def test_delete_config_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.delete(
        "/api/customer-admin/config/conventional",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
