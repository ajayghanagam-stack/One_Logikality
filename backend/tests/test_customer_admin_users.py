"""Customer-admin team-management tests (US-2.2 / US-2.3 / US-2.4).

Exercises GET/POST/DELETE on `/api/customer-admin/users`:
  - auth gating (401 / 403 for wrong roles),
  - tenant isolation (a customer_admin only sees their own org),
  - invite happy path (generated + admin-supplied temp password),
  - invariants on delete (self, primary admin, cross-org).

Every test uses the `seeded` fixture which provides one throwaway org
with the three-role user set.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- GET /users --------------------------------------------------------


async def test_list_team_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/customer-admin/users")
    assert resp.status_code == 401


async def test_list_team_rejects_platform_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_team_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_team_returns_own_org_only(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    # Seeded fixture puts two users under the org: the primary customer_admin
    # and the customer_user. Platform admin has org_id=NULL so must not appear.
    emails = {r["email"] for r in rows}
    assert emails == {seeded["customer_admin"][0], seeded["customer_user"][0]}
    primary_row = next(r for r in rows if r["email"] == seeded["customer_admin"][0])
    assert primary_row["role"] == "admin"
    assert primary_row["is_primary_admin"] is True
    user_row = next(r for r in rows if r["email"] == seeded["customer_user"][0])
    assert user_row["role"] == "member"
    assert user_row["is_primary_admin"] is False


# --- POST /users -------------------------------------------------------


async def test_invite_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/customer-admin/users",
        json={"full_name": "Pat Smith", "email": "pat@acmemortgage.com", "role": "member"},
    )
    assert resp.status_code == 401


async def test_invite_rejects_platform_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Pat Smith", "email": "pat@acmemortgage.com", "role": "member"},
    )
    assert resp.status_code == 403


async def test_invite_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Pat Smith", "email": "pat@acmemortgage.com", "role": "member"},
    )
    assert resp.status_code == 403


async def test_invite_generates_temp_password_and_login_works(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    new_email = f"pat-{uuid.uuid4().hex[:6]}@acmemortgage.com"
    resp = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Pat Smith", "email": new_email, "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == new_email
    assert body["user"]["role"] == "member"
    assert body["user"]["is_primary_admin"] is False
    temp_password = body["temp_password"]
    assert len(temp_password) >= 6

    # Invited user can log in with the generated password.
    login = await client.post(
        "/api/auth/login", json={"email": new_email, "password": temp_password}
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "customer_user"


async def test_invite_accepts_admin_supplied_password(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    new_email = f"pat-{uuid.uuid4().hex[:6]}@acmemortgage.com"
    supplied = "supplied-pass-1"
    resp = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Pat Smith",
            "email": new_email,
            "role": "admin",
            "temp_password": supplied,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["temp_password"] == supplied
    assert resp.json()["user"]["role"] == "admin"

    login = await client.post("/api/auth/login", json={"email": new_email, "password": supplied})
    assert login.status_code == 200
    # "admin" on the wire maps to customer_admin internally.
    assert login.json()["user"]["role"] == "customer_admin"


async def test_invite_rejects_short_password(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Pat Smith",
            "email": "pat2@acmemortgage.com",
            "role": "member",
            "temp_password": "short",
        },
    )
    # pydantic min_length=6 rejects before the handler runs.
    assert resp.status_code == 422


async def test_invite_rejects_duplicate_email(client: AsyncClient, seeded) -> None:
    # The seeded customer_user lives under `.test` (reserved TLD) which
    # pydantic's EmailStr rejects outright, so we can't use that row to
    # trigger the 409. Instead invite a fresh user, then try to invite
    # again with the same email.
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    dup_email = f"dup-{uuid.uuid4().hex[:6]}@acmemortgage.com"
    first = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "First", "email": dup_email, "role": "member"},
    )
    assert first.status_code == 201

    dup = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Dup", "email": dup_email, "role": "member"},
    )
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]


# --- DELETE /users/{id} ------------------------------------------------


async def test_remove_requires_auth(client: AsyncClient, seeded) -> None:
    resp = await client.delete(f"/api/customer-admin/users/{seeded['customer_user_id']}")
    assert resp.status_code == 401


async def test_remove_rejects_customer_user(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    resp = await client.delete(
        f"/api/customer-admin/users/{seeded['customer_user_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_remove_rejects_primary_admin(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.delete(
        f"/api/customer-admin/users/{seeded['customer_admin_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Self-delete check fires first (admin is primary AND self).
    assert resp.status_code == 400
    assert "yourself" in resp.json()["detail"]


async def test_remove_rejects_self(client: AsyncClient, seeded) -> None:
    # Invite a second admin, log in as them, and have them try to delete
    # themselves — the self-delete guard should fire regardless of primary.
    primary_email, primary_pw = seeded["customer_admin"]
    primary_token = await _login(client, primary_email, primary_pw)
    invitee_email = f"second-admin-{uuid.uuid4().hex[:6]}@acmemortgage.com"
    invited = await client.post(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {primary_token}"},
        json={
            "full_name": "Second Admin",
            "email": invitee_email,
            "role": "admin",
            "temp_password": "second-admin-pw",
        },
    )
    assert invited.status_code == 201
    invitee_id = invited.json()["user"]["id"]

    invitee_token = await _login(client, invitee_email, "second-admin-pw")
    resp = await client.delete(
        f"/api/customer-admin/users/{invitee_id}",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert resp.status_code == 400
    assert "yourself" in resp.json()["detail"]


async def test_remove_rejects_cross_org_user(client: AsyncClient, seeded) -> None:
    # Platform admin has org_id=NULL and isn't in the customer_admin's org.
    # The filter `org_id == admin.org_id` makes this a 404, not a 403 —
    # we don't leak whether the id exists in some other scope.
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.delete(
        f"/api/customer-admin/users/{seeded['platform_admin_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_remove_unknown_id_returns_404(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.delete(
        f"/api/customer-admin/users/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_remove_customer_user_succeeds(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.delete(
        f"/api/customer-admin/users/{seeded['customer_user_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    # Gone from the list.
    listing = await client.get(
        "/api/customer-admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    emails = {r["email"] for r in listing.json()}
    assert seeded["customer_user"][0] not in emails

    # And can no longer log in.
    login = await client.post(
        "/api/auth/login",
        json={"email": seeded["customer_user"][0], "password": seeded["customer_user"][1]},
    )
    assert login.status_code == 401
