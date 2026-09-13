"""
One ordered view of everything the investigation observed.

The timeline merges sources that record fundamentally different things, so
every entry keeps its kind, its source and its classification. An entry is
never given a timestamp it did not have: undated records are collected
separately and reported as undated rather than being placed at an invented
point in time.
"""

from __future__ import annotations

# Entry kinds mirror the evidence kinds, because the distinction between "a
# source recorded this running" and "someone typed this" is the one an
# investigator most needs the timeline to keep. A shell history line is never
# EXECUTION_EVIDENCE merely because it contains a command.
EXECUTION_EVIDENCE = "EXECUTION_EVIDENCE"
COMMAND_HISTORY = "COMMAND_HISTORY"
SESSION_EVENT = "SESSION_EVENT"
PROCESS_SNAPSHOT = "PROCESS_SNAPSHOT"
ARTIFACT_OBSERVATION = "ARTIFACT_OBSERVATION"
FINDING = "FINDING"
INVESTIGATION_STATE = "INVESTIGATION_STATE"

MAX_TIMELINE_ENTRIES = 10000


def _entry(kind, timestamp, *, title, detail, source, classification, references=None, extra=None):
    return {
        "kind": kind,
        "timestamp": timestamp,
        "title": title,
        "detail": detail,
        "source": source,
        "classification": classification,
        "references": references or [],
        **(extra or {}),
    }


def build_timeline(*, execution=None, artifacts=None, processes=None, findings=(), transitions=()):
    """Merge every observation into one ordered sequence.

    Returns dated entries in chronological order plus the undated ones, kept
    apart so nothing implies a time that was never recorded.
    """
    dated, undated = [], []

    def place(entry):
        (dated if entry["timestamp"] else undated).append(entry)

    for event in (execution or {}).get("events", []) or []:
        # The title is the command when one was recorded. Showing only the
        # executable would discard the most useful thing the source captured.
        name = (event.get("full_command_line")
                or event.get("executable") or event.get("process_name") or "unnamed process")
        place(_entry(
            event.get("evidence_kind") or EXECUTION_EVIDENCE, event.get("timestamp"),
            title=name,
            detail=event.get("evidence_strength"),
            source=event.get("source"),
            classification=event.get("classification"),
            references=[{"kind": "execution_event",
                         "id": event.get("reference") or event.get("event_id")}],
            extra={
                "executable": event.get("executable"),
                "process_name": event.get("process_name"),
                "full_command_line": event.get("full_command_line"),
                "command_reconstruction_status": event.get("command_reconstruction_status"),
                "execution_confirmed": bool(event.get("execution_confirmed")),
                "pid": event.get("pid"),
                "user": event.get("user"),
                "last_seen": event.get("last_seen"),
                "unavailable": event.get("unavailable", {}),
            },
        ))

    for record in (artifacts or {}).get("artifacts", []) or []:
        # A file's modification time is a property of the file, not a record
        # that JOCKY watched it change; the classification says so.
        place(_entry(
            ARTIFACT_OBSERVATION, record.get("modified"),
            title=f"{record['filename']} last modified",
            detail=(f"Filesystem modification time for {record['path']}. This is metadata read at "
                    "collection time, not an observation of the change happening."),
            source=record.get("source"),
            classification="OBSERVED" if record["collection_status"] == "COLLECTED" else "UNAVAILABLE",
            references=[{"kind": "artifact", "id": record.get("reference") or record["path"],
                         "path": record["path"], "hash": record.get("hash")}],
            extra={"collection_status": record["collection_status"], "size_bytes": record.get("size_bytes")},
        ))

    snapshot = processes or {}
    for process in snapshot.get("processes", []) or []:
        place(_entry(
            PROCESS_SNAPSHOT, process.get("started_at"),
            title=f"{process.get('name') or 'unnamed process'} running (PID {process.get('pid')})",
            detail=("Present in the current process snapshot. A running process establishes the present, "
                    "not the past."),
            source=snapshot.get("action", "process_snapshot"),
            classification=process.get("classification", "CURRENT_OBSERVATION"),
            references=[{"kind": "process", "id": process.get("pid")}],
            extra={"executable": process.get("executable"), "pid": process.get("pid")},
        ))

    for finding in findings or ():
        place(_entry(
            FINDING, finding.get("timestamp"),
            title=finding.get("title"),
            detail=finding.get("explanation"),
            source="JOCKY correlation",
            classification=finding.get("classification", "INFERRED"),
            references=finding.get("evidence_references", []),
            extra={"severity": finding.get("severity"), "confidence": finding.get("confidence"),
                   "category": finding.get("category")},
        ))

    for transition in transitions or ():
        place(_entry(
            INVESTIGATION_STATE, transition.get("timestamp"),
            title=f"Investigation state: {transition.get('state')}",
            detail=transition.get("detail"),
            source="JOCKY workstation",
            classification="OBSERVED",
        ))

    dated.sort(key=lambda entry: entry["timestamp"])
    truncated = len(dated) + len(undated) > MAX_TIMELINE_ENTRIES
    if truncated:
        dated = dated[-MAX_TIMELINE_ENTRIES:]
        undated = undated[: max(0, MAX_TIMELINE_ENTRIES - len(dated))]

    return {
        "entries": dated,
        "undated_entries": undated,
        "entry_count": len(dated),
        "undated_count": len(undated),
        "truncated": truncated,
        "kinds": sorted({entry["kind"] for entry in dated + undated}),
        "statistics": _counts(dated + undated),
        "limits": {"max_entries": MAX_TIMELINE_ENTRIES},
        "note": ("Entries are ordered by the timestamp their own source recorded. Undated entries are listed "
                 "separately because their source records no time; they are not the most recent activity."),
    }


def _counts(entries):
    by_kind = {}
    for entry in entries:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    return {"by_kind": by_kind}


MAX_SIGNIFICANT_EVENTS = 40


def build_significant_events(*, activity=None, findings=(), artifacts=None, transitions=(),
                             limit=MAX_SIGNIFICANT_EVENTS) -> dict:
    """The events that actually help explain the investigation.

    The full timeline is every record the collection produced, which on an
    ordinary desktop is thousands of lines and explains nothing. This is the
    short version: activity that needs attention, findings, artifacts the
    evidence named and could not find, and the investigation's own state
    changes. Everything else stays in the full timeline and the database.
    """
    activity = activity or {}
    artifacts = artifacts or {}
    entries = []

    for group in activity.get("groups", []) or []:
        classification = group["classification"]
        if classification["investigator_priority"] not in {"PRIORITY_1", "PRIORITY_2"}:
            continue
        entries.append(_entry(
            group["evidence_kind"], group.get("last_seen") or group.get("first_seen"),
            title=(group.get("full_command_line") or group.get("executable")
                   or group.get("process_name") or "unnamed activity"),
            detail=classification["reason"],
            source=", ".join(group.get("sources") or []),
            classification=classification["category"],
            references=[{"kind": "execution_event", "id": record["reference"]}
                        for record in group["records"][:6] if record.get("reference")],
            extra={"priority": classification["investigator_priority"],
                   "occurrences": group["occurrences"],
                   "execution_confirmed": group["execution_confirmed"]},
        ))

    for finding in findings or ():
        if finding.get("triage") == "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE":
            continue
        entries.append(_entry(
            FINDING, finding.get("timestamp"),
            title=f"{finding.get('reference') or 'finding'}: {finding.get('title')}",
            detail=finding.get("why") or finding.get("explanation"),
            source="JOCKY correlation",
            classification=finding.get("classification", "INFERRED"),
            extra={"priority": finding.get("investigator_priority"),
                   "severity": finding.get("severity")},
        ))

    # An artifact the evidence named and could not find is worth a line; the
    # hundreds that were present and unremarkable are not.
    for record in (artifacts.get("artifacts", []) or []):
        if record.get("collection_status") != "MISSING":
            continue
        entries.append(_entry(
            ARTIFACT_OBSERVATION, record.get("modified"),
            title=f"{record['filename']} named by evidence but absent",
            detail=f"No file exists at {record['path']} at collection time.",
            source=record.get("source"),
            classification="UNAVAILABLE",
            references=[{"kind": "artifact", "id": record.get("reference") or record["path"]}],
        ))

    for transition in transitions or ():
        entries.append(_entry(
            INVESTIGATION_STATE, transition.get("timestamp"),
            title=f"Investigation state: {transition.get('state')}",
            detail=transition.get("detail"),
            source="JOCKY workstation", classification="OBSERVED"))

    dated = sorted((entry for entry in entries if entry["timestamp"]),
                   key=lambda entry: entry["timestamp"])
    undated = [entry for entry in entries if not entry["timestamp"]]
    selected = (dated + undated)[:limit]
    return {
        "entries": selected,
        "entry_count": len(selected),
        "candidate_count": len(entries),
        "truncated": len(entries) > limit,
        "note": ("Only events that help explain the investigation. The complete timeline and "
                 "every underlying record remain in the evidence package and the database."),
    }
