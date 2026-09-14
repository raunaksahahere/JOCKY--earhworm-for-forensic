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
from .triage import (
    NEEDS_REVIEW, NOT_HARMFUL, POTENTIALLY_HARMFUL, PRIORITY, PRIORITY_1, PRIORITY_2,
    PRIORITY_3, PRIORITY_LABELS, PRIORITY_ORDER, classify_event, summarize,
)

MAX_LEADS = 10

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
    """Classify, group and rank the collected activity.

    Corroboration is computed first, across the whole collection, because how
    many independent sources named an executable is a property of the evidence
    set rather than of any one record.
    """
    by_path = {record["path"]: record for record in artifacts}
    sources_by_image = {}
    for event in events:
        image = event.get("executable")
        if image:
            sources_by_image.setdefault(image, set()).add(event.get("source"))
    groups = {}

    for event in events:
        image = event.get("executable")
        classification = classify_event(
            event,
            artifacts_by_path=by_path,
            source_count=len(sources_by_image.get(image, ())) or 1,
            correlated_artifact=by_path.get(image) if image else None,
        )
        key = _group_key(event)
        group = groups.get(key)
        if group is None:
            groups[key] = group = {
                "evidence_kind": event.get("evidence_kind"),
                "full_command_line": event.get("full_command_line"),
                "normalized_command": event.get("normalized_command"),
                "command_reconstruction_status": event.get("command_reconstruction_status"),
                "command_evidence_strength": event.get("command_evidence_strength"),
                "lead_id": None,
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
        # The most urgent instance in a group wins: one concerning occurrence is
        # not cancelled out by routine repetitions of the same text.
        current = group["classification"]
        candidate = classification.to_dict()
        if (candidate["priority_rank"], candidate["priority"]) < (
                current["priority_rank"], current["priority"]):
            group["classification"] = candidate

    ranked = sorted(
        groups.values(),
        key=lambda group: (
            # Investigator priority first: what to look at, before what it is.
            group["classification"]["priority_rank"],
            -group["classification"]["score"],
            group["classification"]["priority"],
            # Confirmed execution outranks command history at equal urgency.
            0 if group["execution_confirmed"] else 1,
            # Then the most recent, undated last.
            group["last_seen"] is None,
            _descending(group["last_seen"]),
        ),
    )

    leads = build_leads(ranked)

    return {
        "groups": ranked,
        "group_count": len(ranked),
        "record_count": sum(group["occurrences"] for group in ranked),
        "highlights": ranked[:MAX_HIGHLIGHTED_GROUPS],
        # The investigator's first actionable view.
        "leads": leads,
        "lead_count": len(leads),
        "by_priority": {
            PRIORITY_1: [g for g in ranked if g["classification"]["investigator_priority"] == PRIORITY_1],
            PRIORITY_2: [g for g in ranked if g["classification"]["investigator_priority"] == PRIORITY_2],
            PRIORITY_3: [g for g in ranked if g["classification"]["investigator_priority"] == PRIORITY_3],
        },
        "triage": summarize_groups(ranked),
        "counts_by_kind": _counts_by_kind(ranked),
        "review_reasons": summarize_review_reasons(ranked),
        "routine_summary": summarize_routine(ranked),
        "note": ("Repeated identical activity is shown once with an occurrence count. Every "
                 "individual record keeps its own identifier, timestamp and source, and all of "
                 "them remain in the investigation database and the JSON export."),
    }


#: Why a group is uncertain, in the investigator's terms. Ordered: the first
#: matching reason is the one reported, so each group is counted once.
_REVIEW_REASONS = (
    ("command_history_only",
     "Command recorded in history, execution not established",
     lambda group: group["evidence_kind"] == "COMMAND_HISTORY"),
    ("arguments_unavailable",
     "Execution confirmed, but the source did not record the arguments",
     lambda group: group["execution_confirmed"]
     and group.get("command_reconstruction_status") in {"EXECUTABLE_ONLY", "NOT_AVAILABLE"}),
    ("unusual_path",
     "Image runs from a writable or unusual location",
     lambda group: any(signal["name"] == "execution_from_writable_location"
                       for signal in group["classification"]["signals"])),
    ("interpreter_context",
     "Interpreter used without enough context to say what it ran",
     lambda group: any(signal["name"] in {"remote_content_to_interpreter", "encoded_powershell"}
                       for signal in group["classification"]["signals"])),
)


def summarize_review_reasons(groups) -> list[dict]:
    """Group the uncertain activity by why it is uncertain.

    "820 records need review" tells an investigator nothing. Knowing that most
    of them are confirmed executions whose arguments the source never captured
    tells them where the gap is, and that it is a telemetry limit rather than a
    pile of leads.
    """
    tally = {}
    for group in groups:
        if group["classification"]["category"] != NEEDS_REVIEW:
            continue
        for key, description, matches in _REVIEW_REASONS:
            if matches(group):
                entry = tally.setdefault(key, {"reason": key, "description": description,
                                               "activities": 0, "records": 0, "examples": []})
                break
        else:
            entry = tally.setdefault("unclassified",
                                     {"reason": "unclassified",
                                      "description": "Recorded, but no reason rule matched",
                                      "activities": 0, "records": 0, "examples": []})
        entry["activities"] += 1
        entry["records"] += group["occurrences"]
        if len(entry["examples"]) < 5:
            entry["examples"].append(group.get("full_command_line")
                                     or group.get("executable") or group.get("process_name"))
    return sorted(tally.values(), key=lambda entry: -entry["records"])


def summarize_routine(groups) -> dict:
    """Ordinary activity, counted rather than printed."""
    routine = [group for group in groups
               if group["classification"]["category"] == NOT_HARMFUL
               and group["classification"]["investigator_priority"] == PRIORITY_3]
    examples = []
    for group in routine:
        name = group.get("process_name") or group.get("executable") or group.get("full_command_line")
        if name and name not in examples and len(examples) < 12:
            examples.append(name)
    return {
        "activities": len(routine),
        "records": sum(group["occurrences"] for group in routine),
        "examples": examples,
        "note": ("No additional suspicious evidence was associated with these activities. Every "
                 "record remains in the appendices and in the investigation database."),
    }


def _descending(stamp):
    """Sort newest first without reversing the rest of the key."""
    if not stamp:
        return ""
    return "".join(chr(0x10FFFD - ord(char)) if ord(char) < 0x10FFFD else char for char in stamp)


def summarize_groups(groups) -> dict:
    """Triage counts over records, not groups: 87 routine runs are 87 records."""
    record_counts, group_counts = {}, {}
    priority_records, priority_groups = {}, {}
    for group in groups:
        category = group["classification"]["category"]
        priority = group["classification"]["investigator_priority"]
        record_counts[category] = record_counts.get(category, 0) + group["occurrences"]
        group_counts[category] = group_counts.get(category, 0) + 1
        priority_records[priority] = priority_records.get(priority, 0) + group["occurrences"]
        priority_groups[priority] = priority_groups.get(priority, 0) + 1
    summary = summarize([group["classification"] for group in groups])
    summary["counts"] = {key: record_counts.get(key, 0) for key in summary["counts"]}
    summary["distinct_activity"] = {key: group_counts.get(key, 0) for key in summary["counts"]}
    summary["priorities"] = {key: priority_records.get(key, 0) for key in summary["priorities"]}
    summary["distinct_by_priority"] = {key: priority_groups.get(key, 0)
                                       for key in summary["priorities"]}
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


#: Signals that describe *why* something is concerning, as opposed to how well
#: it is corroborated. Two activities showing the same concern for the same
#: reason are one lead, however many times the operator typed it.
_PATTERN_SIGNALS = (
    "remote_content_to_interpreter", "download_to_writable_location",
    "encoded_powershell", "execution_from_writable_location",
    "image_absent_after_execution", "installer_shaped_source",
)

_PATTERN_TITLES = {
    "remote_content_to_interpreter": "Remote content piped into an interpreter",
    "download_to_writable_location": "Downloads written to a writable location",
    "encoded_powershell": "PowerShell invoked with an encoded command",
    "execution_from_writable_location": "Execution from a writable or temporary location",
    "image_absent_after_execution": "Executed image no longer present",
}


def build_leads(ranked) -> list[dict]:
    """The top leads, with repetitions of one pattern shown once.

    Five vendor install commands are one lead about one behaviour, not five
    investigations. Each individual command, with its own evidence identifier,
    stays inside the lead and in the evidence package.
    """
    candidates = [group for group in ranked
                  if group["classification"]["investigator_priority"] in {PRIORITY_1, PRIORITY_2}]
    patterns = {}
    for group in candidates:
        signature = (
            group["evidence_kind"],
            group["classification"]["investigator_priority"],
            tuple(sorted(signal["name"] for signal in group["classification"]["signals"]
                         if signal["name"] in _PATTERN_SIGNALS)),
        )
        patterns.setdefault(signature, []).append(group)

    leads = []
    for (kind, priority, signature), members in patterns.items():
        first = members[0]["classification"]
        title = next((_PATTERN_TITLES[name] for name in signature if name in _PATTERN_TITLES),
                     "Activity requiring attention")
        context = [signal["detail"] for signal in members[0]["classification"]["signals"]
                   if signal["name"] == "installer_shaped_source"]
        references, commands = [], []
        for member in members:
            for record in member["records"]:
                if record.get("reference"):
                    references.append(record["reference"])
            command = (member.get("full_command_line") or member.get("executable")
                       or member.get("process_name"))
            if command and command not in commands:
                commands.append(command)
        leads.append({
            "lead_id": None,
            "title": title,
            "pattern": list(signature),
            "evidence_kind": kind,
            "priority": priority,
            "priority_label": PRIORITY_LABELS[priority],
            "classification": first["category"],
            "activity_count": len(members),
            "record_count": sum(member["occurrences"] for member in members),
            "commands": commands,
            "execution_confirmed": any(member["execution_confirmed"] for member in members),
            "why": [signal["detail"] for signal in first["signals"] if signal["weight"] > 0],
            "context": context,
            "unknowns": first.get("unknowns", []),
            "limitations": first.get("limitations", []),
            "recommended_action": first.get("recommended_action"),
            "evidence_references": references[:120],
            "first_seen": min((member["first_seen"] for member in members
                               if member["first_seen"]), default=None),
            "last_seen": max((member["last_seen"] for member in members
                              if member["last_seen"]), default=None),
            "groups": members,
        })

    leads.sort(key=lambda lead: (PRIORITY_ORDER[lead["priority"]], -lead["record_count"]))
    for index, lead in enumerate(leads[:MAX_LEADS], start=1):
        lead["lead_id"] = f"LEAD-{index:03d}"
    return leads[:MAX_LEADS]


#: Grouping for the routine activity report. Printing eleven hundred identical
#: version checks is not a record; it is a way of ensuring nobody reads one.
MAX_ROUTINE_GROUPS = 120
MAX_ROUTINE_COMMANDS = 60


def _routine_key(group):
    """What makes two routine activities the same kind of thing.

    Recognized software groups by what it is. Everything else groups by the
    reason triage called it routine, which is the sentence an investigator will
    read anyway.
    """
    classification = group.get("classification") or {}
    records = group.get("records") or []
    recognition = next((record.get("recognition") for record in records
                        if (record.get("recognition") or {}).get("recognized")), None)
    if recognition:
        name = recognition.get("recognized_name")
        version = recognition.get("version")
        return (f"{name}{' ' + version if version else ''}",
                "Accounted for by " + ", ".join(recognition.get("basis_codes") or ["recognition"])
                + ".")
    for signal in classification.get("signals") or []:
        if signal.get("name") == "routine_command":
            return signal["detail"].removeprefix("Recognised as ").rstrip("."), signal["detail"]
        if signal.get("name") == "managed_system_service":
            return "managed system services", signal["detail"]
    if classification.get("signals"):
        for signal in classification["signals"]:
            if signal.get("name") == "system_location":
                return "operating-system images in system directories", signal["detail"]
    return "other routine activity", classification.get("reason") or "No concern signal was raised."


def build_routine(activity, *, presentation="ROUTINE_RECOGNIZED") -> dict:
    """Group everything presented as routine, for the separate routine report.

    Returns groups rather than rows. The evidence identifiers travel with each
    group so a reader can still reach any individual record.
    """
    groups = activity.get("groups") or []
    routine = [group for group in groups
               if (group.get("classification") or {}).get("presentation") == presentation]

    buckets = {}
    for group in routine:
        label, basis = _routine_key(group)
        bucket = buckets.setdefault(label, {
            "label": label, "basis": basis, "activities": 0, "occurrences": 0,
            "commands": [], "evidence_references": [],
        })
        bucket["activities"] += 1
        bucket["occurrences"] += group.get("occurrences", len(group.get("records") or []))
        command = (group.get("full_command_line") or group.get("executable")
                   or group.get("process_name"))
        if command and command not in bucket["commands"]:
            bucket["commands"].append(command)
        for record in group.get("records") or []:
            if record.get("reference"):
                bucket["evidence_references"].append(record["reference"])

    ordered = sorted(buckets.values(), key=lambda bucket: (-bucket["occurrences"], bucket["label"]))
    for bucket in ordered:
        bucket["commands"] = bucket["commands"][:MAX_ROUTINE_COMMANDS]

    return {
        "groups": ordered[:MAX_ROUTINE_GROUPS],
        "group_count": len(ordered),
        "totals": {
            "activities": len(routine),
            "records": sum(bucket["occurrences"] for bucket in buckets.values()),
            "all_activities": len(groups),
            "excluded": len(groups) - len(routine),
        },
        "note": ("Routine / recognized means the machine's own records account for this activity "
                 "and nothing in the collected evidence raised a concern. It is not a guarantee "
                 "of safety."),
    }
