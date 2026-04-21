"""Platform-admin accounts-list tests (US-1.5).

Verifies the role guard (401 anon, 403 wrong role) and the shape of the
payload for a platform admin — including that the seeded org shows up
with the expected user_count from the `seeded` fixture (1 admin + 1 user
= 2) and that subscription_count is the stubbed 0 until US-2.5 lands.
"""

from __future__ import annotations

from httpx import AsyncClient


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_accounts_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/logikality/accounts")
    assert resp.status_code == 401


async def test_accounts_rejects_customer_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_accounts_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_accounts_lists_orgs_for_platform_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    # `seeded` creates one throwaway org. Other tests and/or the baseline
    # seed may leave additional orgs behind, so find ours by id instead of
    # asserting length.
    match = next((r for r in rows if r["id"] == str(seeded["org_id"])), None)
    assert match is not None, f"seeded org missing from response: {rows}"
    assert match["name"].startswith("Test Org ")
    assert match["slug"].startswith("test-")
    assert match["type"] == "Mortgage Lender"
    # Seeded customer_admin + customer_user both live under this org.
    assert match["user_count"] == 2
    # US-2.5 will populate this; for now it's always 0.
    assert match["subscription_count"] == 0
