"""
Correlation between different kinds of source on one host.

Execution evidence says a program ran. A browser download record says a file
arrived. A USB record says a device was attached. Each is weak alone; together
they describe a sequence, and a sequence is what an investigator can act on.

The rule this module keeps is that a link is only ever a link. That a file was
downloaded and later ran is an ordering of two observations, and the report says
so in those words. It is emphatically not a statement that the download was
malicious, or that the two events were the same person's doing -- that is the
investigator's call, and the explanation says what would have to be checked to
make it.
"""

from __future__ import annotations

import os
from datetime import datetime

from .correlation import HIGH, LOW, MEDIUM, OBSERVED_DIRECTLY, SINGLE_SOURCE, _finding, _reference
from .triage import NEEDS_REVIEW, POTENTIALLY_HARMFUL

#: A download and an execution further apart than this are not treated as one
#: sequence. A day is generous on purpose: the interval is evidence about
#: proximity, not about intent, and a wider window would make every download on
#: a machine look related to every later run.
DOWNLOAD_TO_EXECUTION_HOURS = 24
MAX_LINKS = 25


def _moment(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _gap_hours(first, second):
    start, end = _moment(first), _moment(second)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600


def _paths_in(events):
    """Every filesystem path an execution event names, with its event."""
    seen = []
    for event in events or []:
        for value in (event.get("executable"), event.get("full_command_line"),
                      event.get("command_line")):
            if not value:
                continue
            for word in str(value).split():
                if word.startswith("/") and len(word) > 1:
                    seen.append((word, event))
    return seen


def correlate_downloads(*, execution=None, artifacts=None, browser=None) -> list:
    """Downloads that later appear as an artifact or in execution evidence."""
    downloads = (browser or {}).get("downloads") or []
    if not downloads:
        return []
    events = (execution or {}).get("events") or []
    by_path = {record["path"]: record for record in (artifacts or {}).get("artifacts") or []}
    named = _paths_in(events)

    findings = []
    for download in downloads:
        target = download.get("target_path")
        if not target:
            continue
        artifact = by_path.get(target)
        executions = [event for path, event in named if path == target]
        if not artifact and not executions:
            continue

        event = executions[0] if executions else None
        gap = _gap_hours(download.get("started_at"), event.get("timestamp")) if event else None
        if gap is not None and gap > DOWNLOAD_TO_EXECUTION_HOURS:
            continue

        references = [_reference("browser_download", download.get("url") or target,
                                 path=target, downloaded_at=download.get("started_at"))]
        if artifact:
            references.append(_reference("artifact", artifact.get("reference") or target,
                                         path=target, sha256=artifact.get("hash")))
        if event:
            references.append(_reference("execution_event",
                                         event.get("reference") or event.get("event_id"),
                                         source=event.get("source")))

        if event:
            when = (f"about {gap:.1f} hours after" if gap and gap >= 1 else
                    f"about {int((gap or 0) * 60)} minutes after" if gap is not None else "after")
            title = f"A downloaded file was run: {os.path.basename(target)}"
            explanation = (
                f"{target} was recorded as a download from {download.get('url') or 'an unrecorded URL'} "
                f"and execution evidence names the same path {when} the download. Downloading a file "
                "and running it is ordinary on a workstation -- installers, scripts and tools all look "
                "like this. What makes the sequence worth reading is the source it came from and what "
                "the file does, neither of which this correlation establishes.")
            triage = POTENTIALLY_HARMFUL if event.get("execution_confirmed") else NEEDS_REVIEW
            severity = MEDIUM if event.get("execution_confirmed") else LOW
            action = ("Check the download source, then compare the artifact hash against a known "
                      "copy of whatever it claims to be.")
        else:
            title = f"A downloaded file is present on disk: {os.path.basename(target)}"
            explanation = (
                f"{target} was recorded as a download and a file exists at that path. Nothing in the "
                "collected evidence shows it running.")
            triage, severity = NEEDS_REVIEW, LOW
            action = "Check what the file is and whether anything has run it since collection."

        findings.append(_finding(
            "download_executed" if event else "download_present", severity, title, explanation,
            triage=triage, corroborated=bool(artifact and event),
            confidence=OBSERVED_DIRECTLY if (artifact and event) else SINGLE_SOURCE,
            classification="HISTORICAL_EVIDENCE", action=action,
            unknowns=("What the file does.",
                      "Whether the download and the execution were the same person's doing."),
            why=(f"{os.path.basename(target)} was downloaded and the same path appears in "
                 "execution evidence." if event else
                 f"{os.path.basename(target)} was downloaded and the file is still present."),
            references=references))
        if len(findings) >= MAX_LINKS:
            break
    return findings


def correlate_removable_media(*, execution=None, artifacts=None, usb=None) -> list:
    """Activity touching a removable device's mount point while it was attached."""
    usb = usb or {}
    mounts = usb.get("mounts") or []
    if not mounts:
        return []
    events = (execution or {}).get("events") or []
    records = (artifacts or {}).get("artifacts") or []
    attachments = [event for event in usb.get("events") or []
                   if event.get("action") == "connected"]

    findings = []
    for mount in mounts:
        point = mount.get("mount_point")
        if not point:
            continue
        touched = [(path, event) for path, event in _paths_in(events) if path.startswith(point + "/")]
        written = [record for record in records if record["path"].startswith(point + "/")]
        if not touched and not written:
            continue

        # A file with the same hash inside and outside the device is a copy,
        # which is the observation that matters for data leaving a machine.
        elsewhere = {record["path"]: record.get("hash") for record in records
                     if not record["path"].startswith(point + "/") and record.get("hash")}
        copies = [(record["path"], source) for record in written
                  for source, digest in elsewhere.items() if digest and digest == record.get("hash")]

        attached_at = attachments[0].get("timestamp") if attachments else None
        references = [_reference("removable_device",
                                 (mount.get("device") or point),
                                 mount_point=point,
                                 serial=(usb.get("devices") or [{}])[0].get("serial"))]
        for _path, event in touched[:5]:
            references.append(_reference("execution_event",
                                         event.get("reference") or event.get("event_id"),
                                         source=event.get("source")))
        for record in written[:5]:
            references.append(_reference("artifact", record.get("reference") or record["path"],
                                         path=record["path"], sha256=record.get("hash")))

        copy_text = ""
        if copies:
            pairs = "; ".join(f"{source} and {target}" for target, source in copies[:3])
            copy_text = (f" Files on the device share a hash with files elsewhere on this machine "
                         f"({pairs}), which is what copying produces.")

        findings.append(_finding(
            "removable_media_activity", HIGH if copies else MEDIUM,
            f"Activity involving removable media mounted at {point}",
            (f"A removable device was mounted at {point}"
             + (f", first attached at {attached_at}" if attached_at else "")
             + f". Execution evidence names {len(touched)} path(s) under that mount and "
               f"{len(written)} file(s) were observed there." + copy_text
             + " Copying files to removable media is a normal part of most jobs. Whether this "
               "instance was authorized is a question about the data and the person, which the "
               "evidence here does not answer."),
            triage=POTENTIALLY_HARMFUL if copies else NEEDS_REVIEW, corroborated=bool(copies),
            confidence=OBSERVED_DIRECTLY if copies else SINGLE_SOURCE,
            classification="HISTORICAL_EVIDENCE",
            action=("Identify what the copied files contain and whether the account had authority "
                    "to take them off this machine."),
            unknowns=("What was on the device before it was attached.",
                      "Where the device went afterwards. JOCKY does not read media contents."),
            why=(f"Files were written to removable media at {point}"
                 + (" and match files already on this machine." if copies else ".")),
            references=references))
        if len(findings) >= MAX_LINKS:
            break
    return findings


def correlate_sources(*, execution=None, artifacts=None, browser=None, usb=None) -> list:
    """Every cross-source link this build can draw on one host."""
    return (correlate_downloads(execution=execution, artifacts=artifacts, browser=browser)
            + correlate_removable_media(execution=execution, artifacts=artifacts, usb=usb))
