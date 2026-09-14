"""
The generated case summary, and the record of what each sentence rests on.

A summary is the most dangerous thing a forensic tool produces: it is the part
people read, and it is the part furthest from the evidence. So every sentence
here is assembled from a count or a stored record, and every sentence is emitted
with the evidence identifiers behind it. A statement that cannot name its
evidence is not written at all.

The summary deliberately never reaches for a reassuring phrase. "No priority-1
activity was identified" is a statement about what was collected and ranked. It
is not "the machine is clean", and the closing sentence says so.
"""

from __future__ import annotations

MAX_CITED = 30


def _statement(section, text, evidence=()):
    return {"section": section, "statement": text,
            "evidence_ids": sorted({item for item in evidence if item})[:MAX_CITED]}


def _lead_evidence(lead):
    return list(lead.get("evidence_references") or [])


def build_case_summary(report) -> dict:
    """A short readable conclusion, with each sentence's evidence attached."""
    counts = report.get("record_counts") or {}
    activity = report.get("activity") or {}
    groups = activity.get("groups") or []
    leads = report.get("leads") or []
    threads = report.get("threads") or []
    findings = report.get("findings") or []
    recognition = report.get("recognition") or {}
    limitations = report.get("limitations") or []
    sources = (report.get("historical_execution") or {}).get("sources") or []

    statements = []

    # --- what was looked at ---------------------------------------------
    available = [source for source in sources if source.get("status") == "AVAILABLE"]
    unavailable = [source for source in sources if source.get("status") != "AVAILABLE"]
    statements.append(_statement(
        "scope",
        f"{counts.get('distinct_activity', len(groups))} distinct activities were reconstructed "
        f"from {len(available)} of {len(sources)} telemetry sources, together with "
        f"{counts.get('artifacts', 0)} hashed artifacts."))
    if unavailable:
        statements.append(_statement(
            "scope",
            "Not every source could be read: "
            + "; ".join(f"{source['name']} ({source['status']})" for source in unavailable[:6])
            + ". Nothing should be concluded from the absence of evidence those would have held."))

    # --- priority 1 -------------------------------------------------------
    priority_one = [lead for lead in leads if lead.get("priority") == "PRIORITY_1"]
    if priority_one:
        for lead in priority_one[:5]:
            statements.append(_statement(
                "priority", f"{lead['title']}: {lead.get('activity_count', 0)} command(s) across "
                            f"{lead.get('record_count', 0)} record(s), "
                + ("recorded as having run."
                   if lead.get("execution_confirmed") else
                   "not established as having run by the collected evidence."),
                _lead_evidence(lead)))
    else:
        statements.append(_statement(
            "priority",
            "No priority-1 activity was identified. That is a statement about what was collected "
            "and how it ranked, not a finding that the machine is clean."))

    # --- priority 2 -------------------------------------------------------
    review = [lead for lead in leads if lead.get("priority") == "PRIORITY_2"]
    if review:
        unconfirmed = [lead for lead in review if not lead.get("execution_confirmed")]
        statements.append(_statement(
            "review",
            f"{len(review)} pattern(s) require review"
            + (f", of which {len(unconfirmed)} rest on command history alone: the text was "
               "entered, and the collected evidence does not establish that it ran."
               if unconfirmed else "."),
            [reference for lead in review for reference in _lead_evidence(lead)]))

    # --- recognition ------------------------------------------------------
    recognized = recognition.get("artifacts_recognized") or 0
    if recognized:
        names = ", ".join(item["name"] for item in (recognition.get("software") or [])[:4]
                          if item.get("name"))
        statements.append(_statement(
            "recognition",
            f"{recognized} of {recognition.get('artifacts_examined', 0)} artifacts were accounted "
            f"for by package metadata or installation layout"
            + (f", including {names}" if names else "")
            + ". Being accounted for is not a finding that they are harmless."))
    unattributed = [record for record in report.get("artifacts") or []
                    if (record.get("recognition") or {}).get("basis_codes")
                    == ["trusted_system_location"]]
    if unattributed:
        statements.append(_statement(
            "recognition",
            f"{len(unattributed)} file(s) sit in operating-system directories that no package "
            "claims. Which of the two that is worth resolving.",
            [record.get("reference") for record in unattributed]))

    # --- threads ----------------------------------------------------------
    if threads:
        leading = threads[0]
        statements.append(_statement(
            "threads",
            f"{len(threads)} activity thread(s) were formed, the largest being \"{leading['title']}\" "
            f"across {leading.get('activity_count', 0)} activities. A thread states that records "
            "appear related, never what anyone intended by them.",
            leading.get("evidence_references") or []))

    # --- findings ---------------------------------------------------------
    if findings:
        by_priority = {}
        for finding in findings:
            key = finding.get("investigator_priority") or "PRIORITY_3"
            by_priority[key] = by_priority.get(key, 0) + 1
        statements.append(_statement(
            "findings",
            f"{len(findings)} finding(s) were produced: "
            + ", ".join(f"{count} at {priority.replace('_', ' ').lower()}"
                        for priority, count in sorted(by_priority.items()))
            + ". Each names the evidence it rests on and what it cannot establish.",
            [finding.get("reference") for finding in findings]))

    # --- limitations ------------------------------------------------------
    if limitations:
        statements.append(_statement(
            "limitations",
            f"{len(limitations)} collection limitation(s) are recorded. They bound what any "
            "conclusion here can cover."))

    return {
        "statements": statements,
        "text": " ".join(item["statement"] for item in statements),
        "closing": ("This summary describes the collected evidence. It is not a verdict about the "
                    "machine, and the absence of a finding is not evidence that nothing happened."),
        "evidence_ids": sorted({reference for item in statements
                                for reference in item["evidence_ids"]}),
    }
