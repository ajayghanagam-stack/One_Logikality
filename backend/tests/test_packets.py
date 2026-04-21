"""Packet upload tests (US-3.1 / US-3.2 / US-3.3).

Covers:
- Auth gating (401 unauth, 403 for platform_admin).
- Both customer roles (admin + user) can upload.
- Program-id validation, extension allowlist, empty-file rejection.
- Round-trip: POST then GET returns the same row.
- RLS cross-org isolation — a packet uploaded by one org's user is a 404
  to a user in a different org.
- Storage bytes land under the configured storage_path.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.security import hash_password


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    """Point the storage adapter at a unique tmp dir per test so uploads
    don't pollute the dev `./storage` folder. `settings.storage_path` is
    read on every `get_storage()` call, so patching it is enough."""
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


def _pdf_bytes(text: str = "fake pdf") -> bytes:
    return b"%PDF-1.4\n" + text.encode()


# --- auth gating ------------------------------------------------------


async def test_upload_requires_auth(client: AsyncClient, storage_tmp) -> None:
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post("/api/packets", data=data, files=files)
    assert resp.status_code == 401


async def test_upload_rejects_platform_admin(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["platform_admin"]
    token = await _login(client, email, password)
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# --- happy path -------------------------------------------------------


async def test_customer_admin_can_upload(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    body = _pdf_bytes("admin pdf")
    files = {"files": ("packet.pdf", io.BytesIO(body), "application/pdf")}
    data = {"declared_program_id": "fha"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["declared_program_id"] == "fha"
    assert payload["status"] == "uploaded"
    assert len(payload["files"]) == 1
    assert payload["files"][0]["filename"] == "packet.pdf"
    assert payload["files"][0]["size_bytes"] == len(body)

    # Bytes landed under the tmp storage path.
    packet_id = payload["id"]
    org_dir = storage_tmp / "packets" / str(seeded["org_id"]) / packet_id
    assert org_dir.is_dir()
    written = list(org_dir.iterdir())
    assert len(written) == 1
    assert written[0].read_bytes() == body

    # Cleanup the packet + packet_files rows (fixture only cascades
    # via orgs/users, so packets outlive the seeded fixture otherwise).
    await _cleanup_packets(seeded["org_id"])


async def test_customer_user_can_upload(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_user"]
    token = await _login(client, email, password)
    files = {"files": ("p.pdf", io.BytesIO(_pdf_bytes("user pdf")), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    await _cleanup_packets(seeded["org_id"])


async def test_upload_accepts_multiple_files(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    files = [
        ("files", ("a.pdf", io.BytesIO(_pdf_bytes("a")), "application/pdf")),
        ("files", ("b.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 32), "image/png")),
        ("files", ("c.jpg", io.BytesIO(b"\xff\xd8\xff" + b"y" * 32), "image/jpeg")),
    ]
    data = {"declared_program_id": "jumbo"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert {f["filename"] for f in payload["files"]} == {"a.pdf", "b.png", "c.jpg"}
    await _cleanup_packets(seeded["org_id"])


# --- validation -------------------------------------------------------


async def test_upload_rejects_unknown_program(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "imaginary"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "program" in resp.json()["detail"]


async def test_upload_rejects_bad_extension(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"]


async def test_upload_rejects_empty_file(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# --- RLS / GET -------------------------------------------------------


async def test_get_packet_round_trip(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "va"}
    create = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 201
    packet_id = create.json()["id"]

    fetch = await client.get(
        f"/api/packets/{packet_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert fetch.status_code == 200
    assert fetch.json()["declared_program_id"] == "va"
    assert fetch.json()["files"][0]["filename"] == "doc.pdf"
    await _cleanup_packets(seeded["org_id"])


async def test_get_packet_isolated_across_orgs(client: AsyncClient, seeded, storage_tmp) -> None:
    # Upload as the seeded org's admin.
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    create = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    packet_id = create.json()["id"]

    # Stand up a second org + user directly via SQL so we can attempt a
    # cross-tenant read.
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
        resp = await client.get(
            f"/api/packets/{packet_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_user})
            await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": other_org})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])


# --- helpers ----------------------------------------------------------


async def _cleanup_packets(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM packets WHERE org_id = :o"),
            {"o": org_id},
        )
        await session.commit()
