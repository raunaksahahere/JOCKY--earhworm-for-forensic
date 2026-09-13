"""
Conservative correlation between execution evidence and collected artifacts.

Every finding produced here names the evidence it rests on and states how
strongly it is supported. Nothing in this module decides that something is
malware: a name, an extension or a directory is a reason for an analyst to
look, never a verdict. Findings that describe a gap in the evidence -- missing
telemetry, truncation, permission failures -- matter as much as findings about
activity, because an investigator needs to know what could not be seen.
"""

from __future__ import annotations

import os

from .execution_model import AVAILABLE, NOT_AVAILABLE, NOT_ENABLED, PERMISSION_DENIED

INFO, LOW, MEDIUM, HIGH = "info", "low", "medium", "high"

# How well the evidence supports the statement, kept separate from severity.
CORROBORATED = "corroborated by more than one source"
SINGLE_SOURCE = "single source; not corroborated"
OBSERVED_DIRECTLY = "directly observed by the collector"
QUALIFIED = "qualified: the underlying source has known limits"


def _finding(category, severity, title, explanation, *, confidence, classification, references):
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "confidence": confidence,
        "classification": classification,
        "evidence_references": references,
    }


def _reference(kind, identifier, **extra):
    return {"kind": kind, "id": identifier, **extra}


def correlate(*, execution=None, artifacts=None, processes=None):
    """Produce findings from the collected evidence.

    Returns a list of findings and a correlation summary linking execution
    events to the artifacts they name.
    """
    execution = execution or {}
    artifacts = artifacts or {}
    events = execution.get("events", []) or []
    records = artifacts.get("artifacts", []) or []
    by_path = {record["path"]: record for record in records}

    findings, links = [], []
    sources_by_event = {}
    for event in events:
        path = event.get("executable")
        if path and os.path.isabs(path):
            sources_by_event.setdefault(path, set()).add(event.get("source"))

    findings.extend(_artifact_findings(events, by_path, sources_by_event, links))
    findings.extend(_indicator_findings(records))
    findings.extend(_integrity_findings(records))
    findings.extend(_telemetry_findings(execution))
    findings.extend(_completeness_findings(execution, artifacts, processes or {}))

    return {
        "findings": findings,
        "links": links,
        "statistics": {
            "findings_by_severity": _count(findings, "severity"),
            "findings_by_category": _count(findings, "category"),
            "execution_events_with_artifact": sum(1 for link in links if link["artifact_present"]),
            "execution_events_without_artifact": sum(1 for link in links if not link["artifact_present"]),
        },
    }


def _count(items, key):
    counts = {}
    for item in items:
        counts[item[key]] = counts.get(item[key], 0) + 1
    return counts


def _artifact_findings(events, by_path, sources_by_event, links):
    """Relate each execution event to the artifact it names."""
    findings, reported_missing, reported_location, reported_match = [], set(), set(), set()
    for event in events:
        path = event.get("executable")
        if not path or not os.path.isabs(path):
            continue
        record = by_path.get(os.path.abspath(path))
        present = bool(record and record["collection_status"] == "COLLECTED")
        links.append({
            "execution_event_id": event.get("event_id"),
            "source": event.get("source"),
            "executable": path,
            "artifact_present": present,
            "artifact_hash": record["hash"] if record else None,
            "timestamp": event.get("timestamp"),
        })
        corroboration = CORROBORATED if len(sources_by_event.get(path, ())) > 1 else SINGLE_SOURCE

        if record and record["collection_status"] == "MISSING" and path not in reported_missing:
            reported_missing.add(path)
            findings.append(_finding(
                "execution_artifact_missing", MEDIUM,
                f"Execution evidence names an executable that is no longer present: {os.path.basename(path)}",
                (f"{event.get('source')} recorded execution activity for {path}, but no file exists at that "
                 "path at collection time. This is expected after a package upgrade, an uninstall or a "
                 "temporary file being cleaned up, and it is also what removal of a program after use looks "
                 "like. The record alone does not distinguish between them."),
                confidence=corroboration, classification="INFERRED",
                references=[_reference("execution_event", event.get("event_id"), source=event.get("source")),
                            _reference("artifact", path, collection_status="MISSING")],
            ))

        if record and record.get("notable_location") and path not in reported_location:
            reported_location.add(path)
            findings.append(_finding(
                "unusual_execution_location", MEDIUM,
                f"Execution from a writable or temporary location: {os.path.basename(path)}",
                (f"{path} sits under '{record['notable_location']}', a location that is writable by "
                 "unprivileged users and commonly used for staging. Legitimate installers, updaters and "
                 "build tools also run from these directories, so this is a reason to inspect the artifact, "
                 "not a conclusion about it."),
                confidence=OBSERVED_DIRECTLY, classification="INFERRED",
                references=[_reference("execution_event", event.get("event_id"), source=event.get("source")),
                            _reference("artifact", path, hash=record.get("hash"))],
            ))

        if present and record.get("hash") and path not in reported_match:
            reported_match.add(path)
            findings.append(_finding(
                "execution_artifact_matched", INFO,
                f"Execution evidence corroborated by a present artifact: {os.path.basename(path)}",
                (f"{event.get('source')} names {path}, and a file exists there whose "
                 f"{record['hash_algorithm']} digest is {record['hash']}. The digest records the bytes "
                 "present now; it does not prove these are the bytes that ran."),
                confidence=corroboration, classification="OBSERVED",
                references=[_reference("execution_event", event.get("event_id"), source=event.get("source")),
                            _reference("artifact", path, hash=record.get("hash"))],
            ))
    return findings


def _indicator_findings(records):
    findings = []
    for record in records:
        for indicator in record.get("indicators") or []:
            findings.append(_finding(
                "suspicious_filename", MEDIUM if indicator.get("level") == "warning" else INFO,
                f"{indicator['label']}: {record['filename']}",
                (f"{indicator['detail']} This is a static naming heuristic applied to {record['path']}. "
                 "It describes the name only and is not a statement about the file's behaviour."),
                confidence=OBSERVED_DIRECTLY, classification="INFERRED",
                references=[_reference("artifact", record["path"], hash=record.get("hash"))],
            ))
    return findings


def _integrity_findings(records):
    findings = []
    for record in records:
        history = record.get("integrity_history") or {}
        if history.get("status") == "altered":
            findings.append(_finding(
                "artifact_hash_changed", HIGH,
                f"Artifact changed since JOCKY last hashed it: {record['filename']}",
                (f"{record['path']} now digests to {record.get('hash')}, which differs from the digest "
                 "recorded in this workstation's hash ledger. The change is established; its cause is not. "
                 "Routine updates produce the same result as tampering."),
                confidence=OBSERVED_DIRECTLY, classification="OBSERVED",
                references=[_reference("artifact", record["path"], hash=record.get("hash"),
                                       previous_hash=(record.get("previous_hash") or {}).get("hash"))],
            ))
        integrity = record.get("integrity") or {}
        if integrity.get("status") in {"warning", "critical"}:
            findings.append(_finding(
                "integrity_anomaly", MEDIUM if integrity["status"] == "warning" else HIGH,
                f"Structural integrity check reported {integrity['status']}: {record['filename']}",
                (f"{integrity.get('detail') or integrity.get('message') or 'The structural check did not pass.'} "
                 f"This inspects {record['path']} against the expected container format only."),
                confidence=OBSERVED_DIRECTLY, classification="OBSERVED",
                references=[_reference("artifact", record["path"], hash=record.get("hash"))],
            ))
    return findings


def _telemetry_findings(execution):
    """A source that could not be read is itself a reportable fact."""
    findings = []
    for source in execution.get("sources", []) or []:
        if source["status"] == AVAILABLE:
            continue
        severity = {
            NOT_ENABLED: LOW, NOT_AVAILABLE: LOW, PERMISSION_DENIED: MEDIUM,
        }.get(source["status"], LOW)
        findings.append(_finding(
            "telemetry_unavailable", severity,
            f"Historical execution source unavailable: {source['name']} ({source['status']})",
            (f"{source['detail']} Any activity that only this source would have recorded is outside "
             "the evidence available to this investigation."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("telemetry_source", source["name"], status=source["status"],
                                   location=source.get("location"))],
        ))
    if not execution.get("telemetry_available", False):
        findings.append(_finding(
            "no_historical_telemetry", HIGH,
            "No historical execution telemetry was available on this host",
            ("Every historical source JOCKY supports on this platform was unavailable, not enabled, or not "
             "readable. The investigation can describe what is running now, but cannot establish what ran "
             "before collection started."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("telemetry_source", source["name"], status=source["status"])
                        for source in execution.get("sources", []) or []],
        ))
    return findings


def _completeness_findings(execution, artifacts, processes):
    findings = []
    if execution.get("truncated"):
        findings.append(_finding(
            "collection_truncated", MEDIUM,
            "Historical execution collection was truncated",
            (f"Collection stopped at its configured bounds ({execution.get('limits', {})}). Events outside "
             "those bounds were not read and are absent from this report."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("collection", "execution_history")],
        ))
    undated = execution.get("undated_event_count") or 0
    if undated:
        findings.append(_finding(
            "undated_evidence", LOW,
            f"{undated} execution records carry no timestamp",
            ("Their source does not record a per-entry time, so they cannot be placed on the timeline or "
             "bounded to the collection window. They are ordered last and must not be read as recent."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("collection", "execution_history")],
        ))
    if artifacts.get("truncated"):
        findings.append(_finding(
            "collection_truncated", MEDIUM,
            "Artifact collection was truncated",
            (f"The artifact bound of {artifacts.get('limits', {}).get('max_artifacts')} was reached; further "
             "candidate artifacts named by the evidence were not observed."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("collection", "artifact_collection")],
        ))
    denied = (artifacts.get("statistics", {}).get("by_collection_status", {}) or {}).get("PERMISSION_DENIED")
    if denied:
        findings.append(_finding(
            "permission_gap", MEDIUM,
            f"{denied} artifacts could not be read",
            ("The collector did not hold sufficient privileges for these paths. Their contents were not "
             "hashed and no statement is made about them."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("collection", "artifact_collection")],
        ))
    if processes.get("truncated"):
        findings.append(_finding(
            "collection_truncated", LOW,
            "Current process snapshot was truncated",
            (f"The snapshot stopped at {processes.get('limits', {}).get('max_processes')} processes. "
             "Processes beyond that bound were running but were not recorded."),
            confidence=OBSERVED_DIRECTLY, classification="UNAVAILABLE",
            references=[_reference("collection", "process_snapshot")],
        ))
    return findings
