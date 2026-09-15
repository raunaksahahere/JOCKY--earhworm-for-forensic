"""
What a program's FILTER statements select from what was collected.

A FILTER is the question the investigation asked. This is where that question
gets answered against the evidence, after collection rather than during it:
evidence is registered and hashed whole, and a selection is a view over it. Run
the same program twice against the same evidence and the same records come back,
which is the property that makes a filtered result quotable in a report.

Nothing here removes, rewrites or re-hashes a record. A selection that comes
back empty means the evidence does not answer the question -- not that the
evidence is gone.
"""

from __future__ import annotations

from compiler.predicate import evaluate

MAX_PER_KIND = 200


def _reference(group):
    for record in group.get("records") or []:
        if record.get("reference"):
            return record["reference"]
    return None


def _label(group):
    return (group.get("full_command_line") or group.get("executable")
            or group.get("process_name") or "activity record")


def select_for_program(report: dict, filters) -> dict:
    """Apply a compiled program's filters to one investigation's report.

    `filters` are IR filter clauses. Several narrow together: each is a further
    condition on the same question, the way consecutive statements read.
    """
    clauses = [clause["predicate"] for clause in filters or []]
    if not clauses:
        return {"applied": False, "filters": [], "results": [], "counts": {}, "total": 0,
                "note": "This investigation's program declares no FILTER, so nothing is narrowed."}

    def keeps(record):
        return all(evaluate(predicate, record) for predicate in clauses)

    results = []

    def add(kind, identifier, label, record, extra=None):
        if len(results) < MAX_PER_KIND * 8 and keeps(record):
            results.append({"kind": kind, "id": identifier, "label": label, **(extra or {})})

    activity = report.get("activity") or {}
    for group in activity.get("groups") or []:
        classification = group.get("classification") or {}
        add("activity", _reference(group), _label(group), group, {
            "presentation": classification.get("presentation_label"),
            "priority": classification.get("priority_label"),
            "occurrences": group.get("occurrences"),
        })

    for record in report.get("artifacts") or []:
        add("artifact", record.get("reference"), record.get("path"), record,
            {"sha256": record.get("hash")})

    supplementary = report.get("supplementary") or {}
    browser = supplementary.get("BROWSER") or {}
    for record in browser.get("downloads") or []:
        add("browser download", record.get("url"),
            record.get("target_path") or record.get("url"), record)
    for record in browser.get("history") or []:
        add("browser history", record.get("url"), record.get("title") or record.get("url"), record)

    for record in (supplementary.get("NETWORK") or {}).get("connections") or []:
        add("network", record.get("remote_address"),
            f"{record.get('process_name') or 'unknown process'} -> "
            f"{record.get('remote_address')}", record)

    counts = {}
    for result in results:
        counts[result["kind"]] = counts.get(result["kind"], 0) + 1

    from compiler.predicate import explain
    return {
        "applied": True,
        "filters": explain(filters),
        "results": results,
        "counts": counts,
        "total": len(results),
        "note": ("A selection is a view over evidence that was registered and hashed in full. "
                 "No record was removed, rewritten or re-hashed to produce it."),
    }
