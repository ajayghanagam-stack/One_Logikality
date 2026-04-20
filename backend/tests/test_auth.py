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
