"""ECV report rendering — PDF (US-8.1) and MISMO 3.6 XML (US-8.2).

Pure rendering — no DB access, no auth, no FastAPI types. Routers hand
us the same objects `GET /api/packets/{id}/ecv` returns and we emit a
self-contained byte string. Keeping this separate from the router lets
tests exercise rendering without spinning up a full request.

PDF layout mirrors the ECV dashboard the user just looked at: hero
block with packet metadata + overall score, three tables (documents,
section scores, items-to-review), optional review-decision block. Brand
palette is pulled from CLAUDE.md — teal `#01BAED` primary, amber
`#FCAE1E` for emphasis, charcoal for text, red for critical findings.

MISMO 3.6 output is the MESSAGE envelope wrapping a DEAL_SET with the
declared loan program, the full document inventory (classified MISMO
types + confidence), and a Logikality-namespaced EXTENSION carrying the
ECV section scores and flagged line items. Schema fidelity is
best-effort: the envelope is well-formed MISMO, but per-field extraction
breadth is limited by what the stub populates today.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import EcvDocument, EcvLineItem, EcvSection, Packet
from app.rules import LOAN_PROGRAMS

# Brand tokens — keep in sync with frontend/lib/brand.ts and
# docs/Logikality_Brand_Guidelines.pdf. If the PDF and the dashboard
# start drifting, this is the place to re-anchor.
_TEAL = colors.HexColor("#01BAED")
_AMBER = colors.HexColor("#FCAE1E")
_AMBER_DARK = colors.HexColor("#D4930F")
_CHARCOAL = colors.HexColor("#1A1A2E")
_MUTED_FG = colors.HexColor("#53585F")
_BORDER = colors.HexColor("#E5E2D8")
_MUTED_BG = colors.HexColor("#F6F3EC")
_DESTRUCTIVE = colors.HexColor("#B91C1C")
_DESTRUCTIVE_BG = colors.HexColor("#FEE2E2")
_SUCCESS = colors.HexColor("#15803D")
_SUCCESS_BG = colors.HexColor("#DCFCE7")

# Severity boundaries match the router constants. Duplicated here
# intentionally — the renderer is a downstream consumer and shouldn't
# reach back into the router module.
_CRITICAL_THRESHOLD = 50
_CONFIDENCE_THRESHOLD = 85
_AUTO_APPROVE_THRESHOLD = 90


def _severity(confidence: int) -> str:
    if confidence < _CRITICAL_THRESHOLD:
        return "critical"
    if confidence < _CONFIDENCE_THRESHOLD:
        return "review"
    return "pass"


def _score_status(score: float) -> tuple[str, colors.Color]:
    if score >= _AUTO_APPROVE_THRESHOLD:
        return "PASS", _SUCCESS
    if score >= _CONFIDENCE_THRESHOLD:
        return "REVIEW", _AMBER_DARK
    return "CRITICAL", _DESTRUCTIVE


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%b %d, %Y · %H:%M UTC")


def render_ecv_pdf(
    *,
    packet: Packet,
    sections: Iterable[EcvSection],
    line_items: Iterable[EcvLineItem],
    documents: Iterable[EcvDocument],
    overrider_name: str | None,
    reviewer_name: str | None,
) -> bytes:
    """Render the ECV validation report as a PDF byte string.

    Caller owns the DB session; this function only reads attributes off
    the passed-in ORM objects. The generated file is portrait LETTER
    sized, suitable for printing or e-mailing to underwriters.
    """
    sections_list = list(sections)
    line_items_list = list(line_items)
    documents_list = list(documents)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"ECV Validation Report — Packet {str(packet.id)[:8]}",
        author="Logikality",
    )

    story: list = []
    story.extend(_hero_block(packet, sections_list, line_items_list, documents_list))
    story.append(Spacer(1, 14))
    story.extend(_review_block(packet, reviewer_name, overrider_name))
    story.extend(_documents_block(documents_list))
    story.extend(_sections_block(sections_list))
    story.extend(_items_to_review_block(sections_list, line_items_list))
    story.append(Spacer(1, 18))
    story.append(_footer_paragraph())

    doc.build(story)
    return buffer.getvalue()


# ---- block builders --------------------------------------------------

_STYLES = getSampleStyleSheet()

_KICKER = ParagraphStyle(
    "Kicker",
    parent=_STYLES["Normal"],
    fontName="Helvetica-Bold",
    fontSize=8,
    textColor=_AMBER_DARK,
    spaceAfter=4,
    leading=10,
)
_TITLE = ParagraphStyle(
    "Title",
    parent=_STYLES["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=20,
    textColor=_CHARCOAL,
    spaceAfter=10,
    leading=24,
)
_H2 = ParagraphStyle(
    "H2",
    parent=_STYLES["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=13,
    textColor=_CHARCOAL,
    spaceBefore=14,
    spaceAfter=8,
    leading=16,
)
_BODY = ParagraphStyle(
    "Body",
    parent=_STYLES["Normal"],
    fontName="Helvetica",
    fontSize=10,
    textColor=_CHARCOAL,
    leading=14,
)
_MUTED = ParagraphStyle(
    "Muted",
    parent=_BODY,
    textColor=_MUTED_FG,
    fontSize=9,
    leading=12,
)
_FOOTER = ParagraphStyle(
    "Footer",
    parent=_BODY,
    textColor=_MUTED_FG,
    fontSize=8,
    leading=10,
    alignment=1,  # center
)


def _hero_block(
    packet: Packet,
    sections: list[EcvSection],
    line_items: list[EcvLineItem],
    documents: list[EcvDocument],
) -> list:
    total_weight = sum(s.weight for s in sections)
    overall = (
        sum(float(s.score) * s.weight for s in sections) / total_weight if total_weight > 0 else 0.0
    )
    overall = round(overall, 1)
    status_label, status_color = _score_status(overall)

    declared = LOAN_PROGRAMS.get(packet.declared_program_id)
    effective_id = packet.program_overridden_to or packet.declared_program_id
    effective = LOAN_PROGRAMS.get(effective_id)
    declared_label = declared["label"] if declared else packet.declared_program_id
    effective_label = effective["label"] if effective else effective_id

    short_id = str(packet.id)[:8]
    missing_docs = sum(1 for d in documents if d.status == "missing")
    critical = sum(1 for i in line_items if i.confidence < _CRITICAL_THRESHOLD)
    review = sum(
        1 for i in line_items if _CRITICAL_THRESHOLD <= i.confidence < _CONFIDENCE_THRESHOLD
    )

    # Summary table: metadata on the left, score gauge on the right.
    meta_rows = [
        ["Program", effective_label],
        ["Status", packet.status.replace("_", " ").title()],
        ["Uploaded", _fmt_ts(packet.created_at)],
    ]
    if packet.program_overridden_to and declared:
        meta_rows.append(["Declared", declared_label])

    meta_tbl = Table(meta_rows, colWidths=[1.1 * inch, 3.0 * inch])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED_FG),
                ("TEXTCOLOR", (1, 0), (1, -1), _CHARCOAL),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    score_banner = (
        "Auto-approval eligible"
        if overall >= _AUTO_APPROVE_THRESHOLD
        else f"Score below {_AUTO_APPROVE_THRESHOLD}% — needs manual review"
    )
    score_tbl = Table(
        [
            [Paragraph(f"<b>{overall}%</b>", _title_score_style())],
            [Paragraph(status_label, _status_pill_style(status_color))],
            [Paragraph(score_banner, _MUTED)],
        ],
        colWidths=[2.5 * inch],
    )
    score_tbl.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BACKGROUND", (0, 0), (-1, -1), _MUTED_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    outer = Table([[meta_tbl, score_tbl]], colWidths=[4.3 * inch, 2.9 * inch])
    outer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    kpi_tbl = Table(
        [
            [
                _kpi_cell(
                    "Documents",
                    f"{len(documents) - missing_docs}/{len(documents)}",
                    f"{missing_docs} missing" if missing_docs else "All present",
                    _DESTRUCTIVE if missing_docs else _SUCCESS,
                ),
                _kpi_cell(
                    "Items to review",
                    str(critical + review),
                    f"{critical} critical · {review} amber",
                    _DESTRUCTIVE,
                ),
                _kpi_cell(
                    "Total checks",
                    str(len(line_items)),
                    f"Across {len(sections)} sections",
                    _MUTED_FG,
                ),
            ]
        ],
        colWidths=[2.4 * inch, 2.4 * inch, 2.4 * inch],
    )
    kpi_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    return [
        Paragraph("ECV VALIDATION REPORT", _KICKER),
        Paragraph(f"Packet {short_id}", _TITLE),
        outer,
        Spacer(1, 10),
        kpi_tbl,
    ]


def _title_score_style() -> ParagraphStyle:
    return ParagraphStyle(
        "ScoreBig",
        parent=_BODY,
        fontName="Helvetica-Bold",
        fontSize=30,
        textColor=_CHARCOAL,
        alignment=1,
        leading=32,
    )


def _status_pill_style(color: colors.Color) -> ParagraphStyle:
    return ParagraphStyle(
        "StatusPill",
        parent=_BODY,
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=color,
        alignment=1,
        leading=12,
    )


def _kpi_cell(label: str, value: str, trend: str, trend_color: colors.Color) -> Table:
    t = Table(
        [
            [Paragraph(label.upper(), _MUTED)],
            [
                Paragraph(
                    f"<b>{value}</b>",
                    ParagraphStyle(
                        "KpiVal",
                        parent=_BODY,
                        fontName="Helvetica-Bold",
                        fontSize=18,
                        textColor=_CHARCOAL,
                        leading=22,
                    ),
                )
            ],
            [
                Paragraph(
                    trend,
                    ParagraphStyle(
                        "KpiTrend",
                        parent=_MUTED,
                        textColor=trend_color,
                    ),
                )
            ],
        ],
        colWidths=[2.3 * inch],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def _review_block(
    packet: Packet,
    reviewer_name: str | None,
    overrider_name: str | None,
) -> list:
    out: list = []
    if packet.review_state is not None:
        state_labels = {
            "approved": ("APPROVED", _SUCCESS, _SUCCESS_BG),
            "rejected": ("REJECTED", _DESTRUCTIVE, _DESTRUCTIVE_BG),
            "pending_manual_review": ("IN MANUAL REVIEW", _AMBER_DARK, _MUTED_BG),
        }
        label, fg, bg = state_labels.get(
            packet.review_state, (packet.review_state.upper(), _CHARCOAL, _MUTED_BG)
        )
        ts = _fmt_ts(packet.review_transitioned_at)
        rows = [
            [Paragraph(f"<b>{label}</b>", _status_pill_style(fg))],
            [
                Paragraph(
                    f"by <b>{reviewer_name or 'unknown'}</b> on {ts}",
                    _BODY,
                )
            ],
        ]
        if packet.review_notes:
            rows.append([Paragraph(f"Notes: {packet.review_notes}", _MUTED)])
        tbl = Table(rows, colWidths=[7.2 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), bg),
                    ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        out.append(KeepTogether([Paragraph("Review decision", _H2), tbl]))

    if packet.program_overridden_to and packet.program_override_reason:
        to_label = (
            LOAN_PROGRAMS[packet.program_overridden_to]["label"]
            if packet.program_overridden_to in LOAN_PROGRAMS
            else packet.program_overridden_to
        )
        out.append(
            Paragraph(
                f"<b>Program override:</b> changed to <b>{to_label}</b> by "
                f"{overrider_name or 'unknown'} on {_fmt_ts(packet.program_overridden_at)} — "
                f"{packet.program_override_reason}",
                _MUTED,
            )
        )
    return out


def _documents_block(documents: list[EcvDocument]) -> list:
    if not documents:
        return []
    header = ["#", "Document", "MISMO type", "Pages", "Confidence", "Status"]
    rows: list[list] = [header]
    for d in documents:
        status_text = "FOUND" if d.status == "found" else "MISSING"
        rows.append(
            [
                str(d.doc_number),
                Paragraph(d.name, _BODY),
                Paragraph(d.mismo_type, _MUTED),
                d.pages_display or "—",
                f"{d.confidence}%" if d.status == "found" else "—",
                status_text,
            ]
        )
    tbl = Table(
        rows,
        colWidths=[
            0.3 * inch,
            2.5 * inch,
            1.9 * inch,
            0.7 * inch,
            0.9 * inch,
            0.9 * inch,
        ],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _MUTED_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), _CHARCOAL),
        ("TEXTCOLOR", (0, 1), (-1, -1), _CHARCOAL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
        ("GRID", (0, 1), (-1, -1), 0.25, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, d in enumerate(documents, start=1):
        if d.status == "missing":
            style.append(("TEXTCOLOR", (5, i), (5, i), _DESTRUCTIVE))
            style.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return [Paragraph("Documents", _H2), tbl]


def _sections_block(sections: list[EcvSection]) -> list:
    if not sections:
        return []
    header = ["#", "Section", "Weight", "Score"]
    rows: list[list] = [header]
    for s in sections:
        rows.append(
            [
                str(s.section_number),
                Paragraph(s.name, _BODY),
                f"{s.weight}%",
                f"{float(s.score):.0f}%",
            ]
        )
    tbl = Table(
        rows,
        colWidths=[0.4 * inch, 5.0 * inch, 0.9 * inch, 0.9 * inch],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _MUTED_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), _CHARCOAL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
        ("GRID", (0, 1), (-1, -1), 0.25, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, s in enumerate(sections, start=1):
        _, color = _score_status(float(s.score))
        style.append(("TEXTCOLOR", (3, i), (3, i), color))
        style.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return [Paragraph("Section scores", _H2), tbl]


def _items_to_review_block(
    sections: list[EcvSection],
    line_items: list[EcvLineItem],
) -> list:
    sections_by_id = {s.id: s for s in sections}
    flagged = [i for i in line_items if i.confidence < _CONFIDENCE_THRESHOLD]
    flagged.sort(key=lambda i: (i.confidence, i.item_code))
    if not flagged:
        return [
            Paragraph("Items to review", _H2),
            Paragraph("No items fell below the 85% confidence threshold.", _MUTED),
        ]
    header = ["Code", "Section", "Check", "Confidence", "Severity"]
    rows: list[list] = [header]
    for item in flagged:
        sec = sections_by_id.get(item.section_id)
        sev = _severity(item.confidence)
        rows.append(
            [
                item.item_code,
                Paragraph(sec.name if sec else "—", _MUTED),
                Paragraph(item.check_description, _BODY),
                f"{item.confidence}%",
                sev.upper(),
            ]
        )
    tbl = Table(
        rows,
        colWidths=[
            0.7 * inch,
            1.4 * inch,
            3.2 * inch,
            0.9 * inch,
            1.0 * inch,
        ],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _MUTED_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), _CHARCOAL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
        ("GRID", (0, 1), (-1, -1), 0.25, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, item in enumerate(flagged, start=1):
        color = _DESTRUCTIVE if item.confidence < _CRITICAL_THRESHOLD else _AMBER_DARK
        style.append(("TEXTCOLOR", (4, i), (4, i), color))
        style.append(("FONTNAME", (4, i), (4, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return [Paragraph("Items to review", _H2), tbl]


def _footer_paragraph() -> Paragraph:
    now = datetime.now(UTC).strftime("%b %d, %Y · %H:%M UTC")
    return Paragraph(
        f"Generated by Logikality on {now}. Transformation first, AI second.",
        _FOOTER,
    )


# ---- MISMO 3.6 XML export (US-8.2) -----------------------------------

# MISMO 3.6 namespaces. The schema URI is the canonical MISMO residential
# 2009 namespace; the Logikality namespace carries our ECV-specific
# EXTENSION payload that doesn't map to a native MISMO construct.
_MISMO_NS = "http://www.mismo.org/residential/2009/schemas"
_LOGIKALITY_NS = "https://logikality.com/schemas/ecv/1"

# Declared loan program → MISMO MortgageType enum. The MISMO enum is a
# closed set; "Jumbo" isn't one of its values, so we classify jumbo as
# Conventional (the rules engine already knows it's non-conforming).
_PROGRAM_TO_MORTGAGE_TYPE = {
    "conventional": "Conventional",
    "jumbo": "Conventional",
    "fha": "FHA",
    "va": "VA",
    "usda": "USDARural",
}


def render_ecv_mismo_xml(
    *,
    packet: Packet,
    sections: Iterable[EcvSection],
    line_items: Iterable[EcvLineItem],
    documents: Iterable[EcvDocument],
    reviewer_name: str | None,
) -> bytes:
    """Render the ECV payload as a well-formed MISMO 3.6 XML byte string.

    Structure:
      MESSAGE (MISMO 3.6)
        ABOUT_VERSIONS — generator metadata
        DEAL_SETS/DEAL_SET/DEALS/DEAL
          LOANS/LOAN — declared program, packet identifier
          DOCUMENT_SETS/DOCUMENT_SET/DOCUMENTS/DOCUMENT[] — ECV inventory
          EXTENSION — Logikality-namespaced ECV findings block

    Caller owns the DB session; this function only reads attributes off
    the passed-in ORM objects. Output is UTF-8 with an XML declaration,
    suitable for drop-in ingestion by downstream MISMO tooling.
    """
    from xml.etree.ElementTree import Element, SubElement, tostring

    sections_list = list(sections)
    line_items_list = list(line_items)
    documents_list = list(documents)

    # Register the Logikality namespace so ElementTree emits the prefix
    # we want (`logikality:`) rather than `ns0:` on the EXTENSION block.
    import xml.etree.ElementTree as ET

    ET.register_namespace("", _MISMO_NS)
    ET.register_namespace("logikality", _LOGIKALITY_NS)

    message = Element(
        f"{{{_MISMO_NS}}}MESSAGE",
        {"MISMOReferenceModelIdentifier": "3.6.0"},
    )

    # -- ABOUT_VERSIONS ----------------------------------------------------
    avs = SubElement(message, f"{{{_MISMO_NS}}}ABOUT_VERSIONS")
    av = SubElement(avs, f"{{{_MISMO_NS}}}ABOUT_VERSION")
    SubElement(av, f"{{{_MISMO_NS}}}AboutVersionIdentifier").text = "Logikality-ECV-1.0"
    SubElement(av, f"{{{_MISMO_NS}}}CreatedDatetime").text = datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    SubElement(av, f"{{{_MISMO_NS}}}DataVersionIdentifier").text = "3.6.0"
    SubElement(av, f"{{{_MISMO_NS}}}DataVersionName").text = "MISMO 3.6"

    # -- DEAL_SETS / DEAL_SET / DEAL --------------------------------------
    deal_sets = SubElement(message, f"{{{_MISMO_NS}}}DEAL_SETS")
    deal_set = SubElement(deal_sets, f"{{{_MISMO_NS}}}DEAL_SET")
    deals = SubElement(deal_set, f"{{{_MISMO_NS}}}DEALS")
    deal = SubElement(deals, f"{{{_MISMO_NS}}}DEAL")

    # LOANS/LOAN
    loans = SubElement(deal, f"{{{_MISMO_NS}}}LOANS")
    loan = SubElement(loans, f"{{{_MISMO_NS}}}LOAN", {"LoanRoleType": "SubjectLoan"})
    loan_ids = SubElement(loan, f"{{{_MISMO_NS}}}LOAN_IDENTIFIERS")
    loan_id = SubElement(loan_ids, f"{{{_MISMO_NS}}}LOAN_IDENTIFIER")
    SubElement(loan_id, f"{{{_MISMO_NS}}}LoanIdentifier").text = str(packet.id)
    SubElement(loan_id, f"{{{_MISMO_NS}}}LoanIdentifierType").text = "LenderLoan"

    terms = SubElement(loan, f"{{{_MISMO_NS}}}TERMS_OF_LOAN")
    mortgage_type = _PROGRAM_TO_MORTGAGE_TYPE.get(
        packet.program_overridden_to or packet.declared_program_id, "Conventional"
    )
    SubElement(terms, f"{{{_MISMO_NS}}}MortgageType").text = mortgage_type
    if (packet.program_overridden_to or packet.declared_program_id) == "jumbo":
        # MISMO 3.6 doesn't model "jumbo" natively; surface it as the
        # amount classification so downstream consumers still see it.
        SubElement(terms, f"{{{_MISMO_NS}}}LoanAmountClassificationType").text = "Jumbo"

    # DOCUMENT_SETS/DOCUMENT_SET/DOCUMENTS — every classified ECV doc
    doc_sets = SubElement(deal, f"{{{_MISMO_NS}}}DOCUMENT_SETS")
    doc_set = SubElement(doc_sets, f"{{{_MISMO_NS}}}DOCUMENT_SET")
    docs_el = SubElement(doc_set, f"{{{_MISMO_NS}}}DOCUMENTS")
    for d in documents_list:
        doc_el = SubElement(
            docs_el,
            f"{{{_MISMO_NS}}}DOCUMENT",
            {"SequenceNumber": str(d.doc_number)},
        )
        classification = SubElement(doc_el, f"{{{_MISMO_NS}}}DOCUMENT_CLASSIFICATION")
        classes = SubElement(classification, f"{{{_MISMO_NS}}}DOCUMENT_CLASSES")
        cls = SubElement(classes, f"{{{_MISMO_NS}}}DOCUMENT_CLASS")
        SubElement(cls, f"{{{_MISMO_NS}}}DocumentClassificationMISMOType").text = d.mismo_type
        SubElement(cls, f"{{{_MISMO_NS}}}DocumentSignatureRequiredIndicator").text = "false"
        detail = SubElement(classification, f"{{{_MISMO_NS}}}DOCUMENT_CLASS_DETAIL")
        SubElement(detail, f"{{{_MISMO_NS}}}DocumentName").text = d.name
        if d.status == "found":
            SubElement(
                detail,
                f"{{{_MISMO_NS}}}DocumentClassificationConfidencePercent",
            ).text = str(d.confidence)
        SubElement(detail, f"{{{_MISMO_NS}}}DocumentStatusType").text = (
            "Processed" if d.status == "found" else "NotReceived"
        )
        if d.pages_display:
            pages = SubElement(doc_el, f"{{{_MISMO_NS}}}DOCUMENT_DETAIL")
            SubElement(pages, f"{{{_MISMO_NS}}}DocumentPageCountDescription").text = d.pages_display

    # -- EXTENSION (Logikality ECV findings) ------------------------------
    # EXTENSION is a standard MISMO slot for vendor-specific payloads
    # that don't fit the base schema. We attach a Logikality-namespaced
    # ECV_VALIDATION block with the overall score, per-section rollup,
    # and items-to-review — the same data the dashboard shows.
    extension = SubElement(deal, f"{{{_MISMO_NS}}}EXTENSION")
    other = SubElement(extension, f"{{{_MISMO_NS}}}OTHER")
    ecv_ext = SubElement(other, f"{{{_LOGIKALITY_NS}}}ECV_VALIDATION")

    total_weight = sum(s.weight for s in sections_list)
    overall = (
        sum(float(s.score) * s.weight for s in sections_list) / total_weight
        if total_weight > 0
        else 0.0
    )
    SubElement(ecv_ext, f"{{{_LOGIKALITY_NS}}}OverallScorePercent").text = f"{overall:.1f}"
    SubElement(ecv_ext, f"{{{_LOGIKALITY_NS}}}AutoApproveThresholdPercent").text = str(
        _AUTO_APPROVE_THRESHOLD
    )
    SubElement(
        ecv_ext, f"{{{_LOGIKALITY_NS}}}DeclaredLoanProgramIdentifier"
    ).text = packet.declared_program_id
    if packet.program_overridden_to:
        SubElement(
            ecv_ext, f"{{{_LOGIKALITY_NS}}}EffectiveLoanProgramIdentifier"
        ).text = packet.program_overridden_to

    sections_el = SubElement(ecv_ext, f"{{{_LOGIKALITY_NS}}}Sections")
    for s in sections_list:
        sec_el = SubElement(
            sections_el,
            f"{{{_LOGIKALITY_NS}}}Section",
            {"Number": str(s.section_number)},
        )
        SubElement(sec_el, f"{{{_LOGIKALITY_NS}}}Name").text = s.name
        SubElement(sec_el, f"{{{_LOGIKALITY_NS}}}WeightPercent").text = str(s.weight)
        SubElement(sec_el, f"{{{_LOGIKALITY_NS}}}ScorePercent").text = f"{float(s.score):.1f}"

    flagged = [i for i in line_items_list if i.confidence < _CONFIDENCE_THRESHOLD]
    items_el = SubElement(ecv_ext, f"{{{_LOGIKALITY_NS}}}ItemsToReview")
    for item in flagged:
        item_el = SubElement(
            items_el,
            f"{{{_LOGIKALITY_NS}}}Item",
            {"Code": item.item_code},
        )
        SubElement(item_el, f"{{{_LOGIKALITY_NS}}}Check").text = item.check_description
        SubElement(item_el, f"{{{_LOGIKALITY_NS}}}Result").text = item.result_text
        SubElement(item_el, f"{{{_LOGIKALITY_NS}}}ConfidencePercent").text = str(item.confidence)
        SubElement(item_el, f"{{{_LOGIKALITY_NS}}}Severity").text = _severity(item.confidence)

    # Review decision — when an underwriter has acted on the packet.
    if packet.review_state is not None and packet.review_transitioned_at is not None:
        review_el = SubElement(ecv_ext, f"{{{_LOGIKALITY_NS}}}ReviewDecision")
        SubElement(review_el, f"{{{_LOGIKALITY_NS}}}State").text = packet.review_state
        SubElement(
            review_el, f"{{{_LOGIKALITY_NS}}}TransitionedAt"
        ).text = packet.review_transitioned_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if reviewer_name:
            SubElement(review_el, f"{{{_LOGIKALITY_NS}}}TransitionedByName").text = reviewer_name
        if packet.review_notes:
            SubElement(review_el, f"{{{_LOGIKALITY_NS}}}Notes").text = packet.review_notes

    # ElementTree.tostring with xml_declaration=True emits the <?xml ... ?>
    # prolog and encodes as UTF-8 — exactly what browsers + MISMO
    # tooling expect. No pretty-print to keep the wire format compact;
    # consumers who want indentation can reformat client-side.
    return tostring(message, encoding="utf-8", xml_declaration=True)
