"""Idempotent demo seed: one platform admin, one customer org, one primary
customer admin. Called from `./start-dev.sh` after `alembic upgrade head`.

Runs as the postgres superuser (via the same DATABASE_URL the app uses), so
it bypasses RLS — that's deliberate: seeding has to insert across tenants.

Re-runs are safe: ON CONFLICT DO NOTHING on natural keys (org name / user
email) means existing rows are left alone and the script just reports
`(existing)`.

Credentials are intentionally weak and documented in CLAUDE.md as
demo-only — not a production pattern.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import text

from app.db import SessionLocal
from app.security import hash_password

# Fixed UUIDs so the seeded rows are addressable from tests / fixtures
# without having to SELECT them back. Versioning them as constants makes
# it obvious when/why they change.
PLATFORM_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACME_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a0")
ACME_PRIMARY_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


@dataclass(frozen=True)
class _UserSpec:
    id: uuid.UUID
    email: str
    password: str
    full_name: str
    role: str
    org_id: uuid.UUID | None
    is_primary_admin: bool = False


PLATFORM_ADMIN = _UserSpec(
    id=PLATFORM_ADMIN_ID,
    email="admin@logikality.com",
    password="admin123",
    full_name="Logikality Platform Admin",
    role="platform_admin",
    org_id=None,
)

ACME_PRIMARY_ADMIN = _UserSpec(
    id=ACME_PRIMARY_ADMIN_ID,
    email="admin@acmemortgage.com",
    password="admin123",
    full_name="Acme Primary Admin",
    role="customer_admin",
    org_id=ACME_ORG_ID,
    is_primary_admin=True,
)


async def seed() -> None:
    async with SessionLocal() as session:
        org_created = await _upsert_org(
            session,
            id=ACME_ORG_ID,
            name="Acme Mortgage Holdings",
            type="Mortgage Lender",
        )
        platform_created = await _upsert_user(session, PLATFORM_ADMIN)
        acme_admin_created = await _upsert_user(session, ACME_PRIMARY_ADMIN)
        await session.commit()

    print("Seed complete:")
    print(f"  Acme Mortgage Holdings     {'created' if org_created else '(existing)'}")
    print(f"  admin@logikality.com       {'created' if platform_created else '(existing)'}")
    print(f"  admin@acmemortgage.com     {'created' if acme_admin_created else '(existing)'}")


async def _upsert_org(session, *, id: uuid.UUID, name: str, type: str) -> bool:
    result = await session.execute(
        text(
            "INSERT INTO orgs (id, name, type) VALUES (:id, :name, :type) "
            "ON CONFLICT (name) DO NOTHING RETURNING id"
        ),
        {"id": id, "name": name, "type": type},
    )
    return result.first() is not None


async def _upsert_user(session, spec: _UserSpec) -> bool:
    result = await session.execute(
        text(
            "INSERT INTO users "
            "(id, email, password_hash, full_name, role, org_id, is_primary_admin) "
            "VALUES (:id, :email, :pw, :name, :role, :org_id, :primary) "
            "ON CONFLICT (email) DO NOTHING RETURNING id"
        ),
        {
            "id": spec.id,
            "email": spec.email,
            "pw": hash_password(spec.password),
            "name": spec.full_name,
            "role": spec.role,
            "org_id": spec.org_id,
            "primary": spec.is_primary_admin,
        },
    )
    return result.first() is not None


if __name__ == "__main__":
    asyncio.run(seed())
