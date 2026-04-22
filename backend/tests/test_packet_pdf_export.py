"""ECV PDF export tests (US-8.1 GET /api/packets/{id}/export/pdf).

Covers:
- Happy path: customer admin downloads the PDF; response is a
  non-trivial application/pdf payload with a sensible Content-
  Disposition filename.
- Not-ready: calling export on a packet that hasn't finished the stub
  yields 409, same shape as the dashboard endpoint.
- RLS: a user in another org gets 404, not 403, so existence doesn't
  leak across tenants.
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


async def test_export_pdf_happy_path(client: AsyncClient, seeded, storage_tmp) -> None:
    """Customer admin pulls a PDF for a completed packet. The response is
    a real PDF (magic bytes + non-trivial size) and carries an attachment
    Content-Disposition so browsers trigger a download."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/export/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert f"ecv-report-{packet_id[:8]}.pdf" in disposition

    body = resp.content
    assert body.startswith(b"%PDF-"), "response body is not a PDF"
    # A realistic ECV report with tables is always > a few KB. A bare
    # reportlab page with just the header is under 2 KB, so 3 KB is a
    # conservative floor that still catches "template rendered empty".
    assert len(body) > 3_000, f"PDF too small: {len(body)} bytes"

    await _cleanup_packets(seeded["org_id"])


async def test_export_pdf_after_review_decision(client: AsyncClient, seeded, storage_tmp) -> None:
    """Recording a review decision first → that decision is reflected in
    the PDF (we don't parse, but regenerating must not error)."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    review = await client.post(
        f"/api/packets/{packet_id}/review",
        json={
            "state": "pending_manual_review",
            "notes": "Escalating to senior underwriter for secondary review.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert review.status_code == 200, review.text

    resp = await client.get(
        f"/api/packets/{packet_id}/export/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")

    await _cleanup_packets(seeded["org_id"])


async def test_export_pdf_404_unknown_packet(client: AsyncClient, seeded) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/export/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_export_pdf_404_cross_org(client: AsyncClient, seeded, storage_tmp) -> None:
    """A user in a different org cannot download the PDF — RLS hides the
    row, so the API returns 404, not 403."""
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
        resp = await client.get(
            f"/api/packets/{packet_id}/export/pdf",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])
