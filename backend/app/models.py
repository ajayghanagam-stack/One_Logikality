"""ORM models for the auth / multi-tenant spine.

Two tables — `orgs` and `users` — plus their check constraints. Every
tenant-scoped table added later MUST carry `org_id UUID NOT NULL REFERENCES
orgs(id) ON DELETE CASCADE` and enable RLS with the same policy shape used
in the initial migration. Platform admins are modeled as users with
`role = 'platform_admin'` and `org_id = NULL` — they aren't scoped to a
customer organization.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base

# Kept as tuples of literals so the same values are used by the migration,
# the model-level CHECK constraints, and any Python-side validation.
ORG_TYPES: tuple[str, ...] = (
    "Mortgage Lender",
    "Loan Servicer",
    "Title Agency",
    "Mortgage BPO",
)

USER_ROLES: tuple[str, ...] = (
    "platform_admin",
    "customer_admin",
    "customer_user",
)

# Known micro-app ids — in lockstep with migration 0003's CHECK constraint
# and frontend/lib/apps.ts. ECV is foundational (every org must subscribe);
# the others are à la carte. The demo uses the same ids so reference
# material stays directly comparable.
APP_IDS: tuple[str, ...] = (
    "ecv",
    "title-search",
    "title-exam",
    "compliance",
    "income-calc",
)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # URL-friendly identifier used by the customer portal at /{slug}/*.
    # Uniqueness + shape + the reserved `logikality` exclusion are enforced
    # in the 0002 migration (constraint `orgs_slug_shape_check`).
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    users: Mapped[list[User]] = relationship(back_populates="org")

    __table_args__ = (
        CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in ORG_TYPES) + ")",
            name="orgs_type_check",
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # NULL for platform_admin users; enforced by users_role_org_consistency below.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_primary_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    org: Mapped[Org | None] = relationship(back_populates="users")

    __table_args__ = (
        CheckConstraint(
            "role IN (" + ", ".join(f"'{r}'" for r in USER_ROLES) + ")",
            name="users_role_check",
        ),
        # Platform admins aren't scoped to an org; customer roles always are.
        CheckConstraint(
            "(role = 'platform_admin' AND org_id IS NULL) "
            "OR (role IN ('customer_admin', 'customer_user') AND org_id IS NOT NULL)",
            name="users_role_org_consistency",
        ),
    )


class AppSubscription(Base):
    """Which micro-apps a customer org has been subscribed to.

    Row-existence = subscribed. The `enabled` column is the customer-admin
    toggle (US-2.6) — subscriptions the org has paid for but temporarily
    disabled still exist as rows with `enabled = false`. Unique
    `(org_id, app_id)` prevents duplicate subscriptions.
    """

    __tablename__ = "app_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_id: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("org_id", "app_id", name="app_subscriptions_org_app_unique"),
        CheckConstraint(
            "app_id IN (" + ", ".join(f"'{a}'" for a in APP_IDS) + ")",
            name="app_subscriptions_app_id_check",
        ),
    )


class AppRuleOverride(Base):
    """One customer-admin org-level rule override (US-4.2).

    Persists per (org_id, program_id, rule_key). Values are stored as
    JSONB because the resolver treats str/int/float/bool uniformly —
    splitting into typed columns would just push the discriminator
    onto the API layer for no gain. Validation (type-matches-schema,
    min/max, allowed-options) is enforced at the router layer against
    `app.rules.catalog.MICRO_APP_RULES`.
    """

    __tablename__ = "app_rule_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    program_id: Mapped[str] = mapped_column(String, nullable=False)
    rule_key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "program_id",
            "rule_key",
            name="app_rule_overrides_org_program_rule_unique",
        ),
    )


# Status values mirror migration 0006's CHECK constraint. Packets start
# as `uploaded` (bytes persisted, nothing run yet); the ECV worker will
# flip through `processing` → `completed` / `failed` in Phase 3.
PACKET_STATUSES: tuple[str, ...] = (
    "uploaded",
    "processing",
    "completed",
    "failed",
)

# Loan-program confirmation states (US-3.11). In lockstep with migration
# 0009's CHECK constraint.
CONFIRMATION_STATUSES: tuple[str, ...] = (
    "confirmed",
    "conflict",
    "inconclusive",
)


# Packet review states (US-8.3). NULL on packets that have not yet been
# reviewed; otherwise one of these values. `rejected` is a terminal state
# in the demo; `pending_manual_review` and `approved` can transition into
# each other.
REVIEW_STATES: tuple[str, ...] = (
    "pending_manual_review",
    "approved",
    "rejected",
)


class Packet(Base):
    """A document packet submitted by a customer user for ECV processing.

    The declared program id is captured at upload time (US-3.2). It stays
    on the row so rule resolution at processing time is reproducible even
    if the org's config changes between upload and analysis; that same
    program is what US-3.11's confirmation analysis will validate against.
    """

    __tablename__ = "packets"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    declared_program_id: Mapped[str] = mapped_column(String, nullable=False)
    # Which micro-apps this packet should be scored against. "ecv" is
    # always implicitly in scope — the column carries it explicitly so
    # callers don't have to special-case the foundational app. Set at
    # upload time; see migration 0018 for the rationale.
    scoped_app_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['ecv']::text[]"),
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="uploaded")
    # Pipeline animation sync (US-3.4). Populated by the ECV stub / the
    # real Temporal workflow once it lands. Values are the ids in
    # app.pipeline.ecv_stub.PIPELINE_STAGES; NULL until processing starts.
    current_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    started_processing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Loan-program confirmation (US-3.11). Written by the ECV pipeline
    # during the `score` stage; NULL until findings exist.
    program_confirmation_status: Mapped[str | None] = mapped_column(String, nullable=True)
    program_confirmation_suggested_id: Mapped[str | None] = mapped_column(String, nullable=True)
    program_confirmation_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    # List of document names the pipeline inspected to reach the
    # confirmation verdict (shown on the pill / override dialog preview).
    program_confirmation_documents: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Packet-level program override (US-3.12). Set by POST
    # /api/packets/{id}/program-override; a revert clears all four at
    # once. `program_overridden_to` is the effective program for rule
    # resolution when non-NULL.
    program_overridden_to: Mapped[str | None] = mapped_column(String, nullable=True)
    program_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    program_overridden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Review state (US-8.3). NULL until the customer records a decision
    # via POST /api/packets/{id}/review.
    review_state: Mapped[str | None] = mapped_column(String, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_transitioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    files: Mapped[list[PacketFile]] = relationship(
        back_populates="packet",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in PACKET_STATUSES) + ")",
            name="packets_status_check",
        ),
        CheckConstraint(
            "program_confirmation_status IS NULL OR program_confirmation_status IN ("
            + ", ".join(f"'{s}'" for s in CONFIRMATION_STATUSES)
            + ")",
            name="packets_program_confirmation_status_check",
        ),
        CheckConstraint(
            "review_state IS NULL OR review_state IN ("
            + ", ".join(f"'{s}'" for s in REVIEW_STATES)
            + ")",
            name="packets_review_state_check",
        ),
    )


class PacketFile(Base):
    """One uploaded document inside a `Packet`.

    `storage_key` is what the storage adapter reads/writes — bytes live
    there, this row just carries metadata the UI needs (filename, size,
    content-type) plus the key the pipeline will read from.
    """

    __tablename__ = "packet_files"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized so RLS can scope without joining packets.
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # SHA256 hex digest of the uploaded bytes. Drives deterministic-dedupe
    # at upload time: the same file + same program = reuse the existing
    # packet instead of re-running the LLM pipeline.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    packet: Mapped[Packet] = relationship(back_populates="files")


# Mirrors migration 0008's CHECK constraints. Kept here so any Python-side
# construction of an ECV row can reference the canonical set without a
# DB round-trip.
ECV_DOC_STATUSES: tuple[str, ...] = ("found", "missing")
ECV_PAGE_ISSUE_TYPES: tuple[str, ...] = ("blank_page", "low_quality", "rotated")


class EcvSection(Base):
    """One weighted validation section for a packet's ECV run.

    13 rows per packet today, keyed 1-13 by `section_number`. `score` is
    the per-section weighted score (0-100) that rolls up into the overall
    ECV score; `weight` is the relative weight applied during rollup.
    """

    __tablename__ = "ecv_sections"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    line_items: Mapped[list[EcvLineItem]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("packet_id", "section_number", name="ecv_sections_packet_section_unique"),
    )


class EcvDocument(Base):
    """One row of the MISMO-tagged document inventory for a packet.

    Maps 1:1 to the demo's `DOCUMENT_INVENTORY` entries — 23 found + 2
    missing for the seeded canned run. `page_issue_*` captures the
    per-page quality flags (blank / low-quality / rotated) shown in the
    Documents tab.
    """

    __tablename__ = "ecv_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mismo_type: Mapped[str] = mapped_column(String, nullable=False)
    pages_display: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    page_issue_type: Mapped[str | None] = mapped_column(String, nullable=True)
    page_issue_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    page_issue_affected_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in ECV_DOC_STATUSES) + ")",
            name="ecv_documents_status_check",
        ),
        CheckConstraint(
            "page_issue_type IS NULL OR page_issue_type IN ("
            + ", ".join(f"'{t}'" for t in ECV_PAGE_ISSUE_TYPES)
            + ")",
            name="ecv_documents_page_issue_type_check",
        ),
        UniqueConstraint("packet_id", "doc_number", name="ecv_documents_packet_doc_unique"),
    )


class EcvLineItem(Base):
    """One validation check inside an `EcvSection`.

    ~58 rows per packet for the seeded canned run. `mismo_path`,
    `document_id`, and `page_refs` are intentionally nullable — today's
    canned data leaves them unset, but the Phase 7 evidence / MISMO
    primitives will populate them without requiring another migration.
    """

    __tablename__ = "ecv_line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ecv_sections.id", ondelete="CASCADE"),
        nullable=False,
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_code: Mapped[str] = mapped_column(String, nullable=False)
    check_description: Mapped[str] = mapped_column(String, nullable=False)
    result_text: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    mismo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ecv_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    page_refs: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    # Downstream apps this check feeds. NULL / empty = core ECV check,
    # applies to every packet. Populated from `_CHECK_DEFS` at validate
    # time; see migration 0018.
    app_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    section: Mapped[EcvSection] = relationship(back_populates="line_items")

    __table_args__ = (
        UniqueConstraint("packet_id", "item_code", name="ecv_line_items_packet_item_unique"),
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ecv_line_items_confidence_range_check",
        ),
    )


class EcvExtraction(Base):
    """One MISMO 3.6 field extraction for a document (M3 of the ECV pipeline).

    Populated by the Vertex AI Gemini Pro extraction stage: one row per
    (document, MISMO path) pair, carrying the value plus the page + snippet
    that justifies it. Feeds the MISMO panel (US-7.3) and evidence panel
    (US-7.4). See migration 0016 for the table shape rationale.
    """

    __tablename__ = "ecv_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ecv_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    mismo_path: Mapped[str] = mapped_column(String, nullable=False)
    entity: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ecv_extractions_confidence_range_check",
        ),
    )


# Mirrors migration 0010's CHECK constraints. Compliance check outcomes
# follow the demo: pass / fail / warn / n/a. Fee tolerance rows don't
# have an `n/a` state — a bucket either passes, is a warning, or fails.
COMPLIANCE_CHECK_STATUSES: tuple[str, ...] = ("pass", "fail", "warn", "n/a")
COMPLIANCE_TOLERANCE_STATUSES: tuple[str, ...] = ("pass", "fail", "warn")

# Mirrors migration 0015's CHECK constraints. The 6-way check_type bucket
# maps 1:1 to the `categories` array keys in the TI-parity
# `ComplianceOutput` interface. Severities are shared across checks,
# fee tolerances, and the top-level findings rollup so downstream rendering
# stays consistent across the three surfaces.
COMPLIANCE_CHECK_TYPES: tuple[str, ...] = (
    "disclosure_timing",
    "fee_tolerance",
    "required_disclosure",
    "program_specific",
    "fair_lending",
    "state_specific",
)
COMPLIANCE_SEVERITIES: tuple[str, ...] = ("critical", "warning", "info")
COMPLIANCE_FEE_CATEGORIES: tuple[str, ...] = (
    "zero_tolerance",
    "ten_percent",
    "no_tolerance",
)


class ComplianceCheck(Base):
    """One regulatory compliance check run against a packet (US-6.3).

    Ported from the demo's `COMPLIANCE_CHECKS` — C-01 through C-10 in
    the canned seed, covering TRID / RESPA / ECOA / HMDA / state-specific
    disclosures / escrow. `mismo_fields` carries the supporting MISMO
    3.6 extractions (entity / field / value / confidence) so the
    Violations tab can render the MISMO panel without another round trip.
    """

    __tablename__ = "compliance_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    check_code: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    rule: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismo_fields: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    # TI-parity extensions (migration 0015). `check_type` is the 6-way
    # bucket key the frontend groups by. `details` carries the
    # category-specific structured data (timing deadlines for
    # disclosure_timing, disclosureName + found + signedByBorrower for
    # required_disclosure, etc.) so the wire shape stays typed without
    # adding a column per category.
    check_type: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    citation: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in COMPLIANCE_CHECK_STATUSES) + ")",
            name="compliance_checks_status_check",
        ),
        CheckConstraint(
            "check_type IS NULL OR check_type IN ("
            + ", ".join(f"'{t}'" for t in COMPLIANCE_CHECK_TYPES)
            + ")",
            name="compliance_checks_check_type_check",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ("
            + ", ".join(f"'{s}'" for s in COMPLIANCE_SEVERITIES)
            + ")",
            name="compliance_checks_severity_check",
        ),
        UniqueConstraint("packet_id", "check_code", name="compliance_checks_packet_code_unique"),
    )


class ComplianceFeeTolerance(Base):
    """One TRID fee-tolerance bucket comparison (LE vs CD) per packet.

    Three rows per packet — Zero / 10% / Unlimited — each with the LE
    amount, CD amount, difference, computed variance percentage, and a
    pass/warn/fail status. Currency strings are preserved verbatim as
    the demo shows them so the wire shape can render directly.
    """

    __tablename__ = "compliance_fee_tolerances"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket: Mapped[str] = mapped_column(String, nullable=False)
    le_amount: Mapped[str] = mapped_column(String, nullable=False)
    cd_amount: Mapped[str] = mapped_column(String, nullable=False)
    diff_amount: Mapped[str] = mapped_column(String, nullable=False)
    variance_pct: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # TI-parity extensions (migration 0015). Numeric amounts sit alongside
    # the pre-formatted strings so the `FeeToleranceCheck` interface can
    # expose `loanEstimate.amount` / `closingDisclosure.amount` as typed
    # numbers. `cure_amount` is populated when status == "cure_required".
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    citation: Mapped[str | None] = mapped_column(String, nullable=True)
    fee_name: Mapped[str | None] = mapped_column(String, nullable=True)
    fee_category: Mapped[str | None] = mapped_column(String, nullable=True)
    le_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    cd_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    cure_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    le_amount_num: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    cd_amount_num: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in COMPLIANCE_TOLERANCE_STATUSES) + ")",
            name="compliance_fee_tolerances_status_check",
        ),
        CheckConstraint(
            "fee_category IS NULL OR fee_category IN ("
            + ", ".join(f"'{c}'" for c in COMPLIANCE_FEE_CATEGORIES)
            + ")",
            name="compliance_fee_tolerances_fee_category_check",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ("
            + ", ".join(f"'{s}'" for s in COMPLIANCE_SEVERITIES)
            + ")",
            name="compliance_fee_tolerances_severity_check",
        ),
        UniqueConstraint(
            "packet_id", "bucket", name="compliance_fee_tolerances_packet_bucket_unique"
        ),
    )


# Mirrors migration 0011's CHECK constraints. Income trend labels follow
# the demo: stable / increasing / decreasing. Confidence is bounded 0-100
# same as ECV line items.
INCOME_TRENDS: tuple[str, ...] = ("stable", "increasing", "decreasing")

# Mirrors migration 0015's CHECK constraints. The two-way category split
# lets the router partition employment vs non-employment sources per the
# TI-parity `BorrowerIncome` interface shape.
INCOME_CATEGORIES: tuple[str, ...] = ("employment", "non_employment")
INCOME_EMPLOYMENT_TYPES: tuple[str, ...] = ("w2", "self_employed", "1099", "military")
INCOME_FINDING_SEVERITIES: tuple[str, ...] = ("critical", "review", "info")
INCOME_FINDING_CATEGORIES: tuple[str, ...] = (
    "missing_doc",
    "variance",
    "trending_concern",
    "dti_exceeded",
    "incomplete_verification",
)


class IncomeSource(Base):
    """One income source for a packet's Income Calculation run (US-6.4).

    Ported from the demo's `INCOME_SOURCES` — I-01 through I-04 in the
    canned seed, covering base W-2, overtime, bonus, and rental. Currency
    amounts stay NUMERIC so server-side rollups (total monthly / annual)
    remain exact; `docs` is the array of supporting document names used by
    the expanded row's "Docs" cell, `mismo_fields` carries the same
    entity/field/value/confidence shape as Compliance.
    """

    __tablename__ = "income_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_code: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    employer: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    income_type: Mapped[str] = mapped_column(String, nullable=False)
    monthly_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    annual_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    trend: Mapped[str] = mapped_column(String, nullable=False)
    years_history: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismo_fields: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    docs: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # TI-parity extensions (migration 0015). Every new column is nullable
    # because existing rows predate this schema change; the seed writes
    # them all in a single pass via the updated ecv stub.
    borrower_id: Mapped[str | None] = mapped_column(String, nullable=True)
    borrower_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    tenure_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_salary: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    overtime: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    bonus: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    commission: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    total_qualifying: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    voe: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    mismo_paths: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    stated_monthly: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    verified_monthly: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "trend IN (" + ", ".join(f"'{t}'" for t in INCOME_TRENDS) + ")",
            name="income_sources_trend_check",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="income_sources_confidence_range_check",
        ),
        CheckConstraint(
            "category IS NULL OR category IN ("
            + ", ".join(f"'{c}'" for c in INCOME_CATEGORIES)
            + ")",
            name="income_sources_category_check",
        ),
        CheckConstraint(
            "employment_type IS NULL OR employment_type IN ("
            + ", ".join(f"'{e}'" for e in INCOME_EMPLOYMENT_TYPES)
            + ")",
            name="income_sources_employment_type_check",
        ),
        UniqueConstraint("packet_id", "source_code", name="income_sources_packet_code_unique"),
    )


class IncomeDtiItem(Base):
    """One monthly obligation feeding the DTI rollup for a packet.

    Ported from the demo's `DTI_ITEMS` — PITIA (housing) plus each
    recurring debt. Amount stays NUMERIC for exact rollup; `sort_order`
    preserves the demo's housing-first ordering regardless of insert
    timing.
    """

    __tablename__ = "income_dti_items"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    monthly_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class IncomeFinding(Base):
    """One consolidated income finding for a packet (US-6.4).

    Mirrors the `Finding[]` array in the TI-parity
    `IncomeCalculationOutput` interface. `category` is the narrow taxonomy
    the underwriter filters by (missing_doc / variance / trending_concern
    / dti_exceeded / incomplete_verification); `affected_sources` and
    `mismo_refs` are JSONB arrays of the document + MISMO field IDs tying
    the finding back to evidence.
    """

    __tablename__ = "income_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    affected_sources: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    mismo_refs: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in INCOME_FINDING_SEVERITIES) + ")",
            name="income_findings_severity_check",
        ),
        CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in INCOME_FINDING_CATEGORIES) + ")",
            name="income_findings_category_check",
        ),
        UniqueConstraint("packet_id", "finding_id", name="income_findings_packet_finding_unique"),
    )


class IncomePacketMetadata(Base):
    """Per-packet metadata for the Income Calculation output (US-6.4).

    Singleton row per packet (unique on `packet_id`). Holds the applied-
    rules bundle that drove the calculation, the optional VA residual-
    income block, the packet-level evidence trace, and the overall
    confidence score — fields that don't belong on any single income
    source row.
    """

    __tablename__ = "income_packet_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    applied_rules: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    residual_income: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="income_packet_metadata_confidence_range_check",
        ),
    )


class ComplianceFinding(Base):
    """One consolidated compliance finding for a packet (US-6.3).

    Mirrors the `ComplianceFinding` interface: findingId, severity,
    ruleId, description, impact, recommendation, optional automated
    curative action, regulatoryCitation, affected parties, and MISMO
    field refs. Findings are derived from the pass/fail/warn rows in
    `compliance_checks` plus the fee-tolerance analysis, but persisted
    as first-class rows so the UI can render them without recomputing.
    """

    __tablename__ = "compliance_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    curative: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    regulatory_citation: Mapped[str] = mapped_column(String, nullable=False)
    affected_parties: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    mismo_refs: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in COMPLIANCE_SEVERITIES) + ")",
            name="compliance_findings_severity_check",
        ),
        UniqueConstraint(
            "packet_id", "finding_id", name="compliance_findings_packet_finding_unique"
        ),
    )


class CompliancePacketMetadata(Base):
    """Per-packet metadata for the Compliance output (US-6.3).

    Singleton row per packet. Holds the applied regulatory framework
    (CFPB + HUD, disclosure set, investor overlays), the applied-rules
    bundle (programId + rule-set version + state code), the packet-level
    evidence trace, and the overall confidence score.
    """

    __tablename__ = "compliance_packet_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    applied_framework: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    applied_rules: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="compliance_packet_metadata_confidence_range_check",
        ),
    )


# Mirrors migration 0012's CHECK constraints. Risk severities follow the
# demo: critical / high / medium / low. AI recommendation decisions are
# the same three the Phase 7 AiRecommendation component uses.
TITLE_FLAG_SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
TITLE_AI_DECISIONS: tuple[str, ...] = ("approve", "reject", "escalate")


class TitleFlag(Base):
    """One risk flag for a packet's Title Search & Abstraction run (US-6.1).

    Ported from the demo's `TITLE_FLAGS` — 7 flags in the canned seed,
    covering unreleased liens, chain-of-title gaps, non-standard
    easements, name discrepancies, missing endorsements, delinquent
    taxes, and vesting issues. `mismo_fields`, `source`, `evidence`,
    and `cross_app` are JSONB so the Flags tab can render the Review
    dialog (Phase 7 primitives) without additional round trips.
    """

    __tablename__ = "title_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    flag_number: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    flag_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    page_ref: Mapped[str] = mapped_column(String, nullable=False)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_rec_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_rec_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_rec_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismo_fields: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    source: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    cross_app: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in TITLE_FLAG_SEVERITIES) + ")",
            name="title_flags_severity_check",
        ),
        CheckConstraint(
            "ai_rec_decision IS NULL OR ai_rec_decision IN ("
            + ", ".join(f"'{d}'" for d in TITLE_AI_DECISIONS)
            + ")",
            name="title_flags_ai_decision_check",
        ),
        CheckConstraint(
            "ai_rec_confidence IS NULL OR (ai_rec_confidence BETWEEN 0 AND 100)",
            name="title_flags_ai_confidence_range_check",
        ),
        UniqueConstraint("packet_id", "flag_number", name="title_flags_packet_number_unique"),
    )


class TitleProperty(Base):
    """The full PROPERTY_SUMMARY payload for a packet's title run.

    Stored as a single JSONB document because the frontend consumes it
    as a nested structure (property ID → physical → chain of title[] →
    mortgages[] → liens[] → easements[] → taxes → title_insurance).
    Over-normalizing would just re-introduce joins on the API layer for
    no gain; a single NoSQL-shaped blob is the pragmatic choice until
    real title data pipelines materialize and we can pick the right
    per-entity schema.
    """

    __tablename__ = "title_properties"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("packet_id", name="title_properties_packet_unique"),)


# ═══════════════════════════════════════════════════════════════════════
# Title Examination (US-6.2)
# ═══════════════════════════════════════════════════════════════════════

TITLE_EXAM_SCHEDULES: tuple[str, ...] = ("standard", "specific")
TITLE_EXAM_PRIORITIES: tuple[str, ...] = ("must_close", "should_close", "recommended")
TITLE_EXAM_REQUIREMENT_STATUSES: tuple[str, ...] = (
    "open",
    "requested",
    "provided",
    "not_ordered",
)

# Flag taxonomy — superset of Title Intelligence Hub's ExaminerFlag.flag_type
# values (title_intelligence_hub/.../schemas/examiner.py). Every TI Hub type
# is included so One_Logikality's title-exam structured output is strictly a
# superset of TI Hub's. Nullable on the column so legacy/standard ALTA
# exceptions that don't map to a risk taxonomy can omit it.
TITLE_EXAM_FLAG_TYPES: tuple[str, ...] = (
    "missing_endorsement",
    "unacceptable_exception",
    "unresolved_lien",
    "unreleased_mortgage",
    "cross_section_mismatch",
    "requirement_missing_proof",
    "name_discrepancy",
    "marital_status_issue",
    "incomplete_document",
    "regulatory_compliance",
    "chain_of_title_gap",
    "document_defect",
    "mineral_rights",
    "trust_issue",
    "estate_issue",
    "vesting_issue",
    "tax_issue",
)

# Per-flag lifecycle — matches TI Hub's flag.status field.
TITLE_EXAM_FLAG_STATUSES: tuple[str, ...] = ("open", "reviewed", "closed")

# Review verdicts — matches TI Hub's ReviewCreate.decision pattern.
TITLE_EXAM_REVIEW_DECISIONS: tuple[str, ...] = ("approve", "reject", "escalate")

# Polymorphic review target — reviews can be recorded against exceptions or
# warnings (both are "flags" in TI Hub vocabulary).
TITLE_EXAM_FLAG_KINDS: tuple[str, ...] = ("exception", "warning")


class TitleExamException(Base):
    """Schedule B exception (standard or specific) for a packet's title exam.

    Ported from the demo's STANDARD_EXCEPTIONS + SPECIFIC_EXCEPTIONS so the
    Title Exam page's Schedule B accordion can hydrate from server state.
    """

    __tablename__ = "title_exam_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule: Mapped[str] = mapped_column(String, nullable=False)
    exception_number: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    page_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TI Hub superset fields — nullable so boilerplate ALTA exceptions
    # without a risk taxonomy (e.g. "taxes not yet due") can omit them.
    flag_type: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="open")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "schedule IN (" + ", ".join(f"'{s}'" for s in TITLE_EXAM_SCHEDULES) + ")",
            name="title_exam_exceptions_schedule_check",
        ),
        CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in TITLE_FLAG_SEVERITIES) + ")",
            name="title_exam_exceptions_severity_check",
        ),
        CheckConstraint(
            "flag_type IS NULL OR flag_type IN ("
            + ", ".join(f"'{t}'" for t in TITLE_EXAM_FLAG_TYPES)
            + ")",
            name="title_exam_exceptions_flag_type_check",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in TITLE_EXAM_FLAG_STATUSES) + ")",
            name="title_exam_exceptions_status_check",
        ),
        UniqueConstraint(
            "packet_id",
            "schedule",
            "exception_number",
            name="title_exam_exceptions_packet_schedule_number_unique",
        ),
    )


class TitleExamRequirement(Base):
    """Schedule C requirement — the examiner's list of things that must be
    satisfied before policy issuance. Status transitions through
    open → requested → provided (or not_ordered for the survey path)."""

    __tablename__ = "title_exam_requirements"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    page_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TI Hub-parity transparency fields on requirements too — the TI Hub
    # ExaminerExtraction.evidence_refs shape applies here.
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "priority IN (" + ", ".join(f"'{p}'" for p in TITLE_EXAM_PRIORITIES) + ")",
            name="title_exam_requirements_priority_check",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in TITLE_EXAM_REQUIREMENT_STATUSES) + ")",
            name="title_exam_requirements_status_check",
        ),
        UniqueConstraint(
            "packet_id",
            "requirement_number",
            name="title_exam_requirements_packet_number_unique",
        ),
    )


class TitleExamWarning(Base):
    """Examiner warnings — severity-scoped free-form observations that
    accompany the Schedule B/C output."""

    __tablename__ = "title_exam_warnings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TI Hub superset fields on warnings — warnings are "flags" in TI Hub
    # vocabulary so they carry the same transparency shape.
    flag_type: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="open")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in TITLE_FLAG_SEVERITIES) + ")",
            name="title_exam_warnings_severity_check",
        ),
        CheckConstraint(
            "flag_type IS NULL OR flag_type IN ("
            + ", ".join(f"'{t}'" for t in TITLE_EXAM_FLAG_TYPES)
            + ")",
            name="title_exam_warnings_flag_type_check",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in TITLE_EXAM_FLAG_STATUSES) + ")",
            name="title_exam_warnings_status_check",
        ),
    )


class TitleExamChecklistItem(Base):
    """Curative workflow state (US-6.2).

    Each row is one curative action; `checked` is the state primitive
    that the frontend toggles via PATCH. Unchecked-on-seed; the demo
    data pre-seeds a few as completed so the UI shows progress out of
    the box.
    """

    __tablename__ = "title_exam_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "packet_id",
            "item_number",
            name="title_exam_checklist_items_packet_number_unique",
        ),
    )


class TitleExamReview(Base):
    """Per-flag reviewer decision — mirrors TI Hub's `reviews` table.

    Reviews are polymorphic across `title_exam_exceptions` (Schedule B) and
    `title_exam_warnings` (examiner warnings) — both are "flags" in TI Hub
    vocabulary. `flag_kind` + `flag_id` pick the target row. No hard FK
    because the target lives in one of two tables; integrity is instead
    enforced by the INSERT endpoint verifying the row exists and belongs
    to the packet/org. `packet_id` + `org_id` are denormalized so RLS can
    scope reads without a join.
    """

    __tablename__ = "title_exam_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    flag_kind: Mapped[str] = mapped_column(String, nullable=False)
    flag_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "flag_kind IN (" + ", ".join(f"'{k}'" for k in TITLE_EXAM_FLAG_KINDS) + ")",
            name="title_exam_reviews_flag_kind_check",
        ),
        CheckConstraint(
            "decision IN (" + ", ".join(f"'{d}'" for d in TITLE_EXAM_REVIEW_DECISIONS) + ")",
            name="title_exam_reviews_decision_check",
        ),
    )
