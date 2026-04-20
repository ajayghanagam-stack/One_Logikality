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

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db import SessionLocal
from app.main import app
from app.security import hash_password


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
            text("INSERT INTO orgs (id, name, type) VALUES (:id, :name, 'Mortgage Lender')"),
            {"id": org_id, "name": f"Test Org {suffix}"},
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
