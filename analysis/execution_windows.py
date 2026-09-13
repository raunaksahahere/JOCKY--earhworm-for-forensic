"""
Historical execution evidence from documented Windows telemetry.

Every source is read-only and uses a documented Windows interface. JOCKY never
enables an audit policy, installs a sensor, or changes any security setting: a
channel that is not enabled is reported as NOT_ENABLED.

Sources, and exactly what each one proves:

  Security 4688     the kernel recorded a process being created. The strongest
                    native source, and off by default -- "Audit Process
                    Creation" must have been enabled by an administrator.
  Sysmon Event 1    a process was created, with hashes and parent image. Only
                    present when Sysmon has been deployed.
  PowerShell 4104   a script block was compiled for execution. Present when
                    script block logging is enabled.
  PowerShell 400    the PowerShell engine started. Widely available, but says
                    nothing about what was run.
  Prefetch          the named executable has been run at least once on this
                    volume. Metadata only: JOCKY reads the file name and
                    timestamps, never the compressed contents.
  UserAssist        the interactive user launched a program through the shell,
                    with a run count and last-run time.

This module imports cleanly on non-Windows hosts so its normalisation can be
tested with recorded fixtures; the collectors then report NOT_AVAILABLE.
"""

from __future__ import annotations

import os
import platform
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from .execution_linux import run_command
from .execution_model import (
    AVAILABLE, NOT_AVAILABLE, NOT_ENABLED, PERMISSION_DENIED,
    HISTORICAL_EVIDENCE, build_event, interpreter_for, redact_command_line,
    source_record,
)

MAX_EVENTS_PER_SOURCE = 2000
MAX_PREFETCH_FILES = 2000
MAX_USERASSIST_VALUES = 2000
EVENT_NAMESPACE = "{http://schemas.microsoft.com/win/2004/08/events/event}"

# Windows FILETIME epoch: 1601-01-01. Used by UserAssist and prefetch metadata.
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def is_windows() -> bool:
    return os.name == "nt" or platform.system() == "Windows"


def filetime_to_iso(value: int) -> str | None:
    """Convert a 100-nanosecond FILETIME to ISO-8601, or None when unset."""
    if not value:
        return None
    try:
        return (FILETIME_EPOCH + timedelta(microseconds=value / 10)).isoformat()
    except (OverflowError, ValueError):
        return None


def query_channel(channel, xpath, *, count=MAX_EVENTS_PER_SOURCE, runner=run_command):
    """Read an event log channel with wevtutil and return parsed Event elements.

    wevtutil emits a bare sequence of <Event> elements rather than a document,
    so the output is wrapped before parsing.
    """
    status, output = runner([
        "wevtutil", "qe", channel, "/f:xml", "/rd:true", f"/c:{count}", f"/q:{xpath}",
    ])
    if status != AVAILABLE:
        return status, []
    if not output.strip():
        return AVAILABLE, []
    try:
        document = ElementTree.fromstring(f"<Events>{output}</Events>")
    except ElementTree.ParseError:
        return NOT_AVAILABLE, []
    return AVAILABLE, list(document.findall(f"{EVENT_NAMESPACE}Event"))


def _system_field(event, name, attribute=None):
    node = event.find(f"{EVENT_NAMESPACE}System/{EVENT_NAMESPACE}{name}")
    if node is None:
        return None
    return node.get(attribute) if attribute else (node.text or None)


def _event_data(event) -> dict:
    data = {}
    for node in event.findall(f"{EVENT_NAMESPACE}EventData/{EVENT_NAMESPACE}Data"):
        key = node.get("Name")
        if key:
            data[key] = node.text
    return data


def _time_filter(window, *, event_ids):
    ids = " or ".join(f"EventID={value}" for value in event_ids)
    start = window.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = window.end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (f"*[System[({ids}) and TimeCreated[@SystemTime&gt;='{start}' and "
            f"@SystemTime&lt;='{end}']]]")


def _unavailable_channel(name, status, *, channel, enabled_hint):
    detail = {
        NOT_AVAILABLE: f"The {channel} channel could not be queried. It may not exist on this Windows edition.",
        PERMISSION_DENIED: f"The {channel} channel exists but is not readable. {enabled_hint}",
        NOT_ENABLED: f"The {channel} channel returned no records. {enabled_hint}",
    }[status]
    return source_record(name, status, detail=detail, location=channel)


def collect_process_creation(window, *, runner=run_command, include_command_lines=False):
    """Security channel event 4688 - kernel-recorded process creation."""
    if not is_windows():
        return source_record("Windows Security 4688", NOT_AVAILABLE, location="Security",
                             detail="Not a Windows host."), []
    status, records = query_channel("Security", _time_filter(window, event_ids=(4688,)), runner=runner)
    hint = ("Reading the Security channel requires administrative rights, and 'Audit Process Creation' "
            "must be enabled in Local Security Policy. JOCKY does not change audit policy.")
    if status != AVAILABLE:
        return _unavailable_channel("Windows Security 4688", status, channel="Security", enabled_hint=hint), []
    if not records:
        return _unavailable_channel("Windows Security 4688", NOT_ENABLED, channel="Security", enabled_hint=hint), []

    events = []
    for record in records:
        data = _event_data(record)
        image = data.get("NewProcessName")
        name = os.path.basename(image or "") or None
        unavailable = {}
        command_line = None
        if include_command_lines and data.get("CommandLine"):
            command_line, redacted = redact_command_line(data["CommandLine"])
            if redacted:
                unavailable["command_line_secrets"] = "values resembling credentials were masked before storage"
        elif not data.get("CommandLine"):
            unavailable["command_line"] = (
                "4688 records a command line only when 'Include command line in process creation events' "
                "is enabled; it is not enabled on this host"
            )
        else:
            unavailable["command_line"] = (
                "collected only when the investigator opts in; command-line arguments can carry credentials"
            )
        events.append(build_event(
            source="Windows Security 4688",
            source_record_id=_system_field(record, "EventRecordID"),
            timestamp=_system_field(record, "TimeCreated", "SystemTime"),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength="Windows recorded this process being created.",
            provenance="Security event log, channel Security",
            observed={
                "process_name": name,
                "executable": image,
                "pid": _as_int(data.get("NewProcessId")),
                "parent_pid": _as_int(data.get("ProcessId")),
                "parent_process": data.get("ParentProcessName"),
                "user": _account(data.get("SubjectDomainName"), data.get("SubjectUserName")),
                "command_line": command_line,
            },
            derived={"interpreter": interpreter_for(name, image)},
            unavailable=unavailable,
            raw={"TokenElevationType": data.get("TokenElevationType"), "LogonId": data.get("SubjectLogonId")},
        ))
    return source_record(
        "Windows Security 4688", AVAILABLE, detail=f"{len(events)} process creation records within the collection window.",
        event_count=len(events), truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="kernel-recorded process creation", location="Security",
    ), events


def collect_sysmon(window, *, runner=run_command, include_command_lines=False):
    """Sysmon event 1 - process creation with parent image and image hashes."""
    if not is_windows():
        return source_record("Sysmon Event 1", NOT_AVAILABLE, location="Microsoft-Windows-Sysmon/Operational",
                             detail="Not a Windows host."), []
    channel = "Microsoft-Windows-Sysmon/Operational"
    status, records = query_channel(channel, _time_filter(window, event_ids=(1,)), runner=runner)
    hint = "Sysmon is a separate Microsoft Sysinternals sensor; JOCKY does not install it."
    if status != AVAILABLE:
        return _unavailable_channel("Sysmon Event 1", status, channel=channel, enabled_hint=hint), []
    if not records:
        return _unavailable_channel("Sysmon Event 1", NOT_ENABLED, channel=channel, enabled_hint=hint), []

    events = []
    for record in records:
        data = _event_data(record)
        image = data.get("Image")
        name = os.path.basename(image or "") or None
        unavailable = {}
        command_line = None
        if include_command_lines and data.get("CommandLine"):
            command_line, redacted = redact_command_line(data["CommandLine"])
            if redacted:
                unavailable["command_line_secrets"] = "values resembling credentials were masked before storage"
        else:
            unavailable["command_line"] = (
                "collected only when the investigator opts in; command-line arguments can carry credentials"
            )
        events.append(build_event(
            source="Sysmon Event 1",
            source_record_id=_system_field(record, "EventRecordID"),
            timestamp=data.get("UtcTime") or _system_field(record, "TimeCreated", "SystemTime"),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength="Sysmon recorded this process being created.",
            provenance=f"event log channel {channel}",
            observed={
                "process_name": name,
                "executable": image,
                "pid": _as_int(data.get("ProcessId")),
                "parent_pid": _as_int(data.get("ParentProcessId")),
                "parent_process": data.get("ParentImage"),
                "user": data.get("User"),
                "hash": _sysmon_sha256(data.get("Hashes")),
                "command_line": command_line,
            },
            derived={"interpreter": interpreter_for(name, image)},
            unavailable=unavailable,
            raw={"ProcessGuid": data.get("ProcessGuid"), "Hashes": data.get("Hashes")},
        ))
    return source_record(
        "Sysmon Event 1", AVAILABLE, detail=f"{len(events)} Sysmon process creation records within the collection window.",
        event_count=len(events), truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="sensor-recorded process creation with image hash", location=channel,
    ), events


def collect_powershell(window, *, runner=run_command):
    """PowerShell script block compilation (4104) and engine start (400)."""
    if not is_windows():
        return source_record("PowerShell operational log", NOT_AVAILABLE,
                             location="Microsoft-Windows-PowerShell/Operational",
                             detail="Not a Windows host."), []
    channel = "Microsoft-Windows-PowerShell/Operational"
    status, records = query_channel(channel, _time_filter(window, event_ids=(4104,)), runner=runner)
    hint = ("Script block logging is a Group Policy setting. JOCKY reports it as off rather than enabling it.")
    if status != AVAILABLE:
        return _unavailable_channel("PowerShell operational log", status, channel=channel, enabled_hint=hint), []
    if not records:
        return _unavailable_channel("PowerShell operational log", NOT_ENABLED, channel=channel, enabled_hint=hint), []

    events = []
    for record in records:
        data = _event_data(record)
        # Script text is evidence, but is also a common place for embedded
        # secrets, so it is redacted and truncated like any other command text.
        script, redacted = redact_command_line((data.get("ScriptBlockText") or "").strip()[:4000])
        events.append(build_event(
            source="PowerShell 4104",
            source_record_id=_system_field(record, "EventRecordID"),
            timestamp=_system_field(record, "TimeCreated", "SystemTime"),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength=(
                "PowerShell compiled this script block for execution. Compilation is strong evidence the "
                "block ran, but the record does not carry its outcome."
            ),
            provenance=f"event log channel {channel}",
            observed={"command_line": script, "process_name": "powershell", "executable": data.get("Path")},
            derived={"interpreter": "powershell"},
            unavailable={
                **({"command_line_secrets": "values resembling credentials were masked before storage"} if redacted else {}),
                "pid": "4104 does not record the process identifier in event data",
                "parent_pid": "4104 does not record a parent process",
            },
            raw={"ScriptBlockId": data.get("ScriptBlockId"), "MessageNumber": data.get("MessageNumber")},
        ))
    return source_record(
        "PowerShell operational log", AVAILABLE,
        detail=f"{len(events)} script block records within the collection window.",
        event_count=len(events), truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="script block compiled for execution", location=channel,
    ), events


def collect_prefetch(window, *, directory=r"C:\Windows\Prefetch"):
    """Prefetch file metadata - names and timestamps only, never contents.

    A prefetch file named FOO.EXE-XXXXXXXX.pf means FOO.EXE has run on this
    volume. Its modification time approximates the most recent run. JOCKY does
    not decompress or parse the file body, so it reports exactly this and no
    per-run history.
    """
    if not is_windows():
        return source_record("Windows Prefetch", NOT_AVAILABLE, location=directory,
                             detail="Not a Windows host."), []
    folder = Path(directory)
    try:
        if not folder.is_dir():
            return source_record(
                "Windows Prefetch", NOT_ENABLED, location=directory,
                detail=("No prefetch directory is present. Prefetch is commonly disabled on SSD-backed "
                        "systems and in virtual machines."),
            ), []
        entries = sorted(folder.glob("*.pf"))[:MAX_PREFETCH_FILES]
    except PermissionError:
        return source_record(
            "Windows Prefetch", PERMISSION_DENIED, location=directory,
            detail="The prefetch directory exists but is not readable. It normally requires administrative rights.",
        ), []
    except OSError as error:
        return source_record("Windows Prefetch", NOT_AVAILABLE, location=directory,
                             detail=f"The prefetch directory could not be read: {error}"), []
    if not entries:
        return source_record("Windows Prefetch", NOT_ENABLED, location=directory,
                             detail="The prefetch directory exists but contains no prefetch files."), []

    events = []
    for entry in entries:
        try:
            stat = entry.stat()
        except OSError:
            continue
        moment = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if not window.contains(moment):
            continue
        executable_name = entry.name.rsplit("-", 1)[0]
        events.append(build_event(
            source="Windows Prefetch",
            source_record_id=entry.name,
            timestamp=moment.isoformat(),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength=(
                "A prefetch file exists for this executable, so it has run on this volume at least once. "
                "The timestamp is the prefetch file's modification time, which approximates the most "
                "recent run; earlier runs are not enumerated because the file body is not parsed."
            ),
            provenance=str(entry),
            observed={"process_name": executable_name},
            derived={"interpreter": interpreter_for(executable_name, None)},
            unavailable={
                "executable": "the prefetch file name carries an image name, not a full path",
                "pid": "prefetch does not record process identifiers",
                "parent_pid": "prefetch does not record a parent process",
                "command_line": "prefetch does not record command lines",
                "user": "prefetch does not record the invoking account",
            },
            raw={"prefetch_file": entry.name, "size_bytes": stat.st_size},
        ))
    return source_record(
        "Windows Prefetch", AVAILABLE, detail=f"{len(events)} prefetch files modified within the collection window.",
        event_count=len(events), truncated=len(entries) >= MAX_PREFETCH_FILES,
        evidence_strength="executable has run on this volume", location=directory,
    ), events


def _rot13(text: str) -> str:
    import codecs
    return codecs.decode(text, "rot_13")


def collect_userassist(window, *, registry=None):
    """UserAssist - programs the interactive user launched through the shell.

    Readable without administrative rights. Value names are ROT13-encoded, and
    each value carries a run count and a last-executed FILETIME.
    """
    if registry is None:
        if not is_windows():
            return source_record("UserAssist", NOT_AVAILABLE, location="HKCU",
                                 detail="Not a Windows host."), []
        try:
            import winreg as registry
        except ImportError:  # pragma: no cover - Windows always provides winreg
            return source_record("UserAssist", NOT_AVAILABLE, location="HKCU",
                                 detail="The winreg module is unavailable."), []

    base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
    events = []
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, base) as root:
            index = 0
            while True:
                try:
                    guid = registry.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with registry.OpenKey(root, rf"{guid}\Count") as counts:
                        events.extend(_userassist_values(registry, counts, window, guid))
                except OSError:
                    continue
    except PermissionError:
        return source_record("UserAssist", PERMISSION_DENIED, location=f"HKCU\\{base}",
                             detail="The UserAssist key exists but could not be read."), []
    except OSError:
        return source_record("UserAssist", NOT_AVAILABLE, location=f"HKCU\\{base}",
                             detail="No UserAssist key was found for the collecting user."), []
    if not events:
        return source_record("UserAssist", NOT_ENABLED, location=f"HKCU\\{base}",
                             detail="UserAssist holds no entries with a last-executed time inside the collection window."), []
    return source_record(
        "UserAssist", AVAILABLE, detail=f"{len(events)} shell-launched programs within the collection window.",
        event_count=len(events), truncated=len(events) >= MAX_USERASSIST_VALUES,
        evidence_strength="program launched interactively through the shell", location=f"HKCU\\{base}",
    ), events


def _userassist_values(registry, key, window, guid):
    produced, index = [], 0
    while len(produced) < MAX_USERASSIST_VALUES:
        try:
            name, value, _kind = registry.EnumValue(key, index)
        except OSError:
            break
        index += 1
        if not isinstance(value, (bytes, bytearray)) or len(value) < 68:
            continue
        try:
            run_count = struct.unpack_from("<I", value, 4)[0]
            last_run = struct.unpack_from("<Q", value, 60)[0]
        except struct.error:
            continue
        stamp = filetime_to_iso(last_run)
        if stamp is None:
            continue
        try:
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if not window.contains(moment):
            continue
        decoded = _rot13(name)
        produced.append(build_event(
            source="UserAssist",
            source_record_id=f"{guid}:{name}",
            timestamp=stamp,
            classification=HISTORICAL_EVIDENCE,
            evidence_strength=(
                "The interactive user launched this program through the Windows shell. The record carries "
                "a run count and the most recent launch time, not a per-run history."
            ),
            provenance=rf"HKCU\...\UserAssist\{guid}\Count",
            observed={"executable": decoded, "process_name": os.path.basename(decoded)},
            derived={"run_count": run_count, "interpreter": interpreter_for(os.path.basename(decoded), decoded)},
            unavailable={
                "pid": "UserAssist does not record process identifiers",
                "parent_pid": "UserAssist does not record a parent process",
                "command_line": "UserAssist does not record command lines",
            },
            raw={"guid": guid, "run_count": run_count},
        ))
    return produced


def _as_int(value):
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _account(domain, user):
    if user and domain:
        return f"{domain}\\{user}"
    return user or None


def _sysmon_sha256(hashes):
    for part in (hashes or "").split(","):
        key, _, value = part.partition("=")
        if key.strip().upper() == "SHA256":
            return value.strip().lower() or None
    return None


def collect(window, *, include_command_lines=False, cancel=None, **overrides):
    """Run every Windows source and return (source records, events)."""
    runner = overrides.get("runner", run_command)
    sources, events = [], []
    for record, produced in (
        collect_process_creation(window, runner=runner, include_command_lines=include_command_lines),
        collect_sysmon(window, runner=runner, include_command_lines=include_command_lines),
        collect_powershell(window, runner=runner),
        collect_prefetch(window, **({"directory": overrides["prefetch_directory"]} if "prefetch_directory" in overrides else {})),
        collect_userassist(window, **({"registry": overrides["registry"]} if "registry" in overrides else {})),
    ):
        sources.append(record)
        events.extend(produced)
    return sources, events
