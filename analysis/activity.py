"""
The investigator-facing view of collected activity.

Grouping here is presentation only. Eighty-seven identical `apt update` lines
are one row an investigator can skim, but every individual record keeps its own
timestamp, source and evidence identifier, and all of them remain in the
database and the JSON export. Commands that differ in any way -- two `wget`
calls to different URLs, say -- never merge.

Stable evidence identifiers are assigned here so a finding in the PDF can name
EXEC-0007 and an investigator can find exactly that record.
"""

from __future__ import annotations

from .execution_model import (
    COMMAND_HISTORY, EXECUTION_EVIDENCE, SESSION_EVENT,
)
from .triage import NEEDS_REVIEW, POTENTIALLY_HARMFUL, PRIORITY, classify_event, summarize

REFERENCE_PREFIX = {
    EXECUTION_EVIDENCE: "EXEC",
    COMMAND_HISTORY: "CMD",
    SESSION_EVENT: "SESS",
}

MAX_HIGHLIGHTED_GROUPS = 60


def assign_references(events, *, artifacts=()):
    """Give every record a short, stable identifier.

    Ordering is by evidence kind then timestamp then source record id, so the
    same collection always produces the same identifiers and a report can be
    re-read against the database it came from.
    """
    counters = {}
    ordered = sorted(
        events,
        key=lambda event: (
            event.get("evidence_kind") or "",
            event.get("timestamp") or "9999",
            str(event.get("source_record_id") or ""),
        ),
    )
    for event in ordered:
        prefix = REFERENCE_PREFIX.get(event.get("evidence_kind"), "EVT")
        counters[prefix] = counters.get(prefix, 0) + 1
        event["reference"] = f"{prefix}-{counters[prefix]:04d}"
    for index, record in enumerate(artifacts, start=1):
        record["reference"] = f"ART-{index:04d}"
    return events


def _group_key(event):
    """What makes two records the same activity.

    The full command line, when there is one: `wget URL_A` and `wget URL_B` are
    different activity and must stay apart. Otherwise the executable, so that
    repeated runs of one image collapse while different images do not.
    """
    return (
        event.get("evidence_kind"),
        event.get("full_command_line") or f"\0exe:{event.get('executable') or event.get('process_name')}",
    )


def build_activity(events, *, artifacts=()) -> dict:
    """Classify, group and rank the collected activity."""
    by_path = {record["path"]: record for record in artifacts}
    groups = {}

    for event in events:
        classification = classify_event(event, artifacts_by_path=by_path)
        key = _group_key(event)
        group = groups.get(key)
        if group is None:
            groups[key] = group = {
                "evidence_kind": event.get("evidence_kind"),
                "full_command_line": event.get("full_command_line"),
                "normalized_command": event.get("normalized_command"),
                "command_reconstruction_status": event.get("command_reconstruction_status"),
                "command_evidence_strength": event.get("command_evidence_strength"),
                "executable": event.get("executable"),
                "process_name": event.get("process_name"),
                "execution_confirmed": bool(event.get("execution_confirmed")),
                "classification": classification.to_dict(),
                "sources": [],
                "occurrences": 0,
                "first_seen": None,
                "last_seen": None,
                "undated_occurrences": 0,
                # Presentation groups; the individual records stay addressable.
                "records": [],
            }
        group["occurrences"] += 1
        group["execution_confirmed"] |= bool(event.get("execution_confirmed"))
        if event.get("source") not in group["sources"]:
            group["sources"].append(event.get("source"))
        stamp = event.get("timestamp")
        if stamp:
            group["first_seen"] = min(group["first_seen"] or stamp, stamp)
            group["last_seen"] = max(group["last_seen"] or stamp, stamp)
        else:
            group["undated_occurrences"] += 1
        group["records"].append({
            "reference": event.get("reference"),
            "event_id": event.get("event_id"),
            "timestamp": stamp,
            "source": event.get("source"),
            "source_record_id": event.get("source_record_id"),
            "pid": event.get("pid"),
            "user": event.get("user"),
            # The raw command exactly as the source recorded it, per record, so
            # grouping can never be mistaken for losing one.
            "full_command_line": event.get("full_command_line"),
        })
        # The strongest classification in a group wins: one concerning instance
        # is not cancelled out by routine repetitions of the same text.
        if classification.priority < PRIORITY[group["classification"]["category"]]:
            group["classification"] = classification.to_dict()

    ranked = sorted(
        groups.values(),
        key=lambda group: (
            group["classification"]["priority"],
            # Confirmed execution outranks command history at equal concern.
            0 if group["execution_confirmed"] else 1,
            # Then the most recent, undated last.
            group["last_seen"] is None,
            _descending(group["last_seen"]),
        ),
    )

    classifications = [group["classification"] for group in ranked]
    return {
        "groups": ranked,
        "group_count": len(ranked),
        "record_count": sum(group["occurrences"] for group in ranked),
        "highlights": ranked[:MAX_HIGHLIGHTED_GROUPS],
        "triage": summarize_groups(ranked),
        "counts_by_kind": _counts_by_kind(ranked),
        "note": ("Repeated identical activity is shown once with an occurrence count. Every "
                 "individual record keeps its own identifier, timestamp and source, and all of "
                 "them remain in the investigation database and the JSON export."),
    }


def _descending(stamp):
    """Sort newest first without reversing the rest of the key."""
    if not stamp:
        return ""
    return "".join(chr(0x10FFFD - ord(char)) if ord(char) < 0x10FFFD else char for char in stamp)


def summarize_groups(groups) -> dict:
    """Triage counts over records, not groups: 87 routine runs are 87 records."""
    record_counts, group_counts = {}, {}
    for group in groups:
        category = group["classification"]["category"]
        record_counts[category] = record_counts.get(category, 0) + group["occurrences"]
        group_counts[category] = group_counts.get(category, 0) + 1
    summary = summarize([group["classification"] for group in groups])
    summary["counts"] = {key: record_counts.get(key, 0) for key in summary["counts"]}
    summary["distinct_activity"] = {key: group_counts.get(key, 0) for key in summary["counts"]}
    return summary


def _counts_by_kind(groups) -> dict:
    """Accurate, separately named totals -- never one blurred 'events' number."""
    counts = {}
    for group in groups:
        kind = group["evidence_kind"]
        counts[kind] = counts.get(kind, 0) + group["occurrences"]
    return {
        "execution_source_records": counts.get(EXECUTION_EVIDENCE, 0),
        "command_history_records": counts.get(COMMAND_HISTORY, 0),
        "session_records": counts.get(SESSION_EVENT, 0),
    }


def search_activity(groups, term) -> list:
    """Match against the full command text, not the executable alone.

    Searching "holehe" or "github.com" finds the records that contain it,
    because the raw command, the search form, the executable, the user and the
    source are all matched.
    """
    if not term:
        return list(groups)
    needle = term.strip().lower()
    matched = []
    for group in groups:
        haystack = " ".join(str(value) for value in (
            group.get("full_command_line"), group.get("normalized_command"),
            group.get("executable"), group.get("process_name"),
            group.get("evidence_kind"), group["classification"]["category"],
            " ".join(group.get("sources") or ()),
            " ".join(str(record.get("user") or "") for record in group["records"]),
        ) if value)
        if needle in haystack.lower():
            matched.append(group)
    return matched
