"""
The exported evidence package, and the manifest that makes it self-describing.

An evidence package is useless to the next investigator if they cannot tell what
it contains, when it was collected, by which version, from which host, and what
was done to it along the way. So the package carries a manifest answering
exactly those questions, and a digest of every file in it so the package can be
checked as a whole rather than trusted as a whole.

The manifest is not a summary of the findings. It is a description of the
evidence and its handling, which is the part that has to survive being read by
someone who was not there.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

from backend.storage import now
from backend.versions import versions

PACKAGE_VERSION = 2

MANIFEST_NAME = "MANIFEST.json"
README_NAME = "README.txt"

README = """JOCKY EVIDENCE PACKAGE
======================

This archive is the complete structured record of one investigation. Nothing was
removed from it to shorten the investigator report; the report is a presentation
of what is here.

  MANIFEST.json            what this package contains, and the digest of every
                           file in it
  investigator-report.pdf  the concise report an investigator reads
  full-report.pdf          the same report with every appendix appended
  report.json              the complete report payload

  evidence/
    command-history.json   every command-history record, in full
    execution.json         every execution record, normalized
    activity.json          every reconstructed activity with its triage
    processes.json         the process listing as collected
    artifacts.json         every hashed artifact with its recognition result
    findings.json          every finding with the evidence it cites
    threads.json           every activity thread, printed or not
    timeline.json          the merged timeline
    telemetry-sources.json which sources were read, and which were not
    limitations.json       what could not be collected, and why
    recognition.json       what the machine could account for
    browser.json           browser history and download records
    usb.json               removable media identity, events and mounts
    network.json           interfaces, routes, resolver and the socket table
    drivers.json           loaded drivers and their reference verification
    memory.json            memory analysis, with its provenance
    services.json          service units and scheduled jobs

  provenance/
    evidence-sources.json  registered sources, digests and integrity history
    endpoints.json         the endpoints this evidence came from
    audit-trail.json       what JOCKY and the investigator did
    programs.json          the investigation program, its IR and the plan
    investigation.json     state history and execution records

  analysis/
    case-summary.json      the generated conclusion, with the evidence behind
                           each sentence
    narrative.json         the same statements as stored rows, for auditing
    routine-activity.json  activity presented as routine or recognized

  briefs/                  any review briefs generated for this investigation

WHAT THE DIGESTS MEAN

Each entry in MANIFEST.json carries the SHA-256 of that file as written. Verify
one with:

    sha256sum <file>

and compare it against the manifest. A digest that matches shows the file is
the one JOCKY wrote. It does not establish anything about the machine that was
examined -- for that, read the evidence itself.

WHAT IS NOT IN HERE

The routine activity report and any review briefs are separate documents, each
produced on request. They contain nothing this package does not: a brief is one
subject's evidence rearranged, and the routine report is a grouping of activity
whose records are all in evidence/activity.json.

WHAT THIS PACKAGE IS NOT

It is not a verdict. Findings state what the evidence supports and what it does
not. Activity marked routine or recognized produced no concern signal in the
collected evidence, which is not a guarantee of safety. The collection
limitations recorded in report.json bound what any conclusion can cover.
"""


def _collector_versions(report) -> dict:
    """The version each collector recorded when it ran.

    Read back from the evidence rather than assumed: a package assembled from a
    database written by an older build should say so.
    """
    collected = {}
    for record in report.get("evidence") or []:
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("versions"):
            collected[record.get("type")] = payload["versions"]
    for record in report.get("executions") or []:
        if record.get("versions"):
            collected.setdefault(record.get("command"), record["versions"])
    return collected


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _dump(value) -> bytes:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False).encode("utf-8")


def build_manifest(*, report, files, case=None, endpoints=(), evidence_sources=(),
                   programs=(), audit_events=()) -> dict:
    """Everything a reader needs to know about the package before opening it.

    Written for someone who was not there: which case, which host, over what
    period, by which version of what, and whether the bytes are the ones JOCKY
    wrote.
    """
    investigation = report.get("investigation") or {}
    execution = report.get("historical_execution") or {}
    recognition = report.get("recognition") or {}
    window = report.get("collection_window") or {}
    from analysis.detections import DETECTION_RULESET_VERSION
    from compiler.investigation import IR_VERSION
    from compiler.plan import PLAN_VERSION
    return {
        "package_version": PACKAGE_VERSION,
        "exported_at": now(),
        "case": {
            "id": (case or {}).get("id") or investigation.get("case_id"),
            "title": (case or {}).get("title"),
            "examiner": (case or {}).get("examiner"),
            "reference": (case or {}).get("reference"),
        },
        "investigation": {
            "id": report.get("investigation_id"),
            "title": investigation.get("title"),
            "status": report.get("status"),
            "started_at": investigation.get("started_at"),
            "completed_at": investigation.get("completed_at"),
            "collection_window": report.get("collection_window"),
        },
        "report": {
            "id": report.get("report_id"),
            "schema_version": report.get("schema_version"),
            "created_at": report.get("created_at"),
        },
        "collection_period": {
            "start": window.get("start"),
            "end": window.get("end"),
            "requested_hours": window.get("requested_hours"),
            "maximum_hours": window.get("maximum_hours"),
            "bounded": window.get("bounded"),
            "detail": ("Historical collection was bounded to this window. Activity outside it was "
                       "not collected and nothing here describes it."
                       if window.get("bounded") else
                       "No collection window was recorded for this investigation."),
        },
        "versions": {
            **(report.get("versions") or versions()),
            "package": PACKAGE_VERSION,
            "recognition": recognition.get("recognition_version"),
            "ir": IR_VERSION,
            "plan": PLAN_VERSION,
            "detection_ruleset": DETECTION_RULESET_VERSION,
        },
        "collectors": {
            "platform": execution.get("platform"),
            # Each collector names itself and its own version in the evidence it
            # produced, so which code read what is answerable from the package
            # rather than inferred from the application version.
            "versions": _collector_versions(report),
            "sources": [{"name": source.get("name"), "status": source.get("status"),
                         "detail": source.get("detail"),
                         "records": source.get("event_count")}
                        for source in execution.get("sources") or []],
        },
        "programs": [
            {"id": program.get("id"), "platform": program.get("platform"),
             "ir_version": program.get("ir_version"), "plan_version": program.get("plan_version"),
             "created_at": program.get("created_at"), "source": program.get("source")}
            for program in programs
        ],
        "endpoints": [
            {"id": endpoint.get("id"), "name": endpoint.get("name"),
             "hostname": endpoint.get("hostname"), "platform": endpoint.get("platform"),
             "agent_version": endpoint.get("agent_version"),
             "authorization_reference": endpoint.get("authorization_reference"),
             "enrolled_at": endpoint.get("enrolled_at")}
            for endpoint in endpoints
        ],
        "evidence_sources": [
            {"id": source.get("id"), "reference": source.get("reference"),
             "source_type": source.get("source_type"), "sha256": source.get("sha256"),
             "size_bytes": source.get("size_bytes"), "acquired_at": source.get("acquired_at"),
             "registered_at": source.get("registered_at"),
             "acquisition_status": source.get("acquisition_status"),
             "verification_state": source.get("verification_state"),
             "processing_status": source.get("processing_status"),
             "supersedes": source.get("supersedes"),
             "collector": source.get("collector"),
             "integrity_events": len(source.get("integrity_events") or [])}
            for source in evidence_sources
        ],
        "evidence_source_ids": [source.get("id") for source in evidence_sources],
        "record_counts": report.get("record_counts") or {},
        "audit_event_count": len(audit_events),
        "files": files,
        "provenance": (
            "Evidence in this package was collected by JOCKY from the endpoints named above, "
            "normalized into one evidence model, and written here without alteration. Where a "
            "record was derived rather than observed, the record itself says so."),
        "integrity": (
            "Each file's SHA-256 is recorded above as written. A matching digest shows the file is "
            "the one JOCKY wrote; it establishes nothing about the examined machine."),
        "not_a_verdict": (
            "This package is a record of collected evidence. It is not a verdict, and the absence "
            "of a finding is not evidence that nothing happened."),
    }


def build_package(*, report, pdf=None, full_pdf=None, case=None, endpoints=(),
                  evidence_sources=(), programs=(), audit_events=(), routine=None,
                  case_summary=None, narrative=(), briefs=()) -> bytes:
    """Assemble the archive, hashing each member as it is written.

    This is where everything the investigator report does not print has to be,
    which is the only reason that report can be eight pages. Every source the
    collection read gets its own file, so following an evidence identifier means
    opening one file rather than searching a single enormous payload.
    """
    activity = report.get("activity") or {}
    groups = activity.get("groups") or []
    supplementary = report.get("supplementary") or {}
    history = report.get("historical_execution") or {}

    def kind(name):
        return [group for group in groups if group.get("evidence_kind") == name]

    members = {
        "report.json": _dump(report),

        # The evidence, split by source. A record is easier to find in the file
        # named after the thing that collected it.
        "evidence/command-history.json": _dump(kind("COMMAND_HISTORY")),
        "evidence/execution.json": _dump(history.get("events") or kind("EXECUTION_EVIDENCE")),
        "evidence/activity.json": _dump(activity),
        "evidence/processes.json": _dump(report.get("appendix_process_listing")
                                         or report.get("current_process_snapshot") or []),
        "evidence/artifacts.json": _dump(report.get("artifacts") or []),
        "evidence/findings.json": _dump(report.get("findings") or []),
        "evidence/threads.json": _dump(report.get("threads") or []),
        "evidence/timeline.json": _dump(report.get("event_timeline")
                                        or report.get("timeline") or []),
        "evidence/telemetry-sources.json": _dump(history.get("sources") or []),
        "evidence/limitations.json": _dump(report.get("collection_limitations")
                                           or report.get("limitations") or []),
        "evidence/recognition.json": _dump(report.get("recognition") or {}),

        "provenance/evidence-sources.json": _dump(list(evidence_sources)),
        "provenance/endpoints.json": _dump(list(endpoints)),
        "provenance/audit-trail.json": _dump(list(audit_events)),
        "provenance/programs.json": _dump(list(programs)),
        "provenance/investigation.json": _dump({
            "investigation": report.get("investigation"),
            "state_history": report.get("timeline") or [],
            "executions": report.get("executions") or [],
            "evidence_records": report.get("evidence") or [],
            "provenance": report.get("provenance") or {},
        }),

        "analysis/routine-activity.json": _dump(routine or {}),
        "analysis/case-summary.json": _dump(case_summary or {}),
        "analysis/narrative.json": _dump(list(narrative)),

        README_NAME: README.encode("utf-8"),
    }

    # One file per program-selected source, named for the source, and only where
    # the collection actually ran it. An empty file would imply a collection
    # that did not happen.
    for source, filename in (("BROWSER", "browser"), ("USB", "usb"), ("NETWORK", "network"),
                             ("DRIVERS", "drivers"), ("MEMORY", "memory"),
                             ("SERVICES", "services")):
        payload = supplementary.get(source)
        if payload:
            members[f"evidence/{filename}.json"] = _dump(payload)

    if pdf:
        members["investigator-report.pdf"] = pdf
    if full_pdf:
        members["full-report.pdf"] = full_pdf
    for brief in briefs:
        payload = brief.get("payload") or brief
        subject = (payload.get("subject") or {}).get("id") or brief.get("id")
        members[f"briefs/JOCKY_ReviewBrief_{subject}.json"] = _dump(payload)

    files = [{"name": name, "bytes": len(data), "sha256": _digest(data)}
             for name, data in sorted(members.items())]
    manifest = build_manifest(report=report, files=files, case=case, endpoints=endpoints,
                              evidence_sources=evidence_sources, programs=programs,
                              audit_events=audit_events)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, _dump(manifest))
        for name, data in sorted(members.items()):
            archive.writestr(name, data)
    return buffer.getvalue()


def verify_package(payload: bytes) -> dict:
    """Re-hash every member and report any that no longer match the manifest."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
        expected = {entry["name"]: entry["sha256"] for entry in manifest.get("files", [])}
        observed, missing, mismatched = {}, [], []
        for name, digest in expected.items():
            try:
                actual = _digest(archive.read(name))
            except KeyError:
                missing.append(name)
                continue
            observed[name] = actual
            if actual != digest:
                mismatched.append(name)
    return {
        "package_version": manifest.get("package_version"),
        "files_checked": len(observed),
        "missing": missing,
        "mismatched": mismatched,
        "verified": not missing and not mismatched,
        "detail": ("Every file matches the digest recorded in the manifest."
                   if not missing and not mismatched else
                   "The package does not match its manifest; it has been altered since export."),
    }
