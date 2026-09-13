"""Offline paginated reports rendered exclusively from persisted snapshots."""
import io
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph

_LOCK = threading.Lock()
FONT_ROOT = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def render_pdf(report):
    # ReportLab font registration/subsetting is shared process state.
    with _LOCK:
        for name, filename in (("Jocky", "NotoSans-Regular.ttf"), ("Devanagari", "NotoSansDevanagari-Regular.ttf"), ("Bengali", "NotoSansBengali-Regular.ttf")):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONT_ROOT / filename), shapable=name != "Jocky"))
        missing = set()
        def markup(value):
            fragments, run, current = [], "", None
            for char in str(value):
                code = ord(char)
                font = "Devanagari" if 0x900 <= code <= 0x97f else "Bengali" if 0x980 <= code <= 0x9ff else "Jocky"
                if code not in pdfmetrics.getFont(font).face.charToGlyph and char not in "\n\t":
                    missing.add(f"U+{code:04X}")
                    char = f"[U+{code:04X}]"
                if font != current and run:
                    fragments.append(f'<font name="{current}">{escape(run)}</font>')
                    run = ""
                current, run = font, run + char
            if run:
                fragments.append(f'<font name="{current}">{escape(run)}</font>')
            return "".join(fragments).replace("\n", "<br/>")
        body = ParagraphStyle("Body", fontName="Jocky", fontSize=8.5, leading=13, spaceAfter=6, splitLongWords=True, shaping=True)
        heading = ParagraphStyle("Heading", parent=body, fontSize=13, leading=18, spaceBefore=14, textColor=colors.HexColor("#123f53"), keepWithNext=True)
        title = ParagraphStyle("Title", parent=heading, fontSize=25, leading=30)
        story = []
        def p(value, style=body):
            story.append(Paragraph(markup(value), style))
        p("JOCKY", title)
        p("DEFENSIVE FORENSIC INVESTIGATION", heading)
        p(f"Report {report.get('report_id')} | Schema {report.get('schema_version')}")
        case = report.get("investigation", {})
        p(case.get("title", "Command report"), heading)
        for label, value in (("Investigation", report.get("investigation_id")), ("Status", report.get("status")),
                             ("Collection started", case.get("started_at")), ("Collection completed", case.get("completed_at")),
                             ("Snapshot created", report.get("created_at", report.get("timestamp")))):
            p(f"{label}: {value or 'UNAVAILABLE'}")
        from backend.storage import now
        p(f"PDF generated: {now()}")
        p("Executive summary", heading)
        p(report.get("summary", "Persisted command execution report"))
        p("OBSERVED records are collected facts. INFERRED findings require investigator review. UNAVAILABLE denotes missing observations.")
        def fields(value, prefix=""):
            if isinstance(value, dict):
                for key, item in value.items():
                    fields(item, f"{prefix} / {key}" if prefix else key)
            elif isinstance(value, list):
                if not value:
                    p(f"{prefix}: none recorded")
                for index, item in enumerate(value):
                    fields(item, f"{prefix} [{index + 1}]")
            else:
                # Break huge strings into paragraphs without dropping data.
                text = f"{prefix}: {value if value is not None else 'UNAVAILABLE'}"
                for start in range(0, len(text), 1800):
                    p(text[start:start+1800])
        for label, key in (("Device identity", "device"), ("Investigator / workstation", "investigation"),
                           ("Findings and severity", "findings"), ("Collection timeline", "timeline"),
                           ("Evidence, processes, files, hashes and integrity", "evidence"),
                           ("Execution results", "executions"), ("Command identity", "command"), ("Normalized command", "normalized_command"), ("Command result", "result"),
                           ("Errors", "errors"), ("Warnings", "warnings"),
                           ("Warnings and limitations", "limitations"), ("Versions and provenance", "versions"), ("Provenance", "provenance")):
            if key in report:
                p(label, heading)
                value = report[key]
                if key == "executions":
                    evidence_by_execution = {item.get("execution_id"): item["id"] for item in report.get("evidence", []) if item.get("execution_id")}
                    value = [{**{k: v for k, v in item.items() if k != "result"}, "result_reference": evidence_by_execution[item["id"]]} if item.get("id") in evidence_by_execution else item for item in value]
                fields(value)
        if missing:
            p("Font coverage limitation", heading)
            p("Unsupported glyphs are preserved as code-point labels: " + ", ".join(sorted(missing)) + ". Exact Unicode text remains in the JSON report.")
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42,
                                title="JOCKY Investigation Report", author="JOCKY")
        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Jocky", 8)
            canvas.setFillColor(colors.HexColor("#526575"))
            canvas.drawString(42, 24, "JOCKY | Authorized local forensic collection")
            canvas.drawRightString(A4[0] - 42, 24, f"Page {doc.page}")
            canvas.restoreState()
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return output.getvalue()
