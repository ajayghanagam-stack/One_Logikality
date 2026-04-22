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
from app.models import EcvLineItem, EcvSection, Packet
from app.pipeline.ecv_stub import PIPELINE_STAGES
from app.security import hash_password


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    """Pin the stub's per-stage delay to zero for every test in this
    module. Under httpx's ASGI transport the `BackgroundTasks` attached
    to the POST response runs to completion before `client.post` returns,
    so any real delay would multiply the suite's wall time by 6 × delay ×
    upload-count. Zero keeps the tests snappy and doesn't change any
    observable behavior: the stub still walks every stage in order."""
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


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


# --- pipeline stub (US-3.4) ------------------------------------------


async def test_packet_pipeline_runs_to_completion(client: AsyncClient, seeded, storage_tmp) -> None:
    """POST schedules the ECV stub; by the time we fetch the packet back
    the stub has walked every stage and left the row in `completed`.

    The POST response is constructed before the background task runs, so
    `status` is still `uploaded` and `current_stage` is NULL there —
    that's the initial state the frontend's `PipelineProgress` sees
    before it starts polling."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    files = {"files": ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    data = {"declared_program_id": "conventional"}
    resp = await client.post(
        "/api/packets",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "uploaded"
    assert body["current_stage"] is None
    assert body["started_processing_at"] is None
    assert body["completed_at"] is None
    packet_id = body["id"]

    # Poll a handful of times — with the delay pinned to 0 the stub
    # completes almost instantly, but the loop keeps the test robust if
    # the ASGI transport's bg-task scheduling ever changes.
    payload = None
    for _ in range(50):
        fetch = await client.get(
            f"/api/packets/{packet_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert fetch.status_code == 200
        payload = fetch.json()
        if payload["status"] == "completed":
            break
        await asyncio.sleep(0.02)

    assert payload is not None
    assert payload["status"] == "completed"
    # Last stage in PIPELINE_STAGES is "route" — the stub doesn't clear
    # current_stage on completion; it leaves the last-seen value for
    # visual continuity on the final poll.
    assert payload["current_stage"] == PIPELINE_STAGES[-1]
    assert payload["started_processing_at"] is not None
    assert payload["completed_at"] is not None
    await _cleanup_packets(seeded["org_id"])


# --- helpers ----------------------------------------------------------


async def _cleanup_packets(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM packets WHERE org_id = :o"),
            {"o": org_id},
        )
        await session.execute(
            text("DELETE FROM app_subscriptions WHERE org_id = :o"),
            {"o": org_id},
        )
        await session.commit()


# --- list endpoint coverage chips (US-2.6 home dashboard) -----------


async def _seed_completed_packet_with_coverage(
    *,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
) -> uuid.UUID:
    """Insert a `completed` packet plus a single section with line items
    tagged for `compliance` and `ecv`, used by the coverage-chip tests.

    Returns the packet id. Bypasses the upload pipeline so the test is
    fully deterministic about which line items exist and what their
    `app_ids` look like — the goal is to assert `_packet_coverage_for_list`'s
    per-app filtering rules, not exercise the real pipeline.

    Confidence values are picked relative to the router's thresholds
    (`_CONFIDENCE_THRESHOLD = 85`, `_CRITICAL_THRESHOLD = 50`):
      - compliance: 90 (passed), 70 (review), 30 (critical) → mean 63.3
      - ecv: untagged 95 (passed), tagged 80 (review)       → mean 87.5
    """
    async with SessionLocal() as session:
        packet = Packet(
            org_id=org_id,
            declared_program_id="conventional",
            status="completed",
            created_by=created_by,
            scoped_app_ids=["compliance", "ecv"],
        )
        session.add(packet)
        await session.flush()

        section = EcvSection(
            packet_id=packet.id,
            org_id=org_id,
            section_number=1,
            name="Coverage Test Section",
            weight=10,
            score=80.0,
        )
        session.add(section)
        await session.flush()

        rows = [
            # Compliance-tagged checks: all three buckets represented.
            EcvLineItem(
                section_id=section.id,
                packet_id=packet.id,
                org_id=org_id,
                item_code="COMP-PASS",
                check_description="Compliance passed",
                result_text="ok",
                confidence=90,
                app_ids=["compliance"],
            ),
            EcvLineItem(
                section_id=section.id,
                packet_id=packet.id,
                org_id=org_id,
                item_code="COMP-REVIEW",
                check_description="Compliance review",
                result_text="needs review",
                confidence=70,
                app_ids=["compliance"],
            ),
            EcvLineItem(
                section_id=section.id,
                packet_id=packet.id,
                org_id=org_id,
                item_code="COMP-CRIT",
                check_description="Compliance critical",
                result_text="critical",
                confidence=30,
                app_ids=["compliance"],
            ),
            # ECV catch-all: one untagged (core) item and one explicitly
            # tagged `ecv`. Both should land in the ecv bucket.
            EcvLineItem(
                section_id=section.id,
                packet_id=packet.id,
                org_id=org_id,
                item_code="ECV-CORE",
                check_description="Core ECV check",
                result_text="ok",
                confidence=95,
                app_ids=None,
            ),
            EcvLineItem(
                section_id=section.id,
                packet_id=packet.id,
                org_id=org_id,
                item_code="ECV-TAGGED",
                check_description="Explicitly tagged ECV check",
                result_text="ok",
                confidence=80,
                app_ids=["ecv"],
            ),
        ]
        session.add_all(rows)
        await session.commit()
        return packet.id


async def _subscribe(org_id: uuid.UUID, app_id: str, *, enabled: bool) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, :a, :e)"
            ),
            {"o": org_id, "a": app_id, "e": enabled},
        )
        await session.commit()


async def _set_subscription_enabled(
    org_id: uuid.UUID, app_id: str, *, enabled: bool
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "UPDATE app_subscriptions SET enabled = :e "
                "WHERE org_id = :o AND app_id = :a"
            ),
            {"o": org_id, "a": app_id, "e": enabled},
        )
        await session.commit()


async def test_list_packets_returns_per_app_coverage_chips(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """The list endpoint surfaces per-app coverage rows for completed
    packets. Non-ECV apps average ONLY their tagged items; ECV averages
    both untagged (core) items and items explicitly tagged `ecv`."""
    org_id = seeded["org_id"]
    await _subscribe(org_id, "compliance", enabled=True)
    packet_id = await _seed_completed_packet_with_coverage(
        org_id=org_id, created_by=seeded["customer_admin_id"]
    )

    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/packets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == str(packet_id)

    coverage = {row["app_id"]: row for row in rows[0]["coverage"]}
    assert set(coverage) == {"ecv", "compliance"}

    # Compliance chip: averages only its three tagged items.
    comp = coverage["compliance"]
    assert comp["total_items"] == 3
    assert comp["passed_items"] == 1
    assert comp["review_items"] == 1
    assert comp["critical_items"] == 1
    assert comp["score"] == pytest.approx(63.3)

    # ECV chip: catch-all bucket — untagged core check + explicitly
    # tagged `ecv` check, but NOT the compliance-tagged items.
    ecv = coverage["ecv"]
    assert ecv["total_items"] == 2
    assert ecv["passed_items"] == 1
    assert ecv["review_items"] == 1
    assert ecv["critical_items"] == 0
    assert ecv["score"] == pytest.approx(87.5)

    await _cleanup_packets(org_id)


async def test_list_packets_drops_chip_when_app_disabled(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Disabling a subscription removes the matching chip from a
    subsequent list response. ECV is foundational and stays."""
    org_id = seeded["org_id"]
    await _subscribe(org_id, "compliance", enabled=True)
    await _seed_completed_packet_with_coverage(
        org_id=org_id, created_by=seeded["customer_admin_id"]
    )

    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    first = await client.get(
        "/api/packets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_apps = {row["app_id"] for row in first.json()[0]["coverage"]}
    assert first_apps == {"ecv", "compliance"}

    await _set_subscription_enabled(org_id, "compliance", enabled=False)

    second = await client.get(
        "/api/packets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    second_apps = {row["app_id"] for row in second.json()[0]["coverage"]}
    assert second_apps == {"ecv"}

    await _cleanup_packets(org_id)


async def _seed_packet(
    *,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    status: str,
) -> uuid.UUID:
    """Insert a packet at an arbitrary status with no derived rows.

    Used to assert the list endpoint's coverage shape for non-completed
    packets (failed pipelines and in-flight uploads).
    """
    async with SessionLocal() as session:
        packet = Packet(
            org_id=org_id,
            declared_program_id="conventional",
            status=status,
            created_by=created_by,
            scoped_app_ids=["compliance", "ecv"],
        )
        session.add(packet)
        await session.commit()
        return packet.id


async def test_list_packets_failed_packet_returns_failed_chips(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """A `failed` packet surfaces a per-app chip in `state="failed"` for
    every currently-enabled app (ECV always included), so the home
    dashboard can render a failure marker per app instead of leaving the
    card silently empty or showing a misleading 0% score."""
    org_id = seeded["org_id"]
    await _subscribe(org_id, "compliance", enabled=True)
    packet_id = await _seed_packet(
        org_id=org_id,
        created_by=seeded["customer_admin_id"],
        status="failed",
    )

    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/packets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == str(packet_id)
    assert rows[0]["status"] == "failed"

    coverage = {row["app_id"]: row for row in rows[0]["coverage"]}
    assert set(coverage) == {"ecv", "compliance"}
    for chip in coverage.values():
        assert chip["state"] == "failed"
        assert chip["total_items"] == 0
        assert chip["passed_items"] == 0
        assert chip["review_items"] == 0
        assert chip["critical_items"] == 0
        assert chip["score"] == 0.0

    await _cleanup_packets(org_id)


async def test_list_packets_uncompleted_packet_omits_coverage(
    client: AsyncClient, seeded, storage_tmp
) -> None:
    """Packets that haven't finished processing yet (no line items, not
    failed) return `coverage=None`, so the dashboard cleanly skips
    rendering chips while the pipeline is still in flight."""
    org_id = seeded["org_id"]
    await _subscribe(org_id, "compliance", enabled=True)
    await _seed_packet(
        org_id=org_id,
        created_by=seeded["customer_admin_id"],
        status="processing",
    )

    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    resp = await client.get(
        "/api/packets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "processing"
    assert rows[0]["coverage"] is None

    await _cleanup_packets(org_id)
