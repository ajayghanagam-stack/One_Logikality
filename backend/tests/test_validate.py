"""Real `validate_packet` tests (M4).

Exercises `app.pipeline.validate.validate_packet` end-to-end with a fake
Claude adapter. The autouse `_stub_validate` fixture in conftest.py
replaces the reference inside `app.pipeline.ecv_stub` (the pipeline
runner) — not the function in `app.pipeline.validate` itself — so tests
that import `validate_packet` directly from `app.pipeline.validate` get
the real implementation.

The real implementation calls `get_anthropic_adapter()` at the top of
each run. We monkeypatch that factory to return a `_FakeAdapter` whose
`.complete(...)` returns canned JSON keyed by section name, so the 13
Claude calls become 13 lookups and the test stays hermetic + fast.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import EcvLineItem, EcvSection
from app.pipeline import validate as validate_mod
from app.pipeline.validate import _CHECK_DEFS, _SECTION_DEFS, validate_packet


class _FakeAdapter:
    """In-memory stand-in for `LLMAdapter`.

    `responses_by_section` is `{section_name: {check_id: (result, confidence)}}`.
    A section name missing from the map raises `RuntimeError`, which
    `validate_packet` catches and degrades to confidence=0.
    """

    def __init__(
        self,
        responses_by_section: dict[str, dict[str, tuple[str, int]]],
    ) -> None:
        self._responses = responses_by_section
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = messages[-1]["content"]
        # The user message opens with `Section: <name>\n`.
        section_name = user.split("\n", 1)[0].removeprefix("Section: ").strip()
        self.calls.append({"section": section_name, "model": model})
        mapping = self._responses.get(section_name)
        if mapping is None:
            raise RuntimeError(f"no canned response for section {section_name!r}")
        return {
            "line_items": [
                {"id": cid, "result": r, "confidence": c} for cid, (r, c) in mapping.items()
            ]
        }


def _full_pass_responses() -> dict[str, dict[str, tuple[str, int]]]:
    """Every check in every section returns a deterministic pass."""
    out: dict[str, dict[str, tuple[str, int]]] = {}
    for section_def in _SECTION_DEFS:
        out[section_def["name"]] = {
            check["id"]: (f"pass {check['id']}", 95) for check in _CHECK_DEFS[section_def["number"]]
        }
    return out


@pytest_asyncio.fixture
async def packet_id(seeded) -> AsyncIterator[uuid.UUID]:
    """Create a bare packet row for the seeded org and clean up after."""
    pid = uuid.uuid4()
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO packets "
                "(id, org_id, declared_program_id, status, created_by) "
                "VALUES (:id, :org, 'conventional', 'uploaded', :uid)"
            ),
            {"id": pid, "org": seeded["org_id"], "uid": seeded["customer_admin_id"]},
        )
        await session.commit()
    try:
        yield pid
    finally:
        async with SessionLocal() as session:
            # ecv_sections + ecv_line_items cascade from packets; an
            # explicit DELETE keeps the teardown readable.
            await session.execute(
                text("DELETE FROM ecv_line_items WHERE packet_id = :p"), {"p": pid}
            )
            await session.execute(text("DELETE FROM ecv_sections WHERE packet_id = :p"), {"p": pid})
            await session.execute(text("DELETE FROM packets WHERE id = :p"), {"p": pid})
            await session.commit()


async def _fetch_sections(packet: uuid.UUID) -> list[EcvSection]:
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(EcvSection)
                    .where(EcvSection.packet_id == packet)
                    .order_by(EcvSection.section_number)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


async def _fetch_line_items(packet: uuid.UUID) -> list[EcvLineItem]:
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(EcvLineItem)
                    .where(EcvLineItem.packet_id == packet)
                    .order_by(EcvLineItem.item_code)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


# --- happy path -------------------------------------------------------


async def test_validate_writes_all_sections_and_line_items(
    packet_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _FakeAdapter(_full_pass_responses())
    monkeypatch.setattr(validate_mod, "get_anthropic_adapter", lambda: adapter)

    await validate_packet(packet_id)

    expected_items = sum(len(checks) for checks in _CHECK_DEFS.values())

    sections = await _fetch_sections(packet_id)
    assert len(sections) == len(_SECTION_DEFS)
    assert [s.section_number for s in sections] == [d["number"] for d in _SECTION_DEFS]
    # Every canned check returned confidence=95, so each section rolls
    # up to 95 (mean of identical values).
    assert all(int(s.score) == 95 for s in sections)
    # Weights should pass through from the static `_SECTION_DEFS`.
    weights_by_num = {s.section_number: s.weight for s in sections}
    for section_def in _SECTION_DEFS:
        assert weights_by_num[section_def["number"]] == section_def["weight"]

    items = await _fetch_line_items(packet_id)
    assert len(items) == expected_items
    # Every item_code is unique and binds to a real section.
    section_ids = {s.id for s in sections}
    assert all(item.section_id in section_ids for item in items)
    assert all(item.confidence == 95 for item in items)

    # One Claude call per section — no batching, no repeats.
    assert len(adapter.calls) == len(_SECTION_DEFS)
    assert {c["section"] for c in adapter.calls} == {s["name"] for s in _SECTION_DEFS}


async def test_validate_clamps_out_of_range_confidence(
    packet_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that returns confidence>100 or <0 should be clamped to [0,100]."""
    responses = _full_pass_responses()
    # Poison section 1's first check with an out-of-range value.
    responses["Document completeness"]["1.1"] = ("over the top", 250)
    responses["Document completeness"]["1.2"] = ("way under", -50)
    adapter = _FakeAdapter(responses)
    monkeypatch.setattr(validate_mod, "get_anthropic_adapter", lambda: adapter)

    await validate_packet(packet_id)

    items = {i.item_code: i for i in await _fetch_line_items(packet_id)}
    assert items["1.1"].confidence == 100
    assert items["1.2"].confidence == 0


# --- section failure isolation ---------------------------------------


async def test_validate_failing_section_marked_zero(
    packet_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Claude raises for one section, that section zeroes out but the
    other 12 still land."""
    responses = _full_pass_responses()
    # Drop one section's canned map — `_FakeAdapter` will raise when it
    # sees this section name.
    del responses["Appraisal"]
    adapter = _FakeAdapter(responses)
    monkeypatch.setattr(validate_mod, "get_anthropic_adapter", lambda: adapter)

    await validate_packet(packet_id)

    sections_by_number = {s.section_number: s for s in await _fetch_sections(packet_id)}
    # Section 6 == Appraisal per `_SECTION_DEFS`.
    assert int(sections_by_number[6].score) == 0
    # Other sections still roll up to 95.
    for num, section in sections_by_number.items():
        if num == 6:
            continue
        assert int(section.score) == 95

    appraisal_items = [
        i for i in await _fetch_line_items(packet_id) if i.item_code.startswith("6.")
    ]
    # Each item under Appraisal should carry the fallback string + 0.
    assert appraisal_items, "appraisal line items should still be written"
    assert all(i.confidence == 0 for i in appraisal_items)
    assert all(i.result_text == "validation failed" for i in appraisal_items)


# --- idempotency ------------------------------------------------------


async def test_validate_short_circuits_when_sections_already_exist(
    packet_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second call against a packet that already has sections is a no-op.

    The gate exists so a pipeline replay (hot reload, retried Temporal
    activity) doesn't trip the `(packet_id, section_number)` unique
    constraint.
    """
    adapter = _FakeAdapter(_full_pass_responses())
    monkeypatch.setattr(validate_mod, "get_anthropic_adapter", lambda: adapter)

    await validate_packet(packet_id)
    first_calls = len(adapter.calls)
    assert first_calls == len(_SECTION_DEFS)

    await validate_packet(packet_id)
    # Short-circuit: no additional Claude calls on the replay.
    assert len(adapter.calls) == first_calls

    # And we still have the same number of rows — no duplicates.
    expected_items = sum(len(checks) for checks in _CHECK_DEFS.values())
    assert len(await _fetch_sections(packet_id)) == len(_SECTION_DEFS)
    assert len(await _fetch_line_items(packet_id)) == expected_items


# --- packet vanished --------------------------------------------------


async def test_validate_no_op_for_unknown_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validating a packet that doesn't exist is a logged warning, not a crash."""
    adapter = _FakeAdapter(_full_pass_responses())
    monkeypatch.setattr(validate_mod, "get_anthropic_adapter", lambda: adapter)

    # Should not raise; should not make any Claude calls either.
    await validate_packet(uuid.uuid4())
    assert adapter.calls == []
