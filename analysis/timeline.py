"""
One ordered view of everything the investigation observed.

The timeline merges sources that record fundamentally different things, so
every entry keeps its kind, its source and its classification. An entry is
never given a timestamp it did not have: undated records are collected
separately and reported as undated rather than being placed at an invented
point in time.
"""

from __future__ import annotations

EXECUTION_EVENT = "EXECUTION_EVENT"
FILE_EVENT = "FILE_EVENT"
OBSERVATION = "OBSERVATION"
ANALYSIS_FINDING = "ANALYSIS_FINDING"
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
        name = event.get("process_name") or event.get("executable") or "unnamed process"
        place(_entry(
            EXECUTION_EVENT, event.get("timestamp"),
            title=f"{name} — {event.get('source')}",
            detail=event.get("evidence_strength"),
            source=event.get("source"),
            classification=event.get("classification"),
            references=[{"kind": "execution_event", "id": event.get("event_id")}],
            extra={
                "executable": event.get("executable"),
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
            FILE_EVENT, record.get("modified"),
            title=f"{record['filename']} last modified",
            detail=(f"Filesystem modification time for {record['path']}. This is metadata read at "
                    "collection time, not an observation of the change happening."),
            source=record.get("source"),
            classification="OBSERVED" if record["collection_status"] == "COLLECTED" else "UNAVAILABLE",
            references=[{"kind": "artifact", "id": record["path"], "hash": record.get("hash")}],
            extra={"collection_status": record["collection_status"], "size_bytes": record.get("size_bytes")},
        ))

    snapshot = processes or {}
    for process in snapshot.get("processes", []) or []:
        place(_entry(
            OBSERVATION, process.get("started_at"),
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
            ANALYSIS_FINDING, finding.get("timestamp"),
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
