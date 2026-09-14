"""
Review briefs: one page about one thing.

An investigator looking at `ART-0041` in a list of two thousand records has one
question -- what is this, and do I care -- and answering it currently means
reading the evidence package. A brief answers it from the evidence already
stored, in a fixed shape, with every statement traceable to the record it rests
on.

The discipline here is that a brief may only say what some stored record
supports. "Downloaded by the browser" requires a browser download record naming
that path. "Connected to a remote address" requires a socket record naming that
process. Proximity in a timeline is not a link, and where the evidence only
supports proximity the brief says so in those words.

A brief is never a verdict. It has a "What is unknown" section that is filled in
as carefully as the rest, because the gap is usually the reason the investigator
was looking.
"""

from __future__ import annotations

import os
from collections import Counter

from .triage import LABELS, PRIORITY_LABELS

BRIEF_VERSION = 1

ARTIFACT, FINDING, ACTIVITY, EVENT, THREAD, LEAD = (
    "artifact", "finding", "activity", "execution_event", "thread", "lead")
SUBJECT_TYPES = (ARTIFACT, FINDING, ACTIVITY, EVENT, THREAD, LEAD)

MAX_RELATED = 12
MAX_SENTENCES = 5

NOT_A_VERDICT = (
    "This brief summarises collected evidence about one subject. It is not a malware verdict and "
    "not a statement that the subject is safe or harmful.")


class BriefError(ValueError):
    pass


def _cite(kind, identifier, **extra):
    return {"kind": kind, "id": identifier, **{k: v for k, v in extra.items() if v is not None}}


def _section(title, body, citations=()):
    """One labelled part of a brief, with the evidence it rests on."""
    return {"title": title, "body": body, "evidence": list(citations)}


class _Corpus:
    """Everything one investigation stored, indexed for lookup.

    A brief queries this rather than re-running collection: the evidence was
    written once, and reading it again is the whole point of having stored it.
    """

    def __init__(self, report):
        self.report = report
        self.activity = report.get("activity") or {}
        self.groups = self.activity.get("groups") or []
        self.threads = report.get("threads") or []
        self.findings = report.get("findings") or []
        self.artifacts = report.get("artifacts") or []
        self.limitations = report.get("limitations") or []
        self.supplementary = report.get("supplementary") or {}

        self.events = []
        for group in self.groups:
            self.events.extend(group.get("records") or [])

        self.by_reference = {}
        for record in self.events:
            if record.get("reference"):
                self.by_reference[record["reference"]] = record
        self.artifact_by_reference = {record["reference"]: record for record in self.artifacts
                                      if record.get("reference")}
        self.artifact_by_path = {record["path"]: record for record in self.artifacts
                                 if record.get("path")}
        self.group_by_reference = {}
        for group in self.groups:
            for record in group.get("records") or []:
                if record.get("reference"):
                    self.group_by_reference[record["reference"]] = group
        self.leads = report.get("leads") or []
        # A group carries no identifier of its own -- an investigator addresses
        # it by one of its evidence references -- so threads are indexed by the
        # references of their members' records.
        self.thread_by_reference = {}
        for thread in self.threads:
            for reference in thread.get("evidence_references") or []:
                self.thread_by_reference[reference] = thread

    def members_of(self, thread):
        """The activity groups a thread's evidence references belong to."""
        groups, seen = [], set()
        for reference in thread.get("evidence_references") or []:
            group = self.group_by_reference.get(reference)
            if group is not None and id(group) not in seen:
                seen.add(id(group))
                groups.append(group)
        return groups

    def records_for(self, references):
        return [self.by_reference[reference] for reference in references
                if reference in self.by_reference]

    def thread_for(self, group):
        for record in group.get("records") or []:
            thread = self.thread_by_reference.get(record.get("reference"))
            if thread:
                return thread
        return None

    # --- evidence-backed context lookups ---------------------------------
    def browser_for(self, path):
        """Download records naming this exact path. Never inferred from timing."""
        downloads = (self.supplementary.get("BROWSER") or {}).get("downloads") or []
        return [record for record in downloads if record.get("target_path") == path]

    def network_for(self, process_name):
        """Socket records whose owning process matches. Also never inferred."""
        connections = (self.supplementary.get("NETWORK") or {}).get("connections") or []
        return [record for record in connections
                if process_name and record.get("process_name") == process_name]

    def usb_for(self, path):
        usb = self.supplementary.get("USB") or {}
        mounts = [mount for mount in usb.get("mounts") or []
                  if mount.get("mount_point") and path and path.startswith(mount["mount_point"])]
        return mounts, (usb.get("events") or []) if mounts else []

    def findings_citing(self, reference):
        matched = []
        for finding in self.findings:
            ids = {item.get("id") for item in finding.get("evidence_references") or []}
            if reference in ids:
                matched.append(finding)
        return matched

    def sessions_for(self, user):
        return [record for record in self.events
                if record.get("evidence_kind") == "SESSION_EVENT" and record.get("user") == user]


def _execution_state(records):
    """What the evidence establishes about whether something ran."""
    if any(record.get("execution_confirmed") for record in records):
        sources = sorted({record.get("source") for record in records
                          if record.get("execution_confirmed")})
        return "CONFIRMED", f"Recorded as having run by {', '.join(filter(None, sources))}."
    if any(record.get("evidence_kind") == "COMMAND_HISTORY" for record in records):
        return "NOT ESTABLISHED", (
            "The command appears in shell history, which records that it was entered. Nothing in "
            "the collected evidence establishes that it ran.")
    if any(record.get("evidence_kind") == "PROCESS_SNAPSHOT" for record in records):
        return "CURRENT ONLY", (
            "Observed running at collection time. That says nothing about earlier activity.")
    return "NOT ESTABLISHED", "No collected record establishes that this ran."


def _recognition_state(recognition):
    if not recognition:
        return "NOT APPLICABLE", "No executable path was available to identify."
    if recognition.get("recognized"):
        name = recognition.get("recognized_name")
        version = f" {recognition['version']}" if recognition.get("version") else ""
        basis = "; ".join(recognition.get("recognition_basis") or [])
        return "RECOGNIZED", f"{name}{version}. {basis}"
    limits = " ".join(recognition.get("limitations") or [])
    return "UNKNOWN", limits or "Nothing in the collected evidence accounts for this path."


def _sentences(parts):
    return " ".join(part for part in parts if part)[:1500]


# --- artifact ----------------------------------------------------------------
def _artifact_brief(corpus, subject_id):
    record = corpus.artifact_by_reference.get(subject_id)
    if record is None:
        raise BriefError(f"No artifact {subject_id} in this investigation")
    path = record.get("path")
    recognition = record.get("recognition") or {}
    recognition_state, recognition_detail = _recognition_state(recognition)

    naming = [item for item in corpus.events
              if path and (item.get("executable") == path
                           or (item.get("full_command_line") or "").find(path) >= 0)]
    execution_state, execution_detail = _execution_state(naming)
    findings = corpus.findings_citing(subject_id)
    downloads = corpus.browser_for(path)
    mounts, usb_events = corpus.usb_for(path)
    group = next((corpus.group_by_reference[item["reference"]] for item in naming
                  if item.get("reference") in corpus.group_by_reference), None)
    thread = corpus.thread_for(group) if group else None

    citations = [_cite("artifact", subject_id, path=path, sha256=record.get("hash"))]
    citations += [_cite("execution_event", item.get("reference"), source=item.get("source"))
                  for item in naming[:MAX_RELATED] if item.get("reference")]
    citations += [_cite("finding", finding.get("reference")) for finding in findings
                  if finding.get("reference")]

    summary = _sentences([
        f"{os.path.basename(path or subject_id)} was observed at {path} and hashed.",
        (f"It is accounted for as {recognition.get('recognized_name')}"
         + (f" {recognition['version']}" if recognition.get("version") else "") + "."
         if recognition.get("recognized") else
         "Nothing in the collected evidence accounts for what this file is."),
        (f"{len(naming)} execution or command record(s) name this path."
         if naming else "No collected execution or command record names this path."),
        execution_detail,
        (f"{len(findings)} finding(s) cite it." if findings else None),
    ])

    known, unknown = [], []
    known.append(f"The file was present at {path} at collection time and its SHA-256 was recorded.")
    if record.get("size_bytes") is not None:
        known.append(f"It is {record['size_bytes']} bytes, last modified {record.get('modified')}.")
    if recognition.get("recognized"):
        known.append(f"It is accounted for by {recognition.get('source')}.")
    else:
        unknown.append("What this file is. No package, snap or installation layout accounts for it.")
    if not naming:
        unknown.append("Whether it ever ran. No collected record names it as having executed.")
    if not downloads:
        unknown.append("How it arrived on this machine.")
    if recognition.get("recognized"):
        unknown.append("Whether the bytes are still the ones the package installed. "
                       "That needs a comparison against a published hash.")

    return {
        "subject": {"type": ARTIFACT, "id": subject_id, "label": path or subject_id},
        "classification": (group or {}).get("classification", {}).get("label", "not classified"),
        "presentation": (group or {}).get("classification", {}).get("presentation_label"),
        "priority": (group or {}).get("classification", {}).get("priority_label", "not ranked"),
        "execution": {"state": execution_state, "detail": execution_detail},
        "recognition": {"state": recognition_state, "detail": recognition_detail},
        "summary": summary,
        "why_surfaced": (
            "; ".join(finding.get("title") for finding in findings) if findings
            else (group or {}).get("classification", {}).get("reason")
            or "This artifact was hashed because collected evidence referenced its path."),
        "sections": [
            _section("Related activity",
                     [f"{item.get('reference')}  {item.get('full_command_line') or item.get('executable')}"
                      for item in naming[:MAX_RELATED]] or ["No related command or execution record."],
                     [_cite("execution_event", item.get("reference")) for item in naming[:MAX_RELATED]]),
            _section("Related artifacts",
                     [f"{other['reference']}  {other['path']}" for other in corpus.artifacts
                      if other.get("hash") and other.get("hash") == record.get("hash")
                      and other.get("reference") != subject_id][:MAX_RELATED]
                     or ["No other collected artifact shares this hash."]),
            _section("Browser context",
                     [f"Downloaded from {item.get('url')} at {item.get('downloaded_at')}"
                      for item in downloads]
                     or ["No browser download record names this path. How the file arrived is not "
                         "established by the collected evidence."],
                     [_cite("browser_download", item.get("url")) for item in downloads]),
            _section("USB context",
                     [f"Path is under removable media mounted at {mount.get('mount_point')}"
                      for mount in mounts]
                     or ["This path is not under any removable media recorded in this collection."],
                     [_cite("removable_device", mount.get("device")) for mount in mounts]),
            _section("Network context",
                     ["Network evidence is associated with a process, not with a file on disk. "
                      "See the related execution records for any process activity."]),
        ],
        "known": known,
        "unknown": unknown,
        "thread": thread.get("thread_id") if thread else None,
        "evidence": citations,
        "suggested_review": _artifact_review(record, recognition, naming, downloads),
    }


def _artifact_review(record, recognition, naming, downloads):
    steps = []
    if not recognition.get("recognized"):
        steps.append("Establish what this file is: check whether any package manager, installer or "
                     "person on this machine accounts for it.")
    if recognition.get("recognized"):
        steps.append(f"Compare the recorded SHA-256 against the published hash for "
                     f"{recognition.get('recognized_name')} to confirm the bytes are unmodified.")
    if naming:
        steps.append("Read the full commands in the related activity above and decide whether they "
                     "fit the expected use of this machine.")
    if downloads:
        steps.append("Check the download source and whether the person using this machine intended "
                     "to obtain it.")
    if not steps:
        steps.append("No specific step is indicated by the collected evidence.")
    return steps


# --- finding -----------------------------------------------------------------
def _finding_brief(corpus, subject_id):
    finding = next((item for item in corpus.findings if item.get("reference") == subject_id), None)
    if finding is None:
        raise BriefError(f"No finding {subject_id} in this investigation")

    references = finding.get("evidence_references") or []
    events = [corpus.by_reference[item["id"]] for item in references
              if item.get("id") in corpus.by_reference]
    artifacts = [corpus.artifact_by_reference[item["id"]] for item in references
                 if item.get("id") in corpus.artifact_by_reference]
    execution_state, execution_detail = _execution_state(events)
    recognition = next((item.get("recognition") for item in artifacts + events
                        if item.get("recognition")), None)
    recognition_state, recognition_detail = _recognition_state(recognition)

    return {
        "subject": {"type": FINDING, "id": subject_id, "label": finding.get("title")},
        # A stored finding row carries the codes; the labels live with the
        # vocabulary that defines them rather than being duplicated per row.
        "classification": LABELS.get(finding.get("triage"), finding.get("triage")),
        "presentation": None,
        "priority": finding.get("priority_label")
        or PRIORITY_LABELS.get(finding.get("investigator_priority")),
        "execution": {"state": execution_state, "detail": execution_detail},
        "recognition": {"state": recognition_state, "detail": recognition_detail},
        "summary": _sentences([finding.get("explanation")]),
        "why_surfaced": finding.get("why") or finding.get("explanation"),
        "sections": [
            _section("Evidence this rests on",
                     [f"{item.get('kind')}  {item.get('id')}" for item in references]
                     or ["This finding cites no evidence."], references),
            _section("Related activity",
                     [f"{item.get('reference')}  {item.get('full_command_line') or item.get('executable')}"
                      for item in events[:MAX_RELATED]] or ["No related activity record."]),
            _section("Related artifacts",
                     [f"{item.get('reference')}  {item.get('path')}" for item in artifacts[:MAX_RELATED]]
                     or ["No related artifact record."]),
            _section("Confidence",
                     [finding.get("confidence", "not stated"),
                      f"Severity: {finding.get('severity')}"]),
        ],
        "known": [finding.get("why") or finding.get("explanation")],
        "unknown": list(finding.get("unknowns") or []) or ["None stated for this finding."],
        "thread": None,
        "evidence": references,
        "suggested_review": [finding.get("recommended_action")] if finding.get("recommended_action")
        else ["No specific step is indicated by the collected evidence."],
    }


# --- activity and execution event --------------------------------------------
def _activity_brief(corpus, subject_id):
    group = corpus.group_by_reference.get(subject_id)
    if group is None:
        raise BriefError(
            f"No activity record {subject_id} in this investigation. An activity is addressed by "
            "one of its evidence identifiers, such as EXEC-0001 or CMD-0001.")

    records = group.get("records") or []
    classification = group.get("classification") or {}
    execution_state, execution_detail = _execution_state(records)
    recognition = next((record.get("recognition") for record in records
                        if record.get("recognition")), None)
    recognition_state, recognition_detail = _recognition_state(recognition)
    command = group.get("full_command_line") or group.get("executable") or group.get("process_name")
    artifact = corpus.artifact_by_path.get(group.get("executable"))
    downloads = corpus.browser_for(group.get("executable"))
    connections = corpus.network_for(group.get("process_name"))
    users = sorted({record.get("user") for record in records if record.get("user")})
    findings = [finding for record in records
                for finding in corpus.findings_citing(record.get("reference"))]
    thread = corpus.thread_for(group)

    citations = [_cite("execution_event", record.get("reference"), source=record.get("source"))
                 for record in records[:MAX_RELATED] if record.get("reference")]
    if artifact:
        citations.append(_cite("artifact", artifact.get("reference"), path=artifact.get("path")))

    return {
        "subject": {"type": ACTIVITY, "id": subject_id, "label": command},
        "classification": classification.get("label"),
        "presentation": classification.get("presentation_label"),
        "priority": classification.get("priority_label"),
        "execution": {"state": execution_state, "detail": execution_detail},
        "recognition": {"state": recognition_state, "detail": recognition_detail},
        "summary": _sentences([
            f"{command}",
            f"Recorded {group.get('occurrences', len(records))} time(s) by "
            f"{', '.join(group.get('sources') or []) or 'an unnamed source'}.",
            execution_detail,
            recognition_detail if recognition_state == "RECOGNIZED" else None,
        ]),
        "why_surfaced": classification.get("presentation_reason") or classification.get("reason"),
        "sections": [
            _section("Occurrences",
                     [f"{record.get('reference')}  {record.get('timestamp') or 'undated'}  "
                      f"{record.get('source')}" for record in records[:MAX_RELATED]], citations),
            _section("Related artifacts",
                     [f"{artifact['reference']}  {artifact['path']}  sha256 {artifact.get('hash')}"]
                     if artifact else
                     ["No collected artifact matches this executable path."]),
            _section("Browser context",
                     [f"Downloaded from {item.get('url')} at {item.get('downloaded_at')}"
                      for item in downloads]
                     or ["No browser download record names this executable."]),
            _section("Network context",
                     [f"{item.get('process_name')} -> {item.get('remote_address')}:"
                      f"{item.get('remote_port')} ({item.get('status')})"
                      for item in connections[:MAX_RELATED]]
                     or ["No socket record in this collection is owned by a process of this name. "
                         "Note that a socket table is a snapshot; it cannot show a connection that "
                         "had already closed."]),
            _section("User and session context",
                     [f"Recorded for user {user}" for user in users]
                     or ["No user was recorded for these records."]),
            _section("Findings citing this",
                     [f"{finding.get('reference')}  {finding.get('title')}" for finding in findings]
                     or ["No finding cites these records."]),
        ],
        "known": [classification.get("reason")] + list(classification.get("why") or []),
        "unknown": list(classification.get("unknowns") or []) or
        ["Nothing further is stated as unknown for this record."],
        "thread": thread.get("thread_id") if thread else None,
        "evidence": citations,
        "suggested_review": [classification.get("recommended_action")]
        if classification.get("recommended_action") else
        ["No specific step is indicated by the collected evidence."],
    }


# --- thread ------------------------------------------------------------------
def _thread_brief(corpus, subject_id):
    thread = next((item for item in corpus.threads if item.get("thread_id") == subject_id), None)
    if thread is None:
        raise BriefError(f"No thread {subject_id} in this investigation")

    members = corpus.members_of(thread)
    records = corpus.records_for(thread.get("evidence_references") or [])
    execution_state, execution_detail = _execution_state(records)
    priorities = Counter(member.get("classification", {}).get("priority_label") for member in members)
    presentations = Counter(member.get("classification", {}).get("presentation_label")
                            for member in members)
    recognized = sorted({(record.get("recognition") or {}).get("recognized_name")
                         for record in records
                         if (record.get("recognition") or {}).get("recognized")} - {None})

    ordered = sorted(members, key=lambda member: member.get("first_seen") or "")
    artifacts = [corpus.artifact_by_path[member["executable"]] for member in members
                 if member.get("executable") in corpus.artifact_by_path]
    connections = [item for member in members
                   for item in corpus.network_for(member.get("process_name"))]
    users = sorted({record.get("user") for record in records if record.get("user")})
    findings = [finding for record in records
                for finding in corpus.findings_citing(record.get("reference"))]

    citations = [_cite("execution_event", record.get("reference")) for record in records[:40]
                 if record.get("reference")]
    citations += [_cite("artifact", item.get("reference"), path=item.get("path"))
                  for item in artifacts]

    return {
        "subject": {"type": THREAD, "id": subject_id, "label": thread.get("title")},
        "classification": thread.get("classification") or "not classified",
        "presentation": presentations.most_common(1)[0][0] if presentations else None,
        "priority": priorities.most_common(1)[0][0] if priorities else thread.get("priority"),
        "execution": {"state": execution_state, "detail": execution_detail},
        "recognition": {
            "state": "RECOGNIZED" if recognized else "UNKNOWN",
            "detail": ("Software accounted for in this thread: " + ", ".join(recognized))
            if recognized else "No executable in this thread is accounted for by system metadata.",
        },
        "summary": _sentences([
            thread.get("title") + ".",
            thread.get("why"),
            f"{thread.get('activity_count', len(members))} related activities across "
            f"{thread.get('record_count', len(records))} record(s).",
            execution_detail,
        ]),
        "why_surfaced": thread.get("why") or thread.get("title"),
        "sections": [
            _section("Sequence",
                     [f"{member.get('first_seen') or 'undated'}  "
                      f"{member.get('full_command_line') or member.get('executable')}"
                      for member in ordered], citations),
            _section("Commands", list(thread.get("commands") or [])
                     or ["No full command was recorded for these records."]),
            _section("Related artifacts",
                     [f"{item['reference']}  {item['path']}  sha256 {item.get('hash')}"
                      for item in artifacts] or ["No collected artifact matches these executables."]),
            _section("Network context",
                     [f"{item.get('process_name')} -> {item.get('remote_address')}:"
                      f"{item.get('remote_port')}" for item in connections[:MAX_RELATED]]
                     or ["No socket record is owned by a process named in this thread."]),
            _section("User and session context",
                     [f"Recorded for user {user}" for user in users]
                     or ["No user was recorded for these records."]),
            _section("Findings citing this thread",
                     [f"{finding.get('reference')}  {finding.get('title')}" for finding in findings]
                     or ["No finding cites these records."]),
        ],
        "known": [thread.get("why")] + [f"Shared terms: {', '.join(thread.get('shared_terms') or [])}"
                                        if thread.get("shared_terms") else None],
        "unknown": list(thread.get("unknowns") or []) + [
            "What connected these activities beyond the shared terms and timing JOCKY matched on. "
            "A thread states that records appear related, never what anyone intended by them.",
        ],
        "thread": subject_id,
        "evidence": citations,
        "suggested_review": [
            "Read the sequence above in order and decide whether it describes expected use of this "
            "machine.",
        ],
    }


def _lead_brief(corpus, subject_id):
    lead = next((item for item in corpus.leads if item.get("lead_id") == subject_id), None)
    if lead is None:
        raise BriefError(f"No lead {subject_id} in this investigation")

    members = lead.get("groups") or []
    records = [record for member in members for record in member.get("records") or []]
    execution_state, execution_detail = _execution_state(records)
    artifacts = [corpus.artifact_by_path[member["executable"]] for member in members
                 if member.get("executable") in corpus.artifact_by_path]
    connections = [item for member in members
                   for item in corpus.network_for(member.get("process_name"))]
    downloads = [item for member in members
                 for item in corpus.browser_for(member.get("executable"))]
    users = sorted({record.get("user") for record in records if record.get("user")})
    findings = [finding for record in records
                for finding in corpus.findings_citing(record.get("reference"))]
    recognized = sorted({(record.get("recognition") or {}).get("recognized_name")
                         for record in records
                         if (record.get("recognition") or {}).get("recognized")} - {None})

    citations = [_cite("execution_event", record.get("reference")) for record in records[:40]
                 if record.get("reference")]
    citations += [_cite("artifact", item.get("reference"), path=item.get("path"))
                  for item in artifacts]

    return {
        "subject": {"type": LEAD, "id": subject_id, "label": lead.get("title")},
        "classification": lead.get("classification"),
        "presentation": (members[0].get("classification", {}).get("presentation_label")
                         if members else None),
        "priority": lead.get("priority_label"),
        "execution": {"state": execution_state, "detail": execution_detail},
        "recognition": {
            "state": "RECOGNIZED" if recognized else "UNKNOWN",
            "detail": ("Software accounted for here: " + ", ".join(recognized)) if recognized
            else "No executable in this lead is accounted for by system metadata.",
        },
        "summary": _sentences([
            lead.get("title") + ".",
            f"{lead.get('activity_count')} distinct command(s) show this pattern across "
            f"{lead.get('record_count')} record(s).",
            execution_detail,
        ]),
        "why_surfaced": "; ".join(lead.get("why") or []) or lead.get("title"),
        "sections": [
            _section("Commands in this pattern", list(lead.get("commands") or [])[:MAX_RELATED]
                     or ["No full command was recorded."], citations),
            _section("Related artifacts",
                     [f"{item['reference']}  {item['path']}" for item in artifacts]
                     or ["No collected artifact matches these executables."]),
            _section("Browser context",
                     [f"Downloaded from {item.get('url')}" for item in downloads]
                     or ["No browser download record names these executables."]),
            _section("Network context",
                     [f"{item.get('process_name')} -> {item.get('remote_address')}:"
                      f"{item.get('remote_port')}" for item in connections[:MAX_RELATED]]
                     or ["No socket record is owned by a process named in this lead."]),
            _section("User and session context",
                     [f"Recorded for user {user}" for user in users]
                     or ["No user was recorded for these records."]),
            _section("Findings citing this lead",
                     [f"{finding.get('reference')}  {finding.get('title')}" for finding in findings]
                     or ["No finding cites these records."]),
        ],
        "known": list(lead.get("why") or []),
        "unknown": list(lead.get("unknowns") or []) or ["Nothing further is stated as unknown."],
        "thread": None,
        "evidence": citations,
        "suggested_review": [lead.get("recommended_action")] if lead.get("recommended_action")
        else ["No specific step is indicated by the collected evidence."],
    }


_BUILDERS = {
    ARTIFACT: _artifact_brief, FINDING: _finding_brief, ACTIVITY: _activity_brief,
    EVENT: _activity_brief, THREAD: _thread_brief, LEAD: _lead_brief,
}


def build_brief(report, *, subject_type, subject_id) -> dict:
    """Assemble one brief from an investigation's stored report payload."""
    kind = (subject_type or "").strip().lower()
    if kind not in _BUILDERS:
        raise BriefError(f"Cannot brief a '{subject_type}'. "
                         f"Available: {', '.join(sorted(SUBJECT_TYPES))}")
    if not subject_id:
        raise BriefError("A brief needs the identifier of the subject to describe")

    corpus = _Corpus(report)
    brief = _BUILDERS[kind](corpus, subject_id)
    brief.update({
        "brief_version": BRIEF_VERSION,
        "investigation_id": report.get("investigation_id"),
        "case_id": (report.get("investigation") or {}).get("case_id"),
        "versions": report.get("versions"),
        "collection_limitations": [
            item.get("detail") if isinstance(item, dict) else str(item)
            for item in corpus.limitations][:MAX_RELATED],
        "disclaimer": NOT_A_VERDICT,
    })
    brief["evidence_ids"] = sorted({item.get("id") for item in brief["evidence"] if item.get("id")})
    return brief
