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
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_LOCK = threading.Lock()

# A report a human can read before reaching for the database. The main body is
# deliberately short; the appendices, the JSON export and SQLite keep everything.
MAX_RENDERED_ROWS = 300
MAX_MAIN_ACTIVITY = 25
MAX_MAIN_REVIEW = 15
MAX_MAIN_EVIDENCE = 12
MAX_MAIN_FINDINGS = 12
MAX_ROUTINE_PREVIEW = 10
MAX_SESSION_ROWS = 12
MAX_APPENDIX_ACTIVITY = 400

TRIAGE_LABELS = {
    "POTENTIALLY_HARMFUL": "POTENTIALLY HARMFUL",
    "NEEDS_REVIEW": "NOT SURE / NEEDS REVIEW",
    "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE": "NOT HARMFUL ON AVAILABLE EVIDENCE",
}

EVIDENCE_LABELS = {
    "EXECUTION_EVIDENCE": "EXECUTION EVIDENCE",
    "COMMAND_HISTORY": "COMMAND HISTORY",
    "SESSION_EVENT": "SESSION EVENT",
}
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
        entry = ParagraphStyle("Entry", parent=body, fontSize=8.5, spaceBefore=6, spaceAfter=1,
                               textColor=colors.HexColor("#1d2b36"), keepWithNext=True)
        mono = ParagraphStyle("Mono", parent=body, fontName="Jocky", fontSize=8.5, leading=12,
                              leftIndent=10, spaceAfter=2, textColor=colors.HexColor("#0b2b3a"))
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

        def rule():
            story.append(Spacer(1, 4))

        def kv(label, value):
            p(f"<b>{markup(label)}</b> {markup(value if value not in (None, '') else 'UNAVAILABLE')}"
              if False else f"{label}: {value if value not in (None, '') else 'UNAVAILABLE'}")

        def command_block(group, *, show_why=True):
            """One activity entry: what ran or was typed, and what that proves.

            The command is printed in full on its own line. Shortening it to the
            executable would throw away the most useful thing the source
            captured, which is the whole point of this section.
            """
            triage = group["classification"]
            when = group.get("last_seen") or group.get("first_seen")
            occurrences = f" x{group['occurrences']}" if group["occurrences"] > 1 else ""
            references = ", ".join(
                record["reference"] for record in group["records"][:6] if record.get("reference"))
            if len(group["records"]) > 6:
                references += f", +{len(group['records']) - 6} more"
            p(f"[{TRIAGE_LABELS.get(triage['category'], triage['category'])}] "
              f"{when or 'time not recorded by source'}{occurrences}   {references}", entry)
            command = group.get("full_command_line")
            if command:
                p(command, mono)
            else:
                image = group.get("executable") or group.get("process_name") or "unnamed process"
                p(image, mono)
                p("Full command line: not available from collected evidence "
                  f"({group.get('command_reconstruction_status')})")
            p(f"{EVIDENCE_LABELS.get(group['evidence_kind'], group['evidence_kind'])} | "
              f"{'execution confirmed by the source' if group['execution_confirmed'] else 'execution NOT established'}"
              f" | command {group.get('command_reconstruction_status')}"
              f"/{group.get('command_evidence_strength') or 'n/a'}"
              f" | {', '.join(group.get('sources') or [])}")
            if show_why:
                p(f"Why: {triage['reason']}")
            rule()

        def activity_section(title, groups, *, limit, empty, note=None):
            p(title, heading)
            if note:
                p(note)
            if not groups:
                p(empty)
                return
            for group in groups[:limit]:
                command_block(group)
            if len(groups) > limit:
                p(f"... {len(groups) - limit} further distinct activities are listed in the "
                  "appendices and held in full in the investigation database.")

        activity = report.get("activity") or {}
        groups = activity.get("groups", []) or []
        counts = report.get("record_counts", {}) or {}
        triage_counts = ((report.get("triage") or {}).get("counts") or {})
        history = report.get("historical_execution", {}) or {}
        sources = history.get("sources", []) or []
        window = report.get("collection_window")

        # --- Page 1: investigation overview -------------------------------
        p("Collection coverage", heading)
        kv("Host", (report.get("device") or {}).get("hostname"))
        kv("Collection window", f"{window.get('start')} to {window.get('end')}" if window else None)
        kv("Historical execution telemetry",
           "AVAILABLE" if history.get("telemetry_available") else "NOT AVAILABLE")
        kv("Telemetry sources read",
           f"{len([s for s in sources if s['status'] == 'AVAILABLE'])} of {len(sources)}")
        rule()
        for label, key in (("Execution-source records", "execution_source_records"),
                           ("Command-history records", "command_history_records"),
                           ("Session records", "session_records"),
                           ("Records with confirmed execution", "execution_confirmed_records"),
                           ("Distinct activities", "distinct_activity"),
                           ("Current processes", "current_processes"),
                           ("Artifacts", "artifacts"),
                           ("Findings", "findings"),
                           ("Collection limitations", "collection_limitations")):
            kv(label, counts.get(key, 0))
        rule()
        for category, label in TRIAGE_LABELS.items():
            kv(label, triage_counts.get(category, 0))

        # --- Page 2: triage summary ---------------------------------------
        p("Triage summary", heading)
        p("Triage categories are not verdicts. 'Not harmful based on available evidence' means "
          "nothing in what was collected stood out; it is not a statement that the activity was safe.")
        distinct = ((report.get("triage") or {}).get("distinct_activity") or {})
        rows = [["Classification", "Records", "Distinct activity", "Priority"]]
        for index, (category, label) in enumerate(TRIAGE_LABELS.items(), start=1):
            rows.append([label, str(triage_counts.get(category, 0)),
                         str(distinct.get(category, 0)), str(index)])
        table = Table(rows, colWidths=[230, 70, 110, 60], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Jocky"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123f53")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#123f53")),
            ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#c9d4dc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

        p("Findings", heading)
        findings = report.get("findings", []) or []
        # Lead with what an investigator has to act on. Corroboration and
        # routine observations are real findings and are kept, but listing them
        # first buries the ones that matter.
        notable = [finding for finding in findings
                   if finding.get("triage") != "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"]
        reassuring = len(findings) - len(notable)
        if not findings:
            p("No findings were raised. This means no rule matched the collected evidence, not that "
              "the device is clear.")
        elif not notable:
            p("No finding requires attention or review. Every finding records corroboration or a "
              "routine observation.")
        for finding in notable[:MAX_MAIN_FINDINGS]:
            references = ", ".join(str(item.get("id")) for item in (finding.get("detail") or [])
                                   if isinstance(item, dict))
            p(f"[{TRIAGE_LABELS.get(finding.get('triage'), finding.get('severity', '').upper())}] "
              f"{finding.get('reference') or ''}  {finding.get('title')}", entry)
            p(f"Why: {finding.get('why') or finding.get('explanation')}")
            p(f"Confidence: {finding.get('confidence')} | Classification: {finding.get('classification')}"
              + (f" | Evidence: {references}" if references else ""))
            rule()
        if len(notable) > MAX_MAIN_FINDINGS:
            p(f"... {len(notable) - MAX_MAIN_FINDINGS} further findings needing attention are listed "
              "in Appendix C.")
        if reassuring:
            p(f"{reassuring} further findings record corroboration or routine observations — the "
              "image named by the evidence was present and hashed, and nothing in the collected "
              "evidence stood out. They are listed in full in Appendix C.")

        # --- Page 3: the activity that matters ----------------------------
        attention = [group for group in groups
                     if group["classification"]["category"] == "POTENTIALLY_HARMFUL"]
        review = [group for group in groups
                  if group["classification"]["category"] == "NEEDS_REVIEW"]
        routine = [group for group in groups
                   if group["classification"]["category"] == "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"]

        activity_section(
            "Activity requiring attention", attention, limit=MAX_MAIN_ACTIVITY,
            empty="No activity in the collected evidence matched a concern rule.",
            note="Each entry shows the command exactly as its source recorded it.")

        activity_section(
            "Activity needing review", review, limit=MAX_MAIN_REVIEW,
            empty="No ambiguous activity was recorded.",
            note="Recorded activity that is neither recognised as routine nor matched by a concern "
                 "rule. Intent cannot be determined from the evidence alone.")

        p("Routine activity", heading)
        if routine:
            p(f"{sum(group['occurrences'] for group in routine)} records across "
              f"{len(routine)} distinct activities were recognised as routine and are listed in "
              "Appendix B. Nothing in the collected evidence identified them as concerning.")
            for group in routine[:MAX_ROUTINE_PREVIEW]:
                p(f"  {group.get('full_command_line') or group.get('executable') or group.get('process_name')}"
                  f"  (x{group['occurrences']})")
        else:
            p("No activity was recognised as routine.")

        # --- Evidence separated by what it proves --------------------------
        confirmed = [group for group in groups if group["evidence_kind"] == "EXECUTION_EVIDENCE"]
        typed = [group for group in groups if group["evidence_kind"] == "COMMAND_HISTORY"]
        sessions = [group for group in groups if group["evidence_kind"] == "SESSION_EVENT"]

        activity_section(
            "Confirmed execution evidence", confirmed[:MAX_MAIN_EVIDENCE], limit=MAX_MAIN_EVIDENCE,
            empty="No source that records execution was available on this host.",
            note="These records come from sources that record execution itself. The command line is "
                 "shown when the source captured it.")

        activity_section(
            "User-entered command history", typed[:MAX_MAIN_EVIDENCE], limit=MAX_MAIN_EVIDENCE,
            empty="No shell history was readable.",
            note="These are commands entered into a shell. Execution is NOT established by these "
                 "records: the text was typed, which does not show that it ran, succeeded, or ran "
                 "at the recorded time.")

        p("Session and login activity", heading)
        if sessions:
            for group in sessions[:MAX_SESSION_ROWS]:
                p(f"  {group.get('last_seen') or 'time not recorded'}  "
                  f"{group.get('process_name')}  x{group['occurrences']}  "
                  f"({', '.join(group.get('sources') or [])})")
        else:
            p("No session records were collected.")

        p("Current process observations", heading)
        snapshot = report.get("current_process_snapshot", {}) or {}
        p("CURRENT OBSERVATION. A running process establishes the present, not the past.")
        statistics = snapshot.get("statistics", {}) or {}
        kv("Processes recorded", f"{statistics.get('processes_recorded')} of "
                                 f"{statistics.get('processes_present')} present")
        kv("Permission denied", statistics.get("permission_denied"))
        kv("Truncated", snapshot.get("truncated"))
        p("The full listing is in Appendix D.")

        # --- Collection limitations, kept apart from findings ---------------
        p("Collection limitations", heading)
        p("Gaps in what could be collected. A telemetry source that was off is a limit on this "
          "investigation, not an activity finding.")
        for item in report.get("collection_limitations", []) or []:
            p(f"[{item.get('severity', '').upper()}] {item.get('title')}", entry)
            p(item.get("explanation"))
            rule()
        for note in report.get("limitations", []) or []:
            p(f"  {note}")

        p("Unavailable telemetry", heading)
        unavailable = report.get("unavailable_telemetry", []) or []
        if unavailable:
            for item in unavailable:
                p(f"  {item['source']} | {item['status']} | {item['detail']}")
        else:
            p("Every telemetry source JOCKY consulted was available.")

        p("Device information", heading)
        fields(report.get("device", {}))

        p("Provenance and versions", heading)
        fields(report.get("provenance", {}))
        fields(report.get("versions", {}))

        # Single-command reports carry these instead of a collection.
        for label, key in (("Command identity", "command"), ("Normalized command", "normalized_command"),
                           ("Command result", "result"), ("Errors", "errors"), ("Warnings", "warnings")):
            if key in report:
                p(label, heading)
                fields(report[key])

        # --- Appendices: the detail, in full -------------------------------
        story.append(PageBreak())
        p("Appendix A: telemetry sources consulted", heading)
        listing(sources, [("", "name"), ("status", "status"), ("records", "event_count"),
                          ("proves", "evidence_strength")], limit=50)

        p("Appendix B: all recorded activity", heading)
        p("Every distinct activity, with its occurrence count and evidence identifiers. Individual "
          "records are preserved in the investigation database and the JSON export.")
        for group in groups[:MAX_APPENDIX_ACTIVITY]:
            command_block(group, show_why=False)
        if len(groups) > MAX_APPENDIX_ACTIVITY:
            p(f"... {len(groups) - MAX_APPENDIX_ACTIVITY} further distinct activities are in the "
              "database and the JSON export.")

        p("Appendix C: findings in full", heading)
        listing(findings, [("", "reference"), ("", "triage"), ("", "severity"), ("", "title"),
                           ("confidence", "confidence")])

        p("Appendix D: current process listing", heading)
        listing(report.get("appendix_process_listing", []),
                [("pid", "pid"), ("", "name"), ("image", "executable"),
                 ("parent", "parent_pid"), ("started", "started_at")],
                empty="No processes were recorded.")

        p("Appendix E: artifacts", heading)
        artifacts = report.get("artifacts", []) or []
        listing(artifacts, [("", "reference"), ("", "path"), ("status", "collection_status"),
                            ("bytes", "size_bytes"), ("", "hash")])

        p("Appendix F: evidence references", heading)
        listing(report.get("evidence", []),
                [("", "id"), ("", "type"), ("source", "source"), ("status", "status"),
                 ("collected", "collected_at")])

        p("Appendix G: investigation state history", heading)
        listing(report.get("timeline", []),
                [("", "timestamp"), ("", "state"), ("", "detail")])

        p("Appendix H: execution results", heading)
        evidence_by_execution = {item.get("execution_id"): item["id"]
                                 for item in report.get("evidence", []) if item.get("execution_id")}
        listing([{**{k: v for k, v in item.items() if k != "result"},
                  "result_reference": evidence_by_execution.get(item["id"], "UNAVAILABLE")}
                 for item in report.get("executions", [])],
                [("", "command"), ("state", "state"), ("started", "started_at"),
                 ("evidence", "result_reference")])

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
