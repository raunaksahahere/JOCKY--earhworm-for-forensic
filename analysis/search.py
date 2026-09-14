"""
Search across everything one investigation holds.

The old search matched an activity's command text. That found `flutter` in a
command and missed the Flutter archive sitting in the artifact list, the thread
that tied them together and the finding that cited both -- which is the search
an investigator actually wanted.

So this searches every stored surface and says which one matched. A result
without its reason is a list of identifiers; with it, an investigator can see at
a glance that "flutter" matched a recognized name here and a URL there.
"""

from __future__ import annotations

MAX_RESULTS_PER_KIND = 200
MIN_TERM_LENGTH = 2

#: What each surface contributes to the haystack, and the name of the field so
#: a match can say where it was found.
ACTIVITY_FIELDS = (
    ("command", lambda group: group.get("full_command_line")),
    ("normalized command", lambda group: group.get("normalized_command")),
    ("executable", lambda group: group.get("executable")),
    ("process name", lambda group: group.get("process_name")),
    ("evidence kind", lambda group: group.get("evidence_kind")),
    ("classification", lambda group: (group.get("classification") or {}).get("category")),
    ("presentation", lambda group: (group.get("classification") or {}).get("presentation")),
    ("priority", lambda group: (group.get("classification") or {}).get("investigator_priority")),
    ("source", lambda group: " ".join(group.get("sources") or ())),
    ("user", lambda group: " ".join(str(record.get("user") or "")
                                    for record in group.get("records") or ())),
    ("evidence id", lambda group: " ".join(str(record.get("reference") or "")
                                           for record in group.get("records") or ())),
    ("recognized software", lambda group: " ".join(
        str((record.get("recognition") or {}).get("recognized_name") or "")
        for record in group.get("records") or ())),
    ("endpoint", lambda group: group.get("endpoint")),
)

ARTIFACT_FIELDS = (
    ("path", lambda record: record.get("path")),
    ("filename", lambda record: record.get("filename")),
    ("sha256", lambda record: record.get("hash")),
    ("evidence id", lambda record: record.get("reference")),
    ("recognized software", lambda record: (record.get("recognition") or {}).get("recognized_name")),
    ("recognition version", lambda record: (record.get("recognition") or {}).get("version")),
    ("source", lambda record: record.get("source")),
    ("endpoint", lambda record: record.get("endpoint")),
)

FINDING_FIELDS = (
    ("title", lambda record: record.get("title")),
    ("explanation", lambda record: record.get("explanation")),
    ("category", lambda record: record.get("category")),
    ("evidence id", lambda record: record.get("reference")),
    ("cited evidence", lambda record: " ".join(
        str(item.get("id") or "") for item in record.get("evidence_references") or ())),
    ("triage", lambda record: record.get("triage")),
)

THREAD_FIELDS = (
    ("title", lambda record: record.get("title")),
    ("why", lambda record: record.get("why")),
    ("command", lambda record: " ".join(record.get("commands") or ())),
    ("shared term", lambda record: " ".join(record.get("shared_terms") or ())),
    ("evidence id", lambda record: " ".join(record.get("evidence_references") or ())),
    ("thread", lambda record: record.get("thread_id")),
)

BROWSER_FIELDS = (
    ("url", lambda record: record.get("url")),
    ("download path", lambda record: record.get("target_path")),
    ("title", lambda record: record.get("title")),
    ("profile", lambda record: record.get("profile")),
)

NETWORK_FIELDS = (
    ("remote address", lambda record: record.get("remote_address")),
    ("process name", lambda record: record.get("process_name")),
    ("status", lambda record: record.get("status")),
)

SOURCE_FIELDS = (
    ("reference", lambda record: record.get("reference")),
    ("path", lambda record: record.get("original_path")),
    ("sha256", lambda record: record.get("sha256")),
    ("evidence id", lambda record: record.get("id")),
    ("description", lambda record: record.get("description")),
    ("endpoint", lambda record: record.get("endpoint")),
)


def _match(record, fields, needle):
    """Which named fields of one record contain the term."""
    matched = []
    for name, read in fields:
        try:
            value = read(record)
        except (AttributeError, TypeError):
            continue
        if value and needle in str(value).lower():
            matched.append(name)
    return matched


def _label(group):
    return (group.get("full_command_line") or group.get("executable")
            or group.get("process_name") or "activity record")


def search(report, term, *, kinds=None) -> dict:
    """Everything in one investigation that mentions `term`.

    Each hit says which field matched, so a result list is readable without
    opening every record in it.
    """
    needle = (term or "").strip().lower()
    if len(needle) < MIN_TERM_LENGTH:
        return {"term": term, "results": [], "counts": {},
                "note": f"A search term needs at least {MIN_TERM_LENGTH} characters."}

    wanted = set(kinds) if kinds else None
    results = []

    def add(kind, identifier, label, matched, extra=None):
        if matched and (wanted is None or kind in wanted):
            results.append({"kind": kind, "id": identifier, "label": label,
                            "matched_fields": matched, **(extra or {})})

    activity = report.get("activity") or {}
    for group in (activity.get("groups") or [])[:MAX_RESULTS_PER_KIND * 10]:
        matched = _match(group, ACTIVITY_FIELDS, needle)
        reference = next((record.get("reference") for record in group.get("records") or []
                          if record.get("reference")), None)
        classification = group.get("classification") or {}
        add("activity", reference, _label(group), matched, {
            "presentation": classification.get("presentation_label"),
            "priority": classification.get("priority_label"),
            "occurrences": group.get("occurrences"),
        })

    for record in report.get("artifacts") or []:
        recognition = record.get("recognition") or {}
        add("artifact", record.get("reference"), record.get("path"),
            _match(record, ARTIFACT_FIELDS, needle),
            {"sha256": record.get("hash"), "recognized": recognition.get("recognized_name")})

    for record in report.get("findings") or []:
        add("finding", record.get("reference"), record.get("title"),
            _match(record, FINDING_FIELDS, needle), {"priority": record.get("investigator_priority")})

    for record in report.get("threads") or []:
        add("thread", record.get("thread_id"), record.get("title"),
            _match(record, THREAD_FIELDS, needle), {"activities": record.get("activity_count")})

    for record in report.get("leads") or []:
        matched = _match(record, (("title", lambda item: item.get("title")),
                                  ("command", lambda item: " ".join(item.get("commands") or ())),
                                  ("lead", lambda item: item.get("lead_id"))), needle)
        add("lead", record.get("lead_id"), record.get("title"), matched,
            {"priority": record.get("priority_label")})

    supplementary = report.get("supplementary") or {}
    for record in (supplementary.get("BROWSER") or {}).get("downloads") or []:
        add("browser download", record.get("url"), record.get("target_path") or record.get("url"),
            _match(record, BROWSER_FIELDS, needle))
    for record in (supplementary.get("BROWSER") or {}).get("history") or []:
        add("browser history", record.get("url"), record.get("title") or record.get("url"),
            _match(record, BROWSER_FIELDS, needle))
    for record in (supplementary.get("NETWORK") or {}).get("connections") or []:
        add("network", record.get("remote_address"),
            f"{record.get('process_name') or 'unknown process'} -> {record.get('remote_address')}",
            _match(record, NETWORK_FIELDS, needle))

    for record in report.get("evidence_sources") or []:
        add("evidence source", record.get("id"), record.get("original_path") or record.get("reference"),
            _match(record, SOURCE_FIELDS, needle), {"sha256": record.get("sha256")})

    for record in report.get("endpoints") or []:
        matched = _match(record, (("endpoint", lambda item: item.get("name")),
                                  ("hostname", lambda item: item.get("hostname")),
                                  ("endpoint id", lambda item: item.get("id"))), needle)
        add("endpoint", record.get("id"), record.get("name"), matched)

    counts = {}
    for result in results:
        counts[result["kind"]] = counts.get(result["kind"], 0) + 1

    return {
        "term": term,
        "results": results[:MAX_RESULTS_PER_KIND * len(counts or [1])],
        "counts": counts,
        "total": len(results),
        "note": ("Each result names the field that matched, so a term found in a URL is "
                 "distinguishable from the same term found in a filename."),
    }
