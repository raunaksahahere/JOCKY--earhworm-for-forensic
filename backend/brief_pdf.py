"""
Review brief and routine activity PDFs.

Two documents that exist so the main investigator report does not have to be
either of them. A brief is one or two pages about one subject, for attaching to
a case file or handing to someone. The routine report is everything the machine
accounted for, grouped, so it can be put on the record without being read.

Both share the main report's font handling, because a forensic document that
renders a path as boxes has failed at the one job it had.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.storage import now
from backend.versions import versions

_LOCK = threading.Lock()
FONT_ROOT = Path(__file__).resolve().parent.parent / "assets" / "fonts"

MAX_BODY_LINES = 14
MAX_GROUPS = 120
MAX_DETAIL_ROWS = 40

ROUTINE_DISCLAIMER = (
    "This report describes activity that did not produce a concern signal in the collected "
    "evidence. It is not a guarantee of safety. Recognition states what a file is, on the evidence "
    "of package metadata and installation layout; it does not establish that the file is harmless, "
    "and it does not establish that the bytes on disk are still the ones a package installed.")


def _styles():
    """Register the fonts once and return the styles both documents use."""
    for name, filename in (("Jocky", "NotoSans-Regular.ttf"),
                           ("Devanagari", "NotoSansDevanagari-Regular.ttf"),
                           ("Bengali", "NotoSansBengali-Regular.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(
                TTFont(name, str(FONT_ROOT / filename), shapable=name != "Jocky"))

    body = ParagraphStyle("Body", fontName="Jocky", fontSize=9, leading=13, spaceAfter=5,
                          splitLongWords=True, shaping=True)
    return {
        "body": body,
        "title": ParagraphStyle("Title", parent=body, fontSize=20, leading=25, spaceAfter=2,
                                textColor=colors.HexColor("#123f53")),
        "heading": ParagraphStyle("Heading", parent=body, fontSize=11, leading=15, spaceBefore=10,
                                  spaceAfter=3, textColor=colors.HexColor("#123f53"),
                                  keepWithNext=True),
        "label": ParagraphStyle("Label", parent=body, fontSize=7.5, leading=10, spaceAfter=0,
                                textColor=colors.HexColor("#5a6b76"), keepWithNext=True),
        "mono": ParagraphStyle("Mono", parent=body, fontSize=8, leading=11, leftIndent=9,
                               spaceAfter=1, textColor=colors.HexColor("#0b2b3a")),
        "quiet": ParagraphStyle("Quiet", parent=body, fontSize=7.5, leading=10,
                                textColor=colors.HexColor("#5a6b76")),
    }


def _markup(value):
    """Per-character font selection, so non-Latin text renders rather than boxing."""
    fragments, run, current = [], "", None
    for char in str(value):
        code = ord(char)
        font = ("Devanagari" if 0x900 <= code <= 0x97f
                else "Bengali" if 0x980 <= code <= 0x9ff else "Jocky")
        if code not in pdfmetrics.getFont(font).face.charToGlyph and char not in "\n\t":
            char = f"[U+{code:04X}]"
        if font != current and run:
            fragments.append(f'<font name="{current}">{escape(run)}</font>')
            run = ""
        current, run = font, run + char
    if run:
        fragments.append(f'<font name="{current}">{escape(run)}</font>')
    return "".join(fragments).replace("\n", "<br/>")


def _kv_table(rows, styles):
    data = [[Paragraph(_markup(label), styles["label"]),
             Paragraph(_markup(value if value not in (None, "") else "not recorded"),
                       styles["body"])]
            for label, value in rows]
    table = Table(data, colWidths=[95, 400])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dfe6ea")),
    ]))
    return table


def render_brief_pdf(brief: dict) -> bytes:
    """One subject, one or two pages, every statement carrying its evidence."""
    with _LOCK:
        styles = _styles()
        buffer = io.BytesIO()
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=40, bottomMargin=40,
            title=f"JOCKY review brief {brief['subject']['id']}", author="JOCKY")
        story = []

        def p(value, style="body"):
            story.append(Paragraph(_markup(value), styles[style]))

        subject = brief["subject"]
        p("JOCKY", "title")
        p("REVIEW BRIEF", "heading")
        p(f"{subject['type'].replace('_', ' ').title()} {subject['id']}", "heading")
        story.append(_kv_table([
            ("Subject", subject.get("label")),
            ("Classification", brief.get("classification")),
            ("Presentation", brief.get("presentation")),
            ("Priority", brief.get("priority")),
            ("Execution", f"{brief['execution']['state']} — {brief['execution']['detail']}"),
            ("Recognition", f"{brief['recognition']['state']} — {brief['recognition']['detail']}"),
            ("Investigation", brief.get("investigation_id")),
            ("Case", brief.get("case_id") or "not attached to a case"),
            ("Generated", now()),
        ], styles))
        story.append(Spacer(1, 8))

        p("Summary", "heading")
        p(brief.get("summary") or "No summary could be assembled from the collected evidence.")

        p("Why this was surfaced", "heading")
        p(brief.get("why_surfaced") or "Not stated.")

        for section in brief.get("sections", []):
            lines = section.get("body") or []
            if not lines:
                continue
            p(section["title"], "heading")
            for line in lines[:MAX_BODY_LINES]:
                p(line, "mono")
            if len(lines) > MAX_BODY_LINES:
                p(f"... and {len(lines) - MAX_BODY_LINES} more; see the evidence package.", "quiet")

        p("What is known", "heading")
        for line in brief.get("known") or ["Nothing beyond the above."]:
            if line:
                p(f"— {line}")

        p("What is unknown", "heading")
        for line in brief.get("unknown") or ["Nothing further is stated as unknown."]:
            if line:
                p(f"— {line}")

        if brief.get("collection_limitations"):
            p("Collection limitations", "heading")
            for line in brief["collection_limitations"]:
                p(f"— {line}", "quiet")

        p("Suggested investigator review", "heading")
        for line in brief.get("suggested_review") or []:
            if line:
                p(f"— {line}")

        p("Evidence cited", "heading")
        p(", ".join(brief.get("evidence_ids") or []) or "No evidence identifier was cited.", "mono")

        story.append(Spacer(1, 10))
        p(brief.get("disclaimer", ""), "quiet")
        applied = brief.get("versions") or versions()
        p(f"Produced by JOCKY {applied.get('application')} "
          f"(report schema {applied.get('report_schema')}, database schema "
          f"{applied.get('database_schema')}). Brief format v{brief.get('brief_version')}.", "quiet")

        document.build(story)
        return buffer.getvalue()


def render_routine_pdf(report: dict, routine: dict, *, detailed=False) -> bytes:
    """Everything the machine accounted for, grouped rather than listed.

    Printing eleven hundred identical version checks is not a record, it is a
    way of making sure nobody reads the record. Detail is available on request.
    """
    with _LOCK:
        styles = _styles()
        buffer = io.BytesIO()
        case = report.get("investigation", {}) or {}
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=40, bottomMargin=40,
            title=f"JOCKY routine activity {report.get('investigation_id')}", author="JOCKY")
        story = []

        def p(value, style="body"):
            story.append(Paragraph(_markup(value), styles[style]))

        p("JOCKY", "title")
        p("ROUTINE / RECOGNIZED ACTIVITY", "heading")
        story.append(_kv_table([
            ("Investigation", report.get("investigation_id")),
            ("Case", case.get("title")),
            ("Status", report.get("status")),
            ("Collection window", str(report.get("collection_window") or "not recorded")),
            ("Generated", now()),
        ], styles))
        story.append(Spacer(1, 6))
        p(ROUTINE_DISCLAIMER, "quiet")

        totals = routine.get("totals", {})
        p("What this covers", "heading")
        p(f"{totals.get('records', 0)} record(s) across {totals.get('activities', 0)} distinct "
          f"activities were presented as routine or recognized, out of "
          f"{totals.get('all_activities', 0)} in the collection. "
          f"{totals.get('excluded', 0)} activity(ies) were not, and appear in the investigator "
          "report instead.")

        recognition = report.get("recognition") or {}
        if recognition.get("software"):
            p("Recognized software", "heading")
            rows = [["Software", "Instances", "Confidence"]]
            for item in recognition["software"][:MAX_GROUPS]:
                rows.append([item.get("name") or "unnamed", str(item.get("count", 0)),
                             item.get("confidence") or ""])
            table = Table([[Paragraph(_markup(cell), styles["body"]) for cell in row]
                           for row in rows], colWidths=[300, 95, 100])
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#123f53")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dfe6ea")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(table)
            story.append(Spacer(1, 6))

        p("Routine activity, grouped", "heading")
        for group in routine.get("groups", [])[:MAX_GROUPS]:
            p(f"{group['label']} — {group['occurrences']} occurrence(s) across "
              f"{group['activities']} distinct command(s)", "mono")
            p(group["basis"], "quiet")
            if detailed:
                for line in group.get("commands", [])[:MAX_DETAIL_ROWS]:
                    p(f"    {line}", "mono")
                if len(group.get("commands", [])) > MAX_DETAIL_ROWS:
                    p(f"    ... and {len(group['commands']) - MAX_DETAIL_ROWS} more.", "quiet")
            references = group.get("evidence_references") or []
            p("Evidence: " + (", ".join(references[:12]) or "none recorded")
              + (f" and {len(references) - 12} more" if len(references) > 12 else ""), "quiet")
        if not routine.get("groups"):
            p("No activity in this collection was presented as routine or recognized.")

        if not detailed:
            story.append(Spacer(1, 8))
            p("Individual commands are grouped above. Request the detailed form for every command, "
              "or read the evidence package, which holds every record with its identifier.",
              "quiet")

        applied = report.get("versions") or versions()
        story.append(Spacer(1, 10))
        p(f"Produced by JOCKY {applied.get('application')} "
          f"(report schema {applied.get('report_schema')}). Recognition v"
          f"{recognition.get('recognition_version', 1)}.", "quiet")

        document.build(story)
        return buffer.getvalue()
