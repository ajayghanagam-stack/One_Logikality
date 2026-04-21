"""Auth endpoint tests. Each test seeds fresh users via the `seeded` fixture
so there's no cross-test contamination."""

from __future__ import annotations

from httpx import AsyncClient


async def test_login_rejects_unknown_email(client: AsyncClient, seeded) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": "noone@nowhere.test", "password": "whatever"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid email or password"


async def test_login_rejects_bad_password(client: AsyncClient, seeded) -> None:
    email, _ = seeded["customer_admin"]
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_login_issues_token_for_customer_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["role"] == "customer_admin"
    assert body["user"]["org_id"] == str(seeded["org_id"])
    assert body["user"]["is_primary_admin"] is True


async def test_login_platform_admin_has_null_org(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["role"] == "platform_admin"
    assert body["user"]["org_id"] is None


async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_returns_current_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    login = await client.post("/api/auth/login", json={"email": email, "password": password})
    token = login.json()["access_token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["role"] == "customer_user"
    assert body["org_id"] == str(seeded["org_id"])


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert "invalid token" in resp.json()["detail"]


# --- US-1.8 / US-2.1: POST /api/auth/change-password -------------------


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_change_password_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "new-pass-1"},
    )
    assert resp.status_code == 401


async def test_change_password_rejects_wrong_current(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "not-the-password", "new_password": "new-pass-1"},
    )
    assert resp.status_code == 400
    assert "current password" in resp.json()["detail"]


async def test_change_password_rejects_short_new(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": password, "new_password": "short"},
    )
    # pydantic min_length=6 rejects before the handler runs.
    assert resp.status_code == 422


async def test_change_password_rejects_same_as_current(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": password, "new_password": password},
    )
    assert resp.status_code == 400
    assert "differ" in resp.json()["detail"]


async def test_change_password_succeeds_and_login_round_trips(client: AsyncClient, seeded) -> None:
    email, old_password = seeded["platform_admin"]
    token = await _login(client, email, old_password)
    new_password = "rotated-pass-1"

    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": old_password, "new_password": new_password},
    )
    assert resp.status_code == 204

    # Old password now rejected; new password works. The existing JWT is
    # still valid (revocation is a later-phase concern) but that's not
    # what's being asserted here — we just want to prove the hash changed.
    bad = await client.post("/api/auth/login", json={"email": email, "password": old_password})
    assert bad.status_code == 401

    good = await client.post("/api/auth/login", json={"email": email, "password": new_password})
    assert good.status_code == 200


async def test_change_password_works_for_customer_admin(client: AsyncClient, seeded) -> None:
    # US-2.1 reuses the same endpoint — sanity-check that a customer admin
    # can also rotate their own password.
    email, old_password = seeded["customer_admin"]
    token = await _login(client, email, old_password)
    new_password = "customer-rotated-1"

    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": old_password, "new_password": new_password},
    )
    assert resp.status_code == 204

    good = await client.post("/api/auth/login", json={"email": email, "password": new_password})
    assert good.status_code == 200
