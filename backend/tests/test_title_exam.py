"""Title Examination API tests (US-6.2).

Covers:
- `GET /api/packets/{id}/title-exam` happy path, 403 / 404 / cross-org.
- `PATCH /api/packets/{id}/title-exam/checklist/{item_id}` — the
  curative-workflow state primitive. Toggles a checklist item from
  unchecked → checked and verifies the count rolls up.
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
from app.pipeline.title_exam_data import (
    CHECKLIST_ITEMS,
    REQUIREMENTS,
    SPECIFIC_EXCEPTIONS,
    STANDARD_EXCEPTIONS,
    WARNINGS,
)


@pytest.fixture(autouse=True)
def _fast_pipeline_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.ecv_stub.STAGE_DELAY_SECONDS", 0)


@pytest_asyncio.fixture
async def storage_tmp(tmp_path_factory, monkeypatch) -> AsyncIterator[Path]:
    tmp = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(settings, "storage_path", str(tmp))
    yield tmp


@pytest_asyncio.fixture
async def title_exam_enabled(seeded) -> AsyncIterator[None]:
    org_id = seeded["org_id"]
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'title-exam', true)"
            ),
            {"o": org_id},
        )
        await session.commit()
    try:
        yield
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM app_subscriptions WHERE org_id = :o"),
                {"o": org_id},
            )
            await session.commit()


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


async def test_title_exam_happy_path(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Schedule B splits cleanly by `schedule` column.
    assert len(payload["standard_exceptions"]) == len(STANDARD_EXCEPTIONS)
    assert len(payload["specific_exceptions"]) == len(SPECIFIC_EXCEPTIONS)

    # Schedule C / warnings / checklist round-trip counts.
    assert len(payload["requirements"]) == len(REQUIREMENTS)
    assert len(payload["warnings"]) == len(WARNINGS)
    assert len(payload["checklist"]) == len(CHECKLIST_ITEMS)

    # Severity counts cover specific exceptions only: 2 critical, 2 high,
    # 1 medium, 2 low.
    counts = payload["severity_counts"]
    assert counts["critical"] == 2
    assert counts["high"] == 2
    assert counts["medium"] == 1
    assert counts["low"] == 2
    assert counts["total"] == 7

    # Curative progress rollup: 3 of 8 items ship pre-checked.
    progress = payload["checklist_progress"]
    pre_checked = sum(1 for c in CHECKLIST_ITEMS if c["checked"])
    assert progress["completed"] == pre_checked == 3
    assert progress["total"] == len(CHECKLIST_ITEMS)

    # First specific exception is the headline critical one.
    exc6 = next(e for e in payload["specific_exceptions"] if e["number"] == 6)
    assert exc6["severity"] == "critical"
    assert "First National Bank" in exc6["title"]

    # Requirement #7 is `provided` (hazard insurance binder received).
    req7 = next(r for r in payload["requirements"] if r["number"] == 7)
    assert req7["status"] == "provided"
    assert req7["priority"] == "must_close"

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_checklist_toggle(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """PATCH the curative checklist and verify the progress rollup moves.

    This is the state-machine primitive the demo's curative workflow
    rides on — underwriter marks an item done, and the page reflects it
    on reload.
    """
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    before = resp.json()
    # Find an unchecked item (item #1 = mortgage payoff is unchecked in seed).
    target = next(c for c in before["checklist"] if not c["checked"])
    baseline = before["checklist_progress"]["completed"]

    patch = await client.patch(
        f"/api/packets/{packet_id}/title-exam/checklist/{target['id']}",
        json={"checked": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["checked"] is True
    assert patch.json()["id"] == target["id"]

    # Reload and verify the rollup moved.
    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    after = resp.json()
    assert after["checklist_progress"]["completed"] == baseline + 1

    # Toggle back to false.
    patch = await client.patch(
        f"/api/packets/{packet_id}/title-exam/checklist/{target['id']}",
        json={"checked": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["checked"] is False

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_403_when_not_subscribed(client: AsyncClient, seeded, storage_tmp) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_404_for_unknown_packet(
    client: AsyncClient, seeded, title_exam_enabled
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)

    resp = await client.get(
        f"/api/packets/{uuid.uuid4()}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_title_exam_checklist_404_unknown_item(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """PATCH for an item ID that doesn't belong to this packet → 404."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    patch = await client.patch(
        f"/api/packets/{packet_id}/title-exam/checklist/{uuid.uuid4()}",
        json={"checked": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 404

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_404_cross_org(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    other_org_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    from app.security import hash_password

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
        await session.execute(
            text(
                "INSERT INTO app_subscriptions (org_id, app_id, enabled) "
                "VALUES (:o, 'title-exam', true)"
            ),
            {"o": other_org_id},
        )
        await session.commit()

    try:
        other_token = await _login(client, f"other-{suffix}@acme.test", "pw-other")
        resp = await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": other_org_id})
            await session.commit()
        await _cleanup_packets(seeded["org_id"])


# ═══════════════════════════════════════════════════════════════════════
# TI Hub-parity tests — the title-exam structured output is a superset of
# title_intelligence_hub's ExaminerFlag / FlagResponse shape. These tests
# lock in the fields and endpoints that make that claim true.
# ═══════════════════════════════════════════════════════════════════════


async def test_title_exam_flags_carry_ti_hub_fields(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """Every real (specific) exception and warning surfaces the TI Hub
    shape: flag_type, ai_explanation, evidence_refs[{page_number, ...}],
    status, and an (initially empty) reviews list."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    payload = resp.json()

    # Unreleased-mortgage exception carries the full TI Hub shape.
    exc6 = next(e for e in payload["specific_exceptions"] if e["number"] == 6)
    assert exc6["flag_type"] == "unreleased_mortgage"
    assert exc6["status"] == "open"
    assert exc6["ai_explanation"] and "release" in exc6["ai_explanation"].lower()
    assert exc6["reviews"] == []
    assert len(exc6["evidence_refs"]) >= 1
    ev0 = exc6["evidence_refs"][0]
    assert isinstance(ev0.get("page_number"), int)
    assert "text_snippet" in ev0

    # Warnings expose the same shape.
    w_critical = next(w for w in payload["warnings"] if w["severity"] == "critical")
    assert w_critical["flag_type"] is not None
    assert w_critical["ai_explanation"] is not None
    assert w_critical["status"] == "open"
    assert w_critical["reviews"] == []

    # Requirements carry ai_explanation + evidence_refs (but not flag_type
    # — those belong to flags).
    req1 = next(r for r in payload["requirements"] if r["number"] == 1)
    assert req1["ai_explanation"] is not None
    assert "evidence_refs" in req1

    # Boilerplate ALTA standard exception has no risk taxonomy attached.
    std1 = next(e for e in payload["standard_exceptions"] if e["number"] == 1)
    assert std1["flag_type"] is None
    assert std1["evidence_refs"] == []

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_flag_review_transitions_status(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """POST a reject decision → flag status flips to `closed`, review
    payload is echoed back in the dashboard's reviews list."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    dashboard = (
        await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    target = next(e for e in dashboard["specific_exceptions"] if e["number"] == 6)
    assert target["status"] == "open"

    post = await client.post(
        f"/api/packets/{packet_id}/title-exam/flags/exception/{target['id']}/reviews",
        json={
            "decision": "reject",
            "reason_code": "unresolved_risk",
            "notes": "Underwriter will not accept without a recorded release.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post.status_code == 201, post.text
    review = post.json()
    assert review["decision"] == "reject"
    assert review["flag_kind"] == "exception"
    assert review["flag_id"] == target["id"]
    assert review["reason_code"] == "unresolved_risk"

    # Reload: status is now `closed`, and the review shows up on the flag.
    after = (
        await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    updated = next(e for e in after["specific_exceptions"] if e["number"] == 6)
    assert updated["status"] == "closed"
    assert len(updated["reviews"]) == 1
    assert updated["reviews"][0]["decision"] == "reject"

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_flag_escalate_keeps_flag_reviewed(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """Escalate is a distinct state from approve/reject — the flag stays
    in the reviewer queue as `reviewed` (visible but not closed)."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    dashboard = (
        await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    target = next(w for w in dashboard["warnings"] if w["severity"] == "high")

    post = await client.post(
        f"/api/packets/{packet_id}/title-exam/flags/warning/{target['id']}/reviews",
        json={"decision": "escalate", "reason_code": "senior_review"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post.status_code == 201, post.text

    after = (
        await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    updated = next(w for w in after["warnings"] if w["id"] == target["id"])
    assert updated["status"] == "reviewed"

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_flag_review_404_unknown_flag(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/title-exam/flags/exception/{uuid.uuid4()}/reviews",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_flag_review_rejects_bad_kind(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """Path-param `flag_kind` outside the Literal union → FastAPI 422."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.post(
        f"/api/packets/{packet_id}/title-exam/flags/requirement/{uuid.uuid4()}/reviews",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_recommendation_default_rejects(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """Fresh packet has 2 open critical findings → aggregate = reject."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam/recommendation",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rec = resp.json()
    assert rec["decision"] == "reject"
    assert 0.0 <= rec["confidence"] <= 1.0
    assert "critical" in rec["reasoning"].lower()

    await _cleanup_packets(seeded["org_id"])


async def test_title_exam_recommendation_moves_as_flags_close(
    client: AsyncClient, seeded, title_exam_enabled, storage_tmp
) -> None:
    """Approving every critical + high flag → recommendation flips to
    approve. This is what makes the review endpoint materially useful."""
    email, password = seeded["customer_admin"]
    token = await _login(client, email, password)
    packet_id = await _upload_and_wait(client, token)

    dashboard = (
        await client.get(
            f"/api/packets/{packet_id}/title-exam",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()

    # Close every critical/high flag across both tables.
    for exc in dashboard["specific_exceptions"]:
        if exc["severity"] in {"critical", "high"}:
            r = await client.post(
                f"/api/packets/{packet_id}/title-exam/flags/exception/{exc['id']}/reviews",
                json={"decision": "approve", "reason_code": "cured"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 201
    for w in dashboard["warnings"]:
        if w["severity"] in {"critical", "high"}:
            r = await client.post(
                f"/api/packets/{packet_id}/title-exam/flags/warning/{w['id']}/reviews",
                json={"decision": "approve", "reason_code": "cured"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 201

    resp = await client.get(
        f"/api/packets/{packet_id}/title-exam/recommendation",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["decision"] == "approve"

    await _cleanup_packets(seeded["org_id"])
