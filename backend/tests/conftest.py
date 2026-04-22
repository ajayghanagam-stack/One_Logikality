"""Test fixtures.

Most tests in this project touch the database to exercise RLS, so fixtures
talk to the same Postgres that `./start-dev.sh` brings up on :5437. Tests
that need isolated rows clean up after themselves in teardown.

`seed_platform_and_org_users` creates a minimal three-role user set with
known passwords (`pw-platform`, `pw-custadmin`, `pw-custuser`) under a
throwaway org, and deletes everything on teardown so tests stay hermetic.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db import SessionLocal
from app.main import app
from app.models import Packet
from app.security import hash_password
from tests._canned_seed import seed_canned_ecv


@pytest.fixture(autouse=True)
def _stub_classify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real Gemini classifier with a no-op for the test suite.

    Running the real Vertex call would (a) hit a paid external, (b)
    require ADC auth on CI, and (c) produce non-deterministic
    confidences. Returning an empty list means `_persist_findings`
    writes zero documents — tests that need the canned inventory get
    it via `_stub_validate`'s seed call (which writes both sections
    and docs) or via their own direct inserts.
    """

    async def _empty(_packet_id):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr("app.pipeline.ecv_stub.classify_packet", _empty)


@pytest.fixture(autouse=True)
def _stub_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real Gemini Pro extractor with a no-op for the test suite.

    Same reasoning as `_stub_classify`. Skipping extraction leaves
    `ecv_extractions` empty; tests that need extractions seed them
    directly (see `tests/test_packet_extractions.py`).
    """

    async def _noop(_packet_id):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr("app.pipeline.ecv_stub.extract_packet", _noop)


@pytest.fixture(autouse=True)
def _stub_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real Claude validator with a canned-seed writer.

    The real `validate_packet` makes 13 Claude calls to grade the 58
    checks; running it from tests is paid + non-deterministic + needs
    an Anthropic key. We swap in a helper that seeds the canned
    `ECV_SECTIONS` / `ECV_LINE_ITEMS` / `DOCUMENT_INVENTORY` rows
    directly so tests predating the real pipeline keep their deterministic
    assertions. Tests that specifically assert on validate behaviour
    (e.g. `tests/test_validate.py`) monkeypatch this fixture off by
    overriding `validate_packet` again inside the test.
    """

    async def _seed(packet_id):  # type: ignore[no-untyped-def]
        async with SessionLocal() as session:
            packet_org = (
                await session.execute(select(Packet.org_id).where(Packet.id == packet_id))
            ).scalar_one_or_none()
            if packet_org is None:
                return
            await seed_canned_ecv(session, packet_id=packet_id, org_id=packet_org)
            await session.commit()

    monkeypatch.setattr("app.pipeline.ecv_stub.validate_packet", _seed)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class SeededUsers(dict):
    """Dict-like record of the users seeded by the fixture.

    Keys: 'platform_admin', 'customer_admin', 'customer_user', 'org_id'.
    Values: (email, password) tuples for users; a UUID for org_id.
    """


@pytest_asyncio.fixture
async def seeded() -> AsyncIterator[SeededUsers]:
    org_id = uuid.uuid4()
    platform_id = uuid.uuid4()
    cust_admin_id = uuid.uuid4()
    cust_user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]

    emails = {
        "platform_admin": f"platform-{suffix}@logikality.test",
        "customer_admin": f"custadmin-{suffix}@acme.test",
        "customer_user": f"custuser-{suffix}@acme.test",
    }
    passwords = {
        "platform_admin": "pw-platform",
        "customer_admin": "pw-custadmin",
        "customer_user": "pw-custuser",
    }

    async with SessionLocal() as session:
        # Runs as postgres (superuser), so bypasses RLS for seeding.
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, type) "
                "VALUES (:id, :name, :slug, 'Mortgage Lender')"
            ),
            {"id": org_id, "name": f"Test Org {suffix}", "slug": f"test-{suffix}"},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, org_id) "
                "VALUES (:id, :email, :pw, :name, 'platform_admin', NULL)"
            ),
            {
                "id": platform_id,
                "email": emails["platform_admin"],
                "pw": hash_password(passwords["platform_admin"]),
                "name": "Test Platform Admin",
            },
        )
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, full_name, role, org_id, is_primary_admin) "
                "VALUES (:id, :email, :pw, :name, 'customer_admin', :org, true)"
            ),
            {
                "id": cust_admin_id,
                "email": emails["customer_admin"],
                "pw": hash_password(passwords["customer_admin"]),
                "name": "Test Customer Admin",
                "org": org_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, org_id) "
                "VALUES (:id, :email, :pw, :name, 'customer_user', :org)"
            ),
            {
                "id": cust_user_id,
                "email": emails["customer_user"],
                "pw": hash_password(passwords["customer_user"]),
                "name": "Test Customer User",
                "org": org_id,
            },
        )
        await session.commit()

    data = SeededUsers(
        org_id=org_id,
        platform_admin=(emails["platform_admin"], passwords["platform_admin"]),
        customer_admin=(emails["customer_admin"], passwords["customer_admin"]),
        customer_user=(emails["customer_user"], passwords["customer_user"]),
        platform_admin_id=platform_id,
        customer_admin_id=cust_admin_id,
        customer_user_id=cust_user_id,
    )

    try:
        yield data
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM users WHERE org_id = :o OR id = :p"),
                {"o": org_id, "p": platform_id},
            )
            await session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": org_id})
            await session.commit()
