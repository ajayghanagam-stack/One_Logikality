"""Platform-admin accounts endpoints tests (US-1.5 + US-1.6).

US-1.5: list accounts — role guard + payload shape.
US-1.6: create account — role guard, slug derivation, uniqueness/reserved
slug rejection, primary-admin login.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.db import SessionLocal


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _delete_org(org_id: str) -> None:
    """Tear-down helper for tests that create orgs via the API (the seeded
    fixture only cleans up its own throwaway org)."""
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM users WHERE org_id = :o"), {"o": uuid.UUID(org_id)})
        await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": uuid.UUID(org_id)})
        await session.commit()


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


# --- US-1.6: POST /api/logikality/accounts -----------------------------


def _create_payload(suffix: str) -> dict[str, str]:
    """Fresh payload keyed by a caller-supplied suffix so each test's rows
    are distinguishable and cleanup by org name/email is easy."""
    return {
        "name": f"Widget Lending {suffix}",
        "type": "Mortgage Lender",
        "primary_admin_full_name": "Wendy Widget",
        "primary_admin_email": f"wendy-{suffix}@widget.example.com",
    }


async def test_create_account_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/logikality/accounts", json=_create_payload("x"))
    assert resp.status_code == 401


async def test_create_account_rejects_customer_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json=_create_payload("cadm"),
    )
    assert resp.status_code == 403


async def test_create_account_succeeds_and_new_admin_can_log_in(
    client: AsyncClient, seeded
) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    suffix = uuid.uuid4().hex[:8]
    payload = _create_payload(suffix)

    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    account = body["account"]
    # Slug is derived server-side: lowercased, whitespace → hyphens.
    assert account["slug"] == f"widget-lending-{suffix}"
    assert account["name"] == payload["name"]
    assert account["type"] == "Mortgage Lender"
    assert account["user_count"] == 1
    assert account["subscription_count"] == 0
    assert body["primary_admin_email"] == payload["primary_admin_email"]
    assert isinstance(body["temp_password"], str) and len(body["temp_password"]) >= 8

    try:
        # Round-trip: the new primary admin can log in with the temp password.
        login = await client.post(
            "/api/auth/login",
            json={
                "email": payload["primary_admin_email"],
                "password": body["temp_password"],
            },
        )
        assert login.status_code == 200, login.text
        me = login.json()["user"]
        assert me["role"] == "customer_admin"
        assert me["is_primary_admin"] is True
        assert me["org_slug"] == account["slug"]
    finally:
        await _delete_org(account["id"])


async def test_create_account_rejects_duplicate_name(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    suffix = uuid.uuid4().hex[:8]
    payload = _create_payload(suffix)

    first = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert first.status_code == 201
    account_id = first.json()["account"]["id"]

    try:
        # Same name + slug, different admin email → still 409 on the org.
        dup = await client.post(
            "/api/logikality/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={**payload, "primary_admin_email": f"other-{suffix}@widget.example.com"},
        )
        assert dup.status_code == 409
    finally:
        await _delete_org(account_id)


async def test_create_account_rejects_reserved_slug(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Logikality",  # slugifies to the reserved `logikality`
            "type": "Mortgage Lender",
            "primary_admin_full_name": "Nope Nope",
            "primary_admin_email": f"nope-{uuid.uuid4().hex[:8]}@example.com",
        },
    )
    assert resp.status_code == 400


async def test_create_account_rejects_invalid_type(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"BadType Co {uuid.uuid4().hex[:6]}",
            "type": "Hedge Fund",
            "primary_admin_full_name": "Bad Type",
            "primary_admin_email": f"bt-{uuid.uuid4().hex[:8]}@example.com",
        },
    )
    assert resp.status_code == 400


# --- Demo affordance: admin-supplied initial_password ------------------
# These exercise the temporary `initial_password` field on the create
# request. When the full onboarding flow ships the field and these tests
# should be removed together.


async def test_create_account_accepts_admin_supplied_password(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    suffix = uuid.uuid4().hex[:8]
    chosen_password = "demo-pass-1"  # > 6 chars, distinct from the generator's output
    payload = {**_create_payload(suffix), "initial_password": chosen_password}

    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    account_id = body["account"]["id"]

    # Response echoes the chosen password verbatim (so the UI can render
    # a confirmation card identically for both paths).
    assert body["temp_password"] == chosen_password

    try:
        # Round-trip: the new admin logs in with the password the platform
        # admin typed — proof the supplied value is what got hashed.
        login = await client.post(
            "/api/auth/login",
            json={
                "email": payload["primary_admin_email"],
                "password": chosen_password,
            },
        )
        assert login.status_code == 200, login.text
    finally:
        await _delete_org(account_id)


async def test_create_account_rejects_short_initial_password(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/logikality/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={**_create_payload(uuid.uuid4().hex[:8]), "initial_password": "short"},
    )
    # Pydantic `min_length=6` kicks in before the handler body runs.
    assert resp.status_code == 422
