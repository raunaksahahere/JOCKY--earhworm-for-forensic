"""
Offline paginated reports rendered exclusively from persisted snapshots.

Two documents come out of one payload.

`render_investigator_pdf` is the report an investigator reads: the narrative,
the leads, the threads worth following, the timeline, and what could not be
collected. Six to ten pages for a normal investigation, and -- this is the
point -- its length is set by how much there is to say, not by how much was
collected. A day of telemetry on a developer's machine is 1,700 records, and
printing them made a 71-page document that nobody finishes.

`render_pdf` is the same report with every appendix appended, kept because it is
what the evidence package carries and what existing callers expect. Nothing was
removed from it; the primary report simply stops before it starts.

The evidence is identical either way. Only the presentation differs, and the
primary report says where the rest lives.
"""
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

from analysis.threads import select_reported_threads

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
MAX_MAIN_THREADS = 10
MAX_LEAD_COMMANDS = 8
MAX_THREAD_COMMANDS = 10

TRIAGE_LABELS = {
    "POTENTIALLY_HARMFUL": "POTENTIALLY HARMFUL",
    "NEEDS_REVIEW": "NOT SURE / NEEDS REVIEW",
    "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE": "NOT HARMFUL ON AVAILABLE EVIDENCE",
}

PRIORITY_LABELS = {
    "PRIORITY_1": "Priority 1 — investigate first",
    "PRIORITY_2": "Priority 2 — review",
    "PRIORITY_3": "Priority 3 — informational",
}

EVIDENCE_LABELS = {
    "EXECUTION_EVIDENCE": "EXECUTION EVIDENCE",
    "COMMAND_HISTORY": "COMMAND HISTORY",
    "SESSION_EVENT": "SESSION EVENT",
}
FONT_ROOT = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _table(rows, widths):
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Jocky"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123f53")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#123f53")),
        ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#c9d4dc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def render_pdf(report, *, detailed=True):
    """The full document: narrative plus every appendix.

    `detailed=False` produces the investigator report alone. Prefer the named
    wrappers below; this parameter exists so both documents are built by one
    code path and cannot drift apart in wording.
    """
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

        def build():
            """Paginate and render whatever is in the story so far.

            Both documents finish through here, so the footer, the margins and
            the font-coverage note are identical in each and cannot drift.
            """
            if missing:
                p("Font coverage limitation", heading)
                p("Unsupported glyphs are preserved as code-point labels: "
                  + ", ".join(sorted(missing))
                  + ". Exact Unicode text remains in the JSON report.")
            output = io.BytesIO()
            document = SimpleDocTemplate(
                output, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42,
                title=("JOCKY Investigator Report" if not detailed
                       else "JOCKY Investigation Report"),
                author="JOCKY")

            def footer(canvas, rendered):
                canvas.saveState()
                canvas.setFont("Jocky", 8)
                canvas.setFillColor(colors.HexColor("#526575"))
                canvas.drawString(42, 24, "JOCKY | Authorized local forensic collection")
                canvas.drawRightString(A4[0] - 42, 24, f"Page {rendered.page}")
                canvas.restoreState()

            document.build(story, onFirstPage=footer, onLaterPages=footer)
            return output.getvalue()

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

        # =================================================================
        # INVESTIGATOR SUMMARY. Everything below is a presentation of evidence
        # that lives in full in the appendices, the JSON export and SQLite.
        # =================================================================
        p("1. Investigation overview", heading)
        device = report.get("device") or {}
        kv("Host", device.get("hostname"))
        kv("Investigation", report.get("investigation_id"))
        kv("Collection period",
           f"{window.get('start')} to {window.get('end')}" if window else None)
        kv("Collection status", report.get("status"))
        kv("Historical telemetry",
           f"{len([s for s in sources if s['status'] == 'AVAILABLE'])} of {len(sources)} sources "
           f"read ({'AVAILABLE' if history.get('telemetry_available') else 'NOT AVAILABLE'})")
        rule()
        for label, key in (("Confirmed execution records", "execution_confirmed_records"),
                           ("Command-history records", "command_history_records"),
                           ("Session records", "session_records"),
                           ("Current processes", "current_processes"),
                           ("Artifacts observed", "artifacts"),
                           ("Findings", "findings"),
                           ("Collection limitations", "collection_limitations")):
            kv(label, counts.get(key, 0))
        rule()
        p("Conclusion", entry)
        p(report.get("conclusion") or report.get("summary", ""))

        p("2. Investigation result", heading)
        priorities = ((report.get("triage") or {}).get("priorities") or {})
        distinct_priority = ((report.get("triage") or {}).get("distinct_by_priority") or {})
        rows = [["Priority", "Records", "Distinct activity", "Meaning"]]
        for key, meaning in (
            ("PRIORITY_1", "Investigate first — several signals combine"),
            ("PRIORITY_2", "Review — a concrete reason, evidence incomplete"),
            ("PRIORITY_3", "Informational — routine or weak-signal activity"),
        ):
            rows.append([PRIORITY_LABELS[key], str(priorities.get(key, 0)),
                         str(distinct_priority.get(key, 0)), meaning])
        story.append(_table(rows, [110, 60, 95, 205]))
        story.append(Spacer(1, 8))
        distinct = ((report.get("triage") or {}).get("distinct_activity") or {})
        rows = [["What the evidence supports", "Records", "Distinct activity"]]
        for category, label in TRIAGE_LABELS.items():
            rows.append([label, str(triage_counts.get(category, 0)),
                         str(distinct.get(category, 0))])
        story.append(_table(rows, [250, 105, 115]))
        story.append(Spacer(1, 8))
        p("Triage categories are not verdicts. 'Not harmful on available evidence' means nothing "
          "in what was collected stood out; it is not a statement that the activity was safe. "
          "Missing command-line arguments are a collection limitation, never a reason for "
          "suspicion.")

        # --- Top leads: repeated patterns shown once -----------------------
        p("3. Top investigative leads", heading)
        leads = report.get("leads", []) or []
        if not leads:
            p("No activity reached the review or investigate-first tiers. This means no rule "
              "combined enough signals, not that the device is clear.")
        for lead in leads:
            p(f"{lead.get('lead_id')}   {PRIORITY_LABELS[lead['priority']].upper()}   "
              f"{TRIAGE_LABELS.get(lead['classification'], lead['classification'])}", entry)
            p(lead["title"])
            related = (f"{lead['activity_count']} related commands"
                       if lead["activity_count"] > 1 else "1 command")
            p(f"{related} | {lead['record_count']} records | Execution: "
              f"{'CONFIRMED' if lead['execution_confirmed'] else 'NOT ESTABLISHED'}"
              f"{'  | ' + (lead.get('last_seen') or '') if lead.get('last_seen') else ''}")
            for command in lead["commands"][:MAX_LEAD_COMMANDS]:
                p(command, mono)
            if len(lead["commands"]) > MAX_LEAD_COMMANDS:
                p(f"   ... {len(lead['commands']) - MAX_LEAD_COMMANDS} further commands in this "
                  "pattern are in Appendix B.")
            for why in lead.get("why", []):
                p(f"Why it matters: {why}")
            for note in lead.get("context", []):
                p(f"Context: {note}")
            for unknown in lead.get("unknowns", []):
                p(f"Unknown: {unknown}")
            if lead.get("recommended_action"):
                p(f"Next step: {lead['recommended_action']}")
            p(f"Evidence: {', '.join(lead['evidence_references'][:10])}"
              + (f", +{len(lead['evidence_references']) - 10} more"
                 if len(lead["evidence_references"]) > 10 else ""))
            rule()

        # --- Threads: related activity read as one story -------------------
        p("4. Important investigation threads", heading)
        threads = report.get("threads", []) or []
        p("Records that appear related, grouped so a sequence reads as one story. A thread states "
          "that records appear related; it does not state what anyone intended by them.")
        selection = select_reported_threads(threads, limit=MAX_MAIN_THREADS)
        tallies = selection["counts"]
        if not threads:
            p("No groups of related activity were identified.")
        else:
            # The tally first, so an investigator can see what was set aside
            # rather than wondering whether twenty-five threads existed.
            kv("Investigation threads", tallies["total"])
            kv("  Priority 1", tallies["priority_1"])
            kv("  Priority 2", tallies["priority_2"])
            kv("  Informational but noteworthy", tallies["noteworthy"])
            kv("  Routine", tallies["routine"])
            p(selection["note"])
        for thread in selection["reported"]:
            p(f"{thread['thread_id']}   {PRIORITY_LABELS[thread['priority']].upper()}   "
              f"{TRIAGE_LABELS.get(thread['classification'], thread['classification'])}", entry)
            p(f"{thread['title']} — {thread['activity_count']} activities, "
              f"{thread['record_count']} records")
            for command in thread["commands"][:MAX_THREAD_COMMANDS]:
                p(command, mono)
            if len(thread["commands"]) > MAX_THREAD_COMMANDS:
                p(f"   ... {len(thread['commands']) - MAX_THREAD_COMMANDS} further commands in "
                  "this thread are "
                  + ("in Appendix B." if detailed else "in the evidence package."))
            p(f"Why: {thread['why']}")
            p(f"Execution: {thread['execution']}")
            for unknown in thread.get("unknowns", [])[:2]:
                p(f"Unknown: {unknown}")
            p(f"Evidence: {', '.join(thread['evidence_references'][:8])}"
              + (f", +{len(thread['evidence_references']) - 8} more"
                 if len(thread["evidence_references"]) > 8 else ""))
            rule()
        if selection["withheld"]:
            p(f"{selection['withheld']} further thread(s) are not printed here. "
              + ("They are listed in full in Appendix C-2." if detailed else
                 "They are in the evidence package, each with its evidence identifiers."))

        # --- The short timeline --------------------------------------------
        p("5. Significant events", heading)
        significant = report.get("significant_events") or {}
        p(significant.get("note", ""))
        for event in significant.get("entries", []):
            when = event.get("timestamp") or "time not recorded by source"
            p(f"{when}   {EVIDENCE_LABELS.get(event['kind'], event['kind'])}"
              f"{'   ' + PRIORITY_LABELS.get(event.get('priority'), '') if event.get('priority') else ''}")
            p(f"   {event['title']}", mono)
        if not significant.get("entries"):
            p("No event met the significance threshold.")
        if significant.get("truncated"):
            p(f"{significant['candidate_count'] - significant['entry_count']} further significant "
              "events are in the evidence package.")

        # --- Everything else, counted rather than printed -------------------
        p("6. Routine activity", heading)
        routine = report.get("routine_summary") or {}
        p(f"{routine.get('records', 0)} records across {routine.get('activities', 0)} distinct "
          "activities were recognised as routine.")
        if routine.get("examples"):
            p("Common examples: " + ", ".join(routine["examples"]))
        p(routine.get("note", ""))

        p("7. Uncertain activity", heading)
        reasons = report.get("review_reasons", []) or []
        if not reasons:
            p("No activity was left uncertain.")
        for reason in reasons:
            p(f"{reason['records']} records across {reason['activities']} activities: "
              f"{reason['description']}")
            if reason.get("examples"):
                p("   e.g. " + "; ".join(str(example)[:70] for example in reason["examples"][:3]))
        p("Every one of these records is preserved in the evidence package with its own "
          "identifier, command text and source.")

        p("8. Collection limitations", heading)
        p("Gaps in what could be collected. A telemetry source that was off is a limit on this "
          "investigation, not an activity finding.")
        for item in report.get("collection_limitations", []) or []:
            p(f"[{item.get('severity', '').upper()}] {item.get('title')}", entry)
            p(item.get("explanation"))
        for note in report.get("limitations", []) or []:
            p(f"   {note}")

        p("9. Evidence package and next steps", heading)
        if detailed:
            p("The appendices that follow hold the complete record: every activity, the full "
              "command history, every finding, the process listing, artifact observations and "
              "provenance. Nothing was removed to shorten this report — the sections above are a "
              "presentation of the same evidence.")
        else:
            p("This report is the investigator-facing narrative. It is deliberately short, and its "
              "length reflects how much there is to say rather than how much was collected — "
              f"{activity.get('record_count', 0)} records were collected and none were discarded to "
              "shorten it.")
            p("Everything behind the statements above is in the evidence package, exported "
              "separately:", entry)
            p("JOCKY_Evidence_Package_" + str(report.get("investigation_id", "")) + ".zip", mono)
            for line in (
                "full command history, every activity record and every finding",
                "process, artifact, browser, USB, network, driver and memory evidence",
                "the investigation program, its compiled IR and the execution plan",
                "the audit trail, provenance and a SHA-256 for every file in the package",
            ):
                p(f"  — {line}")
            p("Two further documents are available and are not appended here: the routine activity "
              "report, which groups everything the machine could account for, and a review brief, "
              "which answers \u201cwhat is this and do I care\u201d about one artifact, finding or "
              "thread on one or two pages.")
            p("To follow up any statement in this report, take its evidence identifier and look it "
              "up in the package. Every identifier printed above resolves to a stored record.")
        kv("Total records collected", activity.get("record_count", 0))
        kv("Distinct activities", activity.get("group_count", 0))
        kv("Evidence identifiers", "EXEC- execution, CMD- command history, SESS- session, "
                                   "ART- artifact, F- finding")
        if detailed:
            fields(report.get("provenance", {}))
            fields(report.get("versions", {}))
        else:
            # The versions belong on the record even in the short document: a
            # report that cannot say which build produced it is not evidence of
            # anything. The provenance tables stay in the package.
            applied = report.get("versions") or {}
            kv("Produced by", f"JOCKY {applied.get('application')} "
                              f"(report schema {applied.get('report_schema')}, "
                              f"database schema {applied.get('database_schema')})")

        # Single-command reports carry these instead of a collection.
        for label, key in (("Command identity", "command"), ("Normalized command", "normalized_command"),
                           ("Command result", "result"), ("Errors", "errors"), ("Warnings", "warnings")):
            if key in report:
                p(label, heading)
                fields(report[key])

        if not detailed:
            # The primary report ends here. Raw evidence volume must not inflate
            # it, and appending the appendices is exactly how it would.
            return build()

        story.append(PageBreak())
        p("Appendix A: telemetry sources consulted", heading)
        listing(sources, [("", "name"), ("status", "status"), ("records", "event_count"),
                          ("proves", "evidence_strength")], limit=50)

        p("Appendix B: full command history", heading)
        p("Every command-history record, in full, with its evidence identifier. These establish "
          "that a command was entered, never that it ran.")
        history_groups = [group for group in groups if group["evidence_kind"] == "COMMAND_HISTORY"]
        for group in history_groups[:MAX_APPENDIX_ACTIVITY]:
            references = ", ".join(record["reference"] for record in group["records"][:8]
                                   if record.get("reference"))
            occurrences = f" (x{group['occurrences']})" if group["occurrences"] > 1 else ""
            p(f"{group.get('full_command_line')}{occurrences}   {references}", mono)
        if len(history_groups) > MAX_APPENDIX_ACTIVITY:
            p(f"... {len(history_groups) - MAX_APPENDIX_ACTIVITY} further command-history "
              "activities are in the JSON export and the investigation database.")

        p("Appendix C: all recorded activity", heading)
        p("Every distinct activity, with its occurrence count and evidence identifiers. Individual "
          "records are preserved in the investigation database and the JSON export.")
        for group in groups[:MAX_APPENDIX_ACTIVITY]:
            command_block(group, show_why=False)
        if len(groups) > MAX_APPENDIX_ACTIVITY:
            p(f"... {len(groups) - MAX_APPENDIX_ACTIVITY} further distinct activities are in the "
              "database and the JSON export.")

        p("Appendix C-2: investigation threads in full", heading)
        for thread in report.get("threads", []) or []:
            p(f"{thread['thread_id']} {thread['title']} — {thread['activity_count']} activities", entry)
            for command in thread["commands"]:
                p(command, mono)
            p(f"Evidence: {', '.join(thread['evidence_references'][:40])}")

        p("Appendix D: findings in full", heading)
        listing(report.get("findings", []) or [], [("", "reference"), ("", "triage"), ("", "severity"), ("", "title"),
                           ("confidence", "confidence")])

        p("Appendix E: current process listing", heading)
        listing(report.get("appendix_process_listing", []),
                [("pid", "pid"), ("", "name"), ("image", "executable"),
                 ("parent", "parent_pid"), ("started", "started_at")],
                empty="No processes were recorded.")

        p("Appendix F: artifacts", heading)
        artifacts = report.get("artifacts", []) or []
        listing(artifacts, [("", "reference"), ("", "path"), ("status", "collection_status"),
                            ("bytes", "size_bytes"), ("", "hash")])

        p("Appendix G: evidence references", heading)
        listing(report.get("evidence", []),
                [("", "id"), ("", "type"), ("source", "source"), ("status", "status"),
                 ("collected", "collected_at")])

        p("Appendix H: investigation state history", heading)
        listing(report.get("timeline", []),
                [("", "timestamp"), ("", "state"), ("", "detail")])

        p("Appendix I: execution results", heading)
        evidence_by_execution = {item.get("execution_id"): item["id"]
                                 for item in report.get("evidence", []) if item.get("execution_id")}
        listing([{**{k: v for k, v in item.items() if k != "result"},
                  "result_reference": evidence_by_execution.get(item["id"], "UNAVAILABLE")}
                 for item in report.get("executions", [])],
                [("", "command"), ("state", "state"), ("started", "started_at"),
                 ("evidence", "result_reference")])

        return build()


def render_investigator_pdf(report) -> bytes:
    """The report an investigator reads. No appendices, no raw evidence.

    Six to ten pages for a normal investigation. Its length is set by how much
    there is to say, which is the whole point: a day of telemetry on a busy
    machine is well over a thousand records, and printing them produced a
    seventy-page document that nobody finished.
    """
    return render_pdf(report, detailed=False)


def render_full_pdf(report) -> bytes:
    """The same report with every appendix, as carried in the evidence package."""
    return render_pdf(report, detailed=True)


def extract_text(pdf: bytes) -> str:
    """The visible text of a rendered document.

    Needed because a test that greps the raw file for "the report says X" passes
    against a report that says no such thing: the fonts here are subset CID
    fonts, so the content streams hold glyph indices rather than characters, and
    the streams themselves are ASCII85-then-Flate encoded.

    So this decodes the streams, reads the ToUnicode CMap the document carries
    for its own fonts, and maps the glyph codes back. It is not a general PDF
    reader -- it exists so assertions about what a document contains are
    assertions about what a reader would see.
    """
    import base64
    import binascii
    import re
    import zlib

    streams = [match.group(1).strip(b"\r\n")
               for match in re.finditer(rb"stream(.*?)endstream", pdf, re.S)]

    def decode(raw):
        for attempt in (lambda data: zlib.decompress(base64.a85decode(data, adobe=True)),
                        zlib.decompress,
                        lambda data: base64.a85decode(data, adobe=True),
                        lambda data: data):
            try:
                return attempt(raw)
            except (zlib.error, binascii.Error, ValueError):
                continue
        return b""

    decoded = [decode(raw) for raw in streams]

    # The glyph-to-character table the document supplies for its own fonts.
    glyphs = {}
    for content in decoded:
        if b"beginbfchar" not in content:
            continue
        for code, value in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                                      content[content.index(b"beginbfchar"):]):
            point = int(value, 16)
            if point:
                glyphs[int(code, 16)] = chr(point)

    collected = []
    for content in decoded:
        if b"beginbfchar" in content or b"/CIDInit" in content:
            continue
        for literal in re.findall(rb"\((?:[^()\\]|\\.)*\)", content):
            body = literal[1:-1]
            body = re.sub(rb"\\([()\\])", rb"\1", body)
            collected.append("".join(glyphs.get(byte, "") for byte in body))
    return " ".join(part for part in collected if part.strip())


def page_count(pdf: bytes) -> int:
    """How many pages a rendered document has.

    Counted from the page objects in the file rather than tracked while
    building, so the number is the one a reader would get.
    """
    import re

    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))
