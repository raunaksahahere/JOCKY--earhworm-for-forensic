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

# A report a human can read. The JSON export and the database keep everything.
MAX_RENDERED_ROWS = 400
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
        def listing(records, columns, *, empty="none recorded", limit=MAX_RENDERED_ROWS):
            """One line per record. Keeps a long section readable and bounded."""
            if not records:
                p(empty)
                return
            for record in records[:limit]:
                parts = []
                for label, key in columns:
                    value = record.get(key)
                    if isinstance(value, (dict, list)):
                        value = f"{len(value)} entries"
                    parts.append(f"{label} {value if value not in (None, '') else 'UNAVAILABLE'}")
                p(" | ".join(parts))
            if len(records) > limit:
                p(f"... {len(records) - limit} further entries are omitted from this PDF for length. "
                  "The complete set is present in the JSON export and in the investigation database.")

        p("Device information", heading)
        fields(report.get("device", {}))

        p("Collection window", heading)
        window = report.get("collection_window")
        if window:
            p(f"{window.get('start')} to {window.get('end')} "
              f"({window.get('requested_hours')} hours requested; bounded at {window.get('maximum_hours')})")
            p("Historical collection is always bounded. Activity outside this window was not examined.")
        else:
            p("UNAVAILABLE: no historical collection window was recorded for this investigation.")

        p("Historical execution evidence", heading)
        history = report.get("historical_execution", {})
        if history.get("telemetry_available"):
            p(f"Platform: {history.get('platform')} | {history.get('event_count', 0)} records "
              f"| {history.get('undated_event_count', 0)} undated | truncated: {history.get('truncated')}")
            p("Sources consulted:")
            listing(history.get("sources", []),
                    [("", "name"), ("status", "status"), ("records", "event_count"),
                     ("proves", "evidence_strength")], limit=50)
            p("Records:")
            listing(history.get("events", []),
                    [("", "timestamp"), ("", "process_name"), ("image", "executable"),
                     ("pid", "pid"), ("user", "user"), ("source", "source")])
        else:
            p("NOT COLLECTED: no historical execution telemetry was available on this host. This "
              "investigation cannot establish what ran before collection started.")
            listing(history.get("sources", []), [("", "name"), ("status", "status"), ("", "detail")], limit=50)

        p("Current process snapshot", heading)
        snapshot = report.get("current_process_snapshot", {})
        p("CURRENT OBSERVATION. A running process establishes the present, not the past.")
        fields(snapshot)
        p("The full per-process listing is in the appendix at the end of this report.")

        p("Timeline", heading)
        p("Ordered by the timestamp each source recorded. Undated records are listed separately.")
        listing(report.get("event_timeline", []),
                [("", "timestamp"), ("", "kind"), ("", "title"), ("source", "source")])

        p("Artifacts", heading)
        artifacts = report.get("artifacts", [])
        listing(artifacts, [("", "path"), ("status", "collection_status"), ("bytes", "size_bytes"),
                            ("modified", "modified")])

        p("Hashes", heading)
        hashed = [record for record in artifacts if record.get("hash")]
        p("A hash compares bytes. It does not prove authenticity or acquisition-chain integrity.")
        listing(hashed, [("", "path"), ("", "hash_algorithm"), ("", "hash")],
                empty="No artifact digests were recorded.")

        p("Indicators", heading)
        flagged = [record for record in artifacts if record.get("indicators")]
        if flagged:
            for record in flagged[:MAX_RENDERED_ROWS]:
                for indicator in record["indicators"]:
                    p(f"{record['path']} | {indicator.get('level')} | {indicator.get('label')} | "
                      f"{indicator.get('detail')}")
        else:
            p("No filename indicators were raised.")

        p("Integrity results", heading)
        checked = [record for record in artifacts if record.get("integrity") or record.get("integrity_history")]
        listing(checked, [("", "path"),
                          ("structural", "integrity"), ("versus ledger", "integrity_history")],
                empty="No structural integrity checks were recorded.")

        p("Findings", heading)
        p("Rule-based triage. A name, extension or directory is a reason to look, never a verdict.")
        listing(report.get("findings", []),
                [("", "severity"), ("", "title"), ("confidence", "confidence"),
                 ("classification", "classification")])

        p("Evidence references", heading)
        listing(report.get("evidence", []),
                [("", "id"), ("", "type"), ("source", "source"), ("status", "status"),
                 ("collected", "collected_at")])

        p("Collection limitations", heading)
        fields(report.get("limitations", []))

        p("Unavailable telemetry", heading)
        listing(report.get("unavailable_telemetry", []),
                [("", "source"), ("", "status"), ("", "detail")],
                empty="Every telemetry source JOCKY consulted was available.")

        p("Provenance", heading)
        fields(report.get("provenance", {}))

        p("Version information", heading)
        fields(report.get("versions", {}))

        p("Investigation state history", heading)
        listing(report.get("timeline", []),
                [("", "timestamp"), ("", "state"), ("", "detail")])

        # Single-command reports carry these instead of a collection.
        for label, key in (("Command identity", "command"), ("Normalized command", "normalized_command"),
                           ("Command result", "result"), ("Errors", "errors"), ("Warnings", "warnings")):
            if key in report:
                p(label, heading)
                fields(report[key])

        p("Appendix A: execution results", heading)
        evidence_by_execution = {item.get("execution_id"): item["id"]
                                 for item in report.get("evidence", []) if item.get("execution_id")}
        listing([{**{k: v for k, v in item.items() if k != "result"},
                  "result_reference": evidence_by_execution.get(item["id"], "UNAVAILABLE")}
                 for item in report.get("executions", [])],
                [("", "command"), ("state", "state"), ("started", "started_at"),
                 ("evidence", "result_reference")])

        p("Appendix B: current process listing", heading)
        p("The complete snapshot, moved here so it does not dominate the report body.")
        listing(report.get("appendix_process_listing", []),
                [("pid", "pid"), ("", "name"), ("image", "executable"),
                 ("parent", "parent_pid"), ("started", "started_at")],
                empty="No processes were recorded.")

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
