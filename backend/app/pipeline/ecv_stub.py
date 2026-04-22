"""Deterministic ECV pipeline stub (US-3.4).

Fakes the multi-stage ECV pipeline so the upload → processing animation
can sync to real server state before the Temporal workflow lands.
Stages match `PIPELINE_STAGES` exactly — ingest / classify / extract /
validate / score / route — so the frontend `PipelineProgress` can port
the demo's labels/icons without translation.

Scheduled as a FastAPI `BackgroundTask` from `POST /api/packets`; runs
after the response is sent. Tests monkeypatch `STAGE_DELAY_SECONDS` to
something tiny so the polling loop terminates quickly without depending
on real time.

Background tasks don't carry the request's auth context, so writes go
through the default connection role (postgres superuser in local dev),
bypassing RLS intentionally — this is server-internal orchestration,
not a tenant-scoped request. The real ECV pipeline (Temporal workflow)
will run under a service identity that still enforces tenant isolation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import (
    ComplianceCheck,
    ComplianceFeeTolerance,
    ComplianceFinding,
    CompliancePacketMetadata,
    EcvDocument,
    EcvLineItem,
    EcvSection,
    IncomeDtiItem,
    IncomeFinding,
    IncomePacketMetadata,
    IncomeSource,
    Packet,
    TitleExamChecklistItem,
    TitleExamException,
    TitleExamRequirement,
    TitleExamWarning,
    TitleFlag,
    TitleProperty,
)
from app.pipeline.classify import classify_packet
from app.pipeline.compliance_data import (
    APPLIED_FRAMEWORK as COMPLIANCE_APPLIED_FRAMEWORK,
)
from app.pipeline.compliance_data import (
    APPLIED_RULES as COMPLIANCE_APPLIED_RULES,
)
from app.pipeline.compliance_data import (
    COMPLIANCE_CHECKS,
    COMPLIANCE_EVIDENCE,
    COMPLIANCE_FINDINGS,
    TOLERANCE_TABLE,
)
from app.pipeline.compliance_data import (
    OVERALL_CONFIDENCE as COMPLIANCE_CONFIDENCE,
)
from app.pipeline.ecv_data import (
    CONFIRMATION_BY_PROGRAM,
    DOCUMENT_INVENTORY,
    ECV_LINE_ITEMS,
    ECV_SECTIONS,
)
from app.pipeline.extract import extract_packet
from app.pipeline.income_data import (
    APPLIED_RULES as INCOME_APPLIED_RULES,
)
from app.pipeline.income_data import (
    DTI_ITEMS,
    INCOME_EVIDENCE,
    INCOME_FINDINGS,
    INCOME_SOURCES,
    RESIDUAL_INCOME,
)
from app.pipeline.income_data import (
    OVERALL_CONFIDENCE as INCOME_CONFIDENCE,
)
from app.pipeline.title_exam_data import (
    CHECKLIST_ITEMS,
    REQUIREMENTS,
    SPECIFIC_EXCEPTIONS,
    STANDARD_EXCEPTIONS,
    WARNINGS,
)
from app.pipeline.title_search_data import PROPERTY_SUMMARY, TITLE_FLAGS
from app.pipeline.validate import validate_packet

log = logging.getLogger(__name__)

# Ordered, frozen — consumed by both the stub runner and the migration
# 0007 CHECK constraint. If this tuple changes, migration 0007 needs a
# follow-up to widen the allowed values.
PIPELINE_STAGES: tuple[str, ...] = (
    "ingest",
    "classify",
    "extract",
    "validate",
    "score",
    "route",
)

# Per-stage wall-clock delay. Kept small so the pipeline isn't artificially
# slowed by UI animation fluff — the real work (classify/extract/validate
# LLM calls) dominates total time. Tests monkeypatch this to ~0.01s for
# fast polling; 0.1s in prod gives the PipelineProgress component a visible
# tick between stages without adding meaningful latency.
STAGE_DELAY_SECONDS: float = 0.1


def _parse_date(value: str | None) -> date | None:
    """ISO yyyy-mm-dd → date. Tolerates None so callers can pass optional seeds."""
    if value is None:
        return None
    return date.fromisoformat(value)


def _encode_trending(t: Any | None) -> dict[str, Any] | None:
    """Serialize an income-source overtime block (amount + method + trending).

    Decimals are stringified so the JSONB column stays stable across
    serialization roundtrips (Python Decimal doesn't map cleanly to JSON).
    """
    if t is None:
        return None
    return {
        "amount": str(t["amount"]),
        "method": t["method"],
        "trending": t["trending"],
    }


def _encode_method(m: Any | None) -> dict[str, Any] | None:
    """Serialize an income-source bonus / commission block (amount + method)."""
    if m is None:
        return None
    return {"amount": str(m["amount"]), "method": m["method"]}


async def run_ecv_stub(packet_id: uuid.UUID) -> None:
    """Walk a packet through the pipeline stages, updating its row after each.

    Flow: flip to `processing` + `started_processing_at`, then per stage
    write `current_stage=<stage>` and sleep, then flip to `completed` +
    `completed_at`. Any exception flips the packet to `failed` so the UI
    polling loop doesn't hang forever.
    """
    try:
        started = datetime.now(UTC)
        async with SessionLocal() as session:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(status="processing", started_processing_at=started)
            )
            await session.commit()

        for stage in PIPELINE_STAGES:
            async with SessionLocal() as session:
                await session.execute(
                    update(Packet).where(Packet.id == packet_id).values(current_stage=stage)
                )
                await session.commit()
            if stage == "score":
                # Persist the canned findings as the `score` stage's
                # "output". Writes bypass RLS (no tenant context set on
                # SessionLocal) because this is internal orchestration —
                # the real workflow runs under a service identity that
                # still enforces tenant scoping.
                await _persist_findings(packet_id)
            # Module-attribute lookup so monkeypatching works without
            # callers having to re-import the value.
            await asyncio.sleep(STAGE_DELAY_SECONDS)

        async with SessionLocal() as session:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception:
        log.exception("ECV stub failed for packet %s", packet_id)
        try:
            async with SessionLocal() as session:
                await session.execute(
                    update(Packet).where(Packet.id == packet_id).values(status="failed")
                )
                await session.commit()
        except Exception:
            log.exception("also failed to mark packet %s as failed", packet_id)


async def _persist_findings(packet_id: uuid.UUID) -> None:
    """Persist classified docs + downstream micro-app rows for this packet.

    ECV sections + line items are NOT written here as of M4 — the
    `validate` stage writes them after this function commits, reading the
    docs + extractions we persist below. Compliance / Income / Title
    rows are canned seed data pending each micro-app's own pipeline
    build-out (Phase 6); they're written here so the downstream tabs
    hydrate as soon as processing completes.

    Re-running against a packet that already has findings would trip
    unique constraints, so we short-circuit when ECV sections already
    exist. That makes the stub safe to replay in dev after a hot reload.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvSection.id).where(EcvSection.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        packet_row = (
            await session.execute(
                select(Packet.org_id, Packet.declared_program_id).where(Packet.id == packet_id)
            )
        ).one_or_none()
        if packet_row is None:
            log.warning("stub: packet %s vanished before findings write", packet_id)
            return
        org_id, declared_program_id = packet_row

        # M2: Real classification via Gemini Flash (Vertex AI). Reads the
        # uploaded PDFs, asks Gemini to label each page, groups consecutive
        # same-class pages into documents, and writes real EcvDocument rows.
        # On failure (e.g. no AI keys) we fall back to the canned
        # DOCUMENT_INVENTORY so the Documents tab still shows meaningful data.
        try:
            classified = await classify_packet(packet_id)
            doc_rows: list[EcvDocument] = [
                EcvDocument(
                    packet_id=packet_id,
                    org_id=org_id,
                    doc_number=idx,
                    name=doc["name"],
                    mismo_type=doc["mismo_type"],
                    pages_display=doc["pages_display"],
                    page_count=doc["page_count"],
                    confidence=doc["confidence"],
                    status=doc["status"],
                    category=doc["category"],
                    page_issue_type=doc.get("page_issue_type"),
                    page_issue_detail=doc.get("page_issue_detail"),
                    page_issue_affected_page=doc.get("page_issue_affected_page"),
                )
                for idx, doc in enumerate(classified, start=1)
            ]
        except Exception:
            log.exception("classify_packet failed for %s — using canned document inventory", packet_id)
            doc_rows = [
                EcvDocument(
                    packet_id=packet_id,
                    org_id=org_id,
                    doc_number=doc["id"],
                    name=doc["name"],
                    mismo_type=doc["mismo_type"],
                    pages_display=doc["pages"],
                    page_count=doc["page_count"],
                    confidence=doc["confidence"],
                    status=doc["status"],
                    category=doc["category"],
                    page_issue_type=doc["page_issue"]["type"] if doc.get("page_issue") else None,
                    page_issue_detail=doc["page_issue"]["detail"] if doc.get("page_issue") else None,
                    page_issue_affected_page=doc["page_issue"]["affected_page"] if doc.get("page_issue") else None,
                )
                for doc in DOCUMENT_INVENTORY
            ]
        session.add_all(doc_rows)

        # Compliance findings (US-6.3). The Compliance micro-app consumes
        # ECV's MISMO inventory to run TRID / RESPA / ECOA / HMDA /
        # state-specific checks; we persist the canned verdicts alongside
        # the ECV rows during the same `score` stage so the Compliance
        # page can hydrate the moment processing completes.
        compliance_rows: list[ComplianceCheck] = [
            ComplianceCheck(
                packet_id=packet_id,
                org_id=org_id,
                check_code=check["code"],
                category=check["category"],
                rule=check["rule"],
                status=check["status"],
                detail=check["detail"],
                ai_note=check["ai_note"],
                mismo_fields=[dict(f) for f in check["mismo"]],
                check_type=check["check_type"],
                rule_id=check["rule_id"],
                citation=check["citation"],
                severity=check["severity"],
                details=dict(check["details"]),
            )
            for check in COMPLIANCE_CHECKS
        ]
        session.add_all(compliance_rows)

        tolerance_rows: list[ComplianceFeeTolerance] = [
            ComplianceFeeTolerance(
                packet_id=packet_id,
                org_id=org_id,
                bucket=row["bucket"],
                le_amount=row["le"],
                cd_amount=row["cd"],
                diff_amount=row["diff"],
                variance_pct=row["pct"],
                status=row["status"],
                sort_order=i,
                rule_id=row["rule_id"],
                citation=row["citation"],
                fee_name=row["fee_name"],
                fee_category=row["fee_category"],
                le_date=_parse_date(row["le_date"]),
                cd_date=_parse_date(row["cd_date"]),
                severity=row["severity"],
                cure_amount=row["cure_amount"],
                le_amount_num=row["le_amount_num"],
                cd_amount_num=row["cd_amount_num"],
            )
            for i, row in enumerate(TOLERANCE_TABLE)
        ]
        session.add_all(tolerance_rows)

        # TI-parity packet-level metadata: applied framework, applied
        # rules, evidence trace, and overall confidence for the
        # Compliance output interface's top-level fields.
        session.add(
            CompliancePacketMetadata(
                packet_id=packet_id,
                org_id=org_id,
                applied_framework={
                    "regulatory": COMPLIANCE_APPLIED_FRAMEWORK["regulatory"],
                    "disclosure_set": COMPLIANCE_APPLIED_FRAMEWORK["disclosure_set"],
                    "program_overlays": list(COMPLIANCE_APPLIED_FRAMEWORK["program_overlays"]),
                },
                applied_rules=dict(COMPLIANCE_APPLIED_RULES),
                evidence=[dict(e) for e in COMPLIANCE_EVIDENCE],
                confidence=COMPLIANCE_CONFIDENCE,
            )
        )

        compliance_finding_rows: list[ComplianceFinding] = [
            ComplianceFinding(
                packet_id=packet_id,
                org_id=org_id,
                finding_id=f["finding_id"],
                severity=f["severity"],
                category=f["category"],
                rule_id=f["rule_id"],
                description=f["description"],
                impact=f["impact"],
                recommendation=f["recommendation"],
                curative=dict(f["curative"]) if f["curative"] else None,
                regulatory_citation=f["regulatory_citation"],
                affected_parties=list(f["affected_parties"]),
                mismo_refs=list(f["mismo_refs"]),
                sort_order=i,
            )
            for i, f in enumerate(COMPLIANCE_FINDINGS)
        ]
        session.add_all(compliance_finding_rows)

        # Income Calculation findings (US-6.4). Base / overtime / bonus /
        # rental sources plus the monthly obligations that feed the DTI
        # rollup. Same transaction, same `score` stage — the Income tab
        # hydrates as soon as processing completes.
        income_rows: list[IncomeSource] = [
            IncomeSource(
                packet_id=packet_id,
                org_id=org_id,
                source_code=src["code"],
                source_name=src["source_name"],
                employer=src["employer"],
                position=src["position"],
                income_type=src["income_type"],
                monthly_amount=src["monthly"],
                annual_amount=src["annual"],
                trend=src["trend"],
                years_history=src["years"],
                confidence=src["confidence"],
                ai_note=src["ai_note"],
                mismo_fields=[dict(f) for f in src["mismo"]],
                docs=list(src["docs"]),
                sort_order=i,
                # TI-parity per-source columns (migration 0015).
                borrower_id=src["borrower_id"],
                borrower_name=src["borrower_name"],
                category=src["category"],
                employment_type=src["employment_type"],
                start_date=_parse_date(src["start_date"]),
                tenure_years=src["tenure_years"],
                tenure_months=src["tenure_months"],
                base_salary=src["base_salary"],
                overtime=_encode_trending(src["overtime"]),
                bonus=_encode_method(src["bonus"]),
                commission=_encode_method(src["commission"]),
                total_qualifying=src["total_qualifying"],
                voe=dict(src["voe"]) if src["voe"] else None,
                mismo_paths=dict(src["mismo_paths"]) if src["mismo_paths"] else None,
                stated_monthly=src["stated_monthly"],
                verified_monthly=src["verified_monthly"],
            )
            for i, src in enumerate(INCOME_SOURCES)
        ]
        session.add_all(income_rows)

        dti_rows: list[IncomeDtiItem] = [
            IncomeDtiItem(
                packet_id=packet_id,
                org_id=org_id,
                description=row["description"],
                monthly_amount=row["monthly"],
                sort_order=i,
            )
            for i, row in enumerate(DTI_ITEMS)
        ]
        session.add_all(dti_rows)

        # TI-parity packet-level income metadata + findings.
        session.add(
            IncomePacketMetadata(
                packet_id=packet_id,
                org_id=org_id,
                applied_rules=dict(INCOME_APPLIED_RULES),
                residual_income=(
                    {
                        "net_monthly_income": str(RESIDUAL_INCOME["net_monthly_income"]),
                        "total_obligations": str(RESIDUAL_INCOME["total_obligations"]),
                        "residual": str(RESIDUAL_INCOME["residual"]),
                        "regional_table": RESIDUAL_INCOME["regional_table"],
                        "required_residual": str(RESIDUAL_INCOME["required_residual"]),
                        "meets_requirement": RESIDUAL_INCOME["meets_requirement"],
                    }
                    if RESIDUAL_INCOME is not None
                    else None
                ),
                evidence=[dict(e) for e in INCOME_EVIDENCE],
                confidence=INCOME_CONFIDENCE,
            )
        )

        income_finding_rows: list[IncomeFinding] = [
            IncomeFinding(
                packet_id=packet_id,
                org_id=org_id,
                finding_id=f["finding_id"],
                severity=f["severity"],
                category=f["category"],
                description=f["description"],
                recommendation=f["recommendation"],
                affected_sources=list(f["affected_sources"]),
                mismo_refs=list(f["mismo_refs"]),
                sort_order=i,
            )
            for i, f in enumerate(INCOME_FINDINGS)
        ]
        session.add_all(income_finding_rows)

        # Title Search & Abstraction findings (US-6.1). 7 canned flags
        # (severity + AI recommendation + MISMO + evidence + optional
        # cross-app ref) plus a singleton property summary JSONB blob.
        title_flag_rows: list[TitleFlag] = [
            TitleFlag(
                packet_id=packet_id,
                org_id=org_id,
                flag_number=flag["number"],
                severity=flag["severity"],
                flag_type=flag["flag_type"],
                title=flag["title"],
                description=flag["description"],
                page_ref=flag["page_ref"],
                ai_note=flag["ai_note"],
                ai_rec_decision=flag["ai_rec"]["decision"],
                ai_rec_confidence=flag["ai_rec"]["confidence"],
                ai_rec_reasoning=flag["ai_rec"]["reasoning"],
                mismo_fields=[dict(f) for f in flag["mismo"]],
                source={
                    "doc_type": flag["source"]["doc_type"],
                    "pages": list(flag["source"]["pages"]),
                },
                cross_app=dict(flag["cross_app"]) if flag["cross_app"] else None,
                evidence=[dict(e) for e in flag["evidence"]],
                sort_order=i,
            )
            for i, flag in enumerate(TITLE_FLAGS)
        ]
        session.add_all(title_flag_rows)

        session.add(
            TitleProperty(
                packet_id=packet_id,
                org_id=org_id,
                summary=PROPERTY_SUMMARY,
            )
        )

        # Title Examination findings (US-6.2). Schedule B (standard +
        # specific), Schedule C requirements, examiner warnings, and
        # the curative checklist — the curative-workflow state primitive
        # is `checked` on each checklist row, which the frontend PATCHes
        # as the underwriter marks items complete.
        schedule_b_rows: list[TitleExamException] = []
        for i, exc in enumerate(STANDARD_EXCEPTIONS):
            schedule_b_rows.append(
                TitleExamException(
                    packet_id=packet_id,
                    org_id=org_id,
                    schedule="standard",
                    exception_number=exc["number"],
                    severity=exc["severity"],
                    title=exc["title"],
                    description=exc["description"],
                    page_ref=exc["page_ref"],
                    note=exc["note"],
                    flag_type=exc["flag_type"],
                    ai_explanation=exc["ai_explanation"],
                    evidence_refs=exc["evidence_refs"],
                    sort_order=i,
                )
            )
        offset = len(STANDARD_EXCEPTIONS)
        for i, exc in enumerate(SPECIFIC_EXCEPTIONS):
            schedule_b_rows.append(
                TitleExamException(
                    packet_id=packet_id,
                    org_id=org_id,
                    schedule="specific",
                    exception_number=exc["number"],
                    severity=exc["severity"],
                    title=exc["title"],
                    description=exc["description"],
                    page_ref=exc["page_ref"],
                    note=exc["note"],
                    flag_type=exc["flag_type"],
                    ai_explanation=exc["ai_explanation"],
                    evidence_refs=exc["evidence_refs"],
                    sort_order=offset + i,
                )
            )
        session.add_all(schedule_b_rows)

        requirement_rows: list[TitleExamRequirement] = [
            TitleExamRequirement(
                packet_id=packet_id,
                org_id=org_id,
                requirement_number=req["number"],
                title=req["title"],
                priority=req["priority"],
                status=req["status"],
                page_ref=req["page_ref"],
                description=req["description"],
                note=req["note"],
                ai_explanation=req["ai_explanation"],
                evidence_refs=req["evidence_refs"],
                sort_order=i,
            )
            for i, req in enumerate(REQUIREMENTS)
        ]
        session.add_all(requirement_rows)

        warning_rows: list[TitleExamWarning] = [
            TitleExamWarning(
                packet_id=packet_id,
                org_id=org_id,
                severity=w["severity"],
                title=w["title"],
                description=w["description"],
                note=w["note"],
                flag_type=w["flag_type"],
                ai_explanation=w["ai_explanation"],
                evidence_refs=w["evidence_refs"],
                sort_order=i,
            )
            for i, w in enumerate(WARNINGS)
        ]
        session.add_all(warning_rows)

        checklist_rows: list[TitleExamChecklistItem] = [
            TitleExamChecklistItem(
                packet_id=packet_id,
                org_id=org_id,
                item_number=item["number"],
                action=item["action"],
                priority=item["priority"],
                checked=item["checked"],
                note=item["note"],
                sort_order=i,
            )
            for i, item in enumerate(CHECKLIST_ITEMS)
        ]
        session.add_all(checklist_rows)

        # Loan-program confirmation (US-3.11). Look up the canned verdict
        # for the declared program and stamp it onto the packet row.
        # Unknown program ids (shouldn't happen — the POST validates
        # against LOAN_PROGRAM_IDS) fall through to NULLs.
        confirmation = CONFIRMATION_BY_PROGRAM.get(declared_program_id)
        if confirmation is not None:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(
                    program_confirmation_status=confirmation["status"],
                    program_confirmation_suggested_id=confirmation.get("suggested_program_id"),
                    program_confirmation_evidence=confirmation["evidence"],
                    program_confirmation_documents=list(confirmation["documents_analyzed"]),
                )
            )

        await session.commit()

    # M3: Real MISMO 3.6 extraction via Gemini Pro. Runs AFTER the
    # findings commit so `extract_packet` can read back the `EcvDocument`
    # rows it was asked to extract from. Any failure is logged and
    # swallowed so the `score` stage still completes — the MISMO / evidence
    # panels will render empty rather than blocking the dashboard.
    try:
        await extract_packet(packet_id)
    except Exception:
        log.exception("extract_packet failed for %s", packet_id)

    # M4: Real validate + score via Claude Sonnet. Reads back the docs
    # (classify output) + extractions (extract output) and grades the 58
    # industry-standard checks, persisting `EcvSection` (with computed
    # scores) + `EcvLineItem` rows. Must run after both earlier stages
    # have committed their rows. On failure (e.g. no AI keys configured)
    # we fall back to the canned ECV_SECTIONS / ECV_LINE_ITEMS data so
    # the dashboard can still display results rather than hanging on 409.
    try:
        await validate_packet(packet_id)
    except Exception:
        log.exception("validate_packet failed for %s — writing canned fallback sections", packet_id)
        await _write_fallback_ecv_sections(packet_id)


async def _write_fallback_ecv_sections(packet_id: uuid.UUID) -> None:
    """Write canned ECV sections + line items when the real validate stage fails.

    Checks first whether sections already exist (idempotent) so a hot
    reload or retry won't trip the unique constraint.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvSection.id).where(EcvSection.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        packet_row = (
            await session.execute(
                select(Packet.org_id).where(Packet.id == packet_id)
            )
        ).scalar_one_or_none()
        if packet_row is None:
            log.warning("fallback: packet %s not found", packet_id)
            return
        org_id = packet_row

        section_id_map: dict[int, uuid.UUID] = {}
        for sec in ECV_SECTIONS:
            sec_id = uuid.uuid4()
            section_id_map[sec["id"]] = sec_id
            session.add(
                EcvSection(
                    id=sec_id,
                    packet_id=packet_id,
                    org_id=org_id,
                    section_number=sec["id"],
                    name=sec["name"],
                    score=sec["score"],
                    weight=sec["weight"],
                )
            )

        for section_num, items in ECV_LINE_ITEMS.items():
            sec_id = section_id_map.get(section_num)
            if sec_id is None:
                continue
            for item in items:
                session.add(
                    EcvLineItem(
                        section_id=sec_id,
                        packet_id=packet_id,
                        org_id=org_id,
                        item_code=item["id"],
                        check_description=item["check"],
                        result_text=item["result"],
                        confidence=item["confidence"],
                    )
                )

        await session.commit()
        log.info("fallback: wrote canned ECV sections for packet %s", packet_id)
