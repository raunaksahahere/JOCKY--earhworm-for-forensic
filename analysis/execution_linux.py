"""
Historical execution evidence from documented Linux telemetry.

Every source here is read-only and already present on the host. JOCKY never
enables auditing, never edits security policy and never touches EDR/AV
configuration: a source that is switched off is reported as NOT_ENABLED, not
switched on. Sources that need privileges JOCKY does not have are reported as
PERMISSION_DENIED rather than skipped silently.

Sources, and exactly what each one proves:

  systemd journal    an executable was running at the moment it logged. The
                     timestamp is the log time, never the process start time.
  shell history      a command was entered into a shell. It does not prove the
                     command ran, succeeded, or ran at the recorded time.
  audit log          execve was recorded by the kernel audit subsystem. This is
                     the strongest available execution evidence, and is usually
                     root-only and often not enabled.
  process accounting the kernel recorded a process exit. Usually not enabled.
  wtmp sessions      a login session opened or closed. Session context, not
                     process execution.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .execution_model import (
    AVAILABLE, NOT_AVAILABLE, NOT_ENABLED, PERMISSION_DENIED,
    HISTORICAL_EVIDENCE, build_event, interpreter_for, redact_command_line,
    source_record,
)

# Bounded everywhere: a forensic collector must not be a denial of service
# against the machine it is examining.
MAX_JOURNAL_RECORDS = 20000
MAX_EVENTS_PER_SOURCE = 2000
MAX_HISTORY_BYTES = 256 * 1024
MAX_HISTORY_LINES = 2000
MAX_AUDIT_BYTES = 8 * 1024 * 1024
MAX_WTMP_RECORDS = 5000
COMMAND_TIMEOUT = 60

UTMP_RECORD = "<hxxi32s4s32s256shhiii4i20x"
UTMP_SIZE = struct.calcsize(UTMP_RECORD)
UTMP_TYPES = {1: "runlevel", 2: "boot", 5: "init", 6: "login", 7: "session_open", 8: "session_close"}


def run_command(argv, timeout=COMMAND_TIMEOUT):
    """Execute a documented system utility and return (status, stdout).

    Kept tiny and injectable so collector behaviour can be driven by fixtures
    without a live host.
    """
    try:
        finished = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return NOT_AVAILABLE, ""
    except PermissionError:
        return PERMISSION_DENIED, ""
    except (subprocess.TimeoutExpired, OSError):
        return NOT_AVAILABLE, ""
    if finished.returncode != 0:
        combined = (finished.stderr or "").lower()
        if "permission" in combined or "not permitted" in combined or "access denied" in combined:
            return PERMISSION_DENIED, finished.stdout or ""
        return NOT_AVAILABLE, finished.stdout or ""
    return AVAILABLE, finished.stdout or ""


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def collect_journal(window, *, runner=run_command, include_command_lines=False, cancel=None):
    """Aggregate journal records into one event per (boot, pid, executable).

    A journal record proves the executable was alive when it wrote the record.
    Aggregating gives first and last observed times for that process instance;
    neither is a process start time, and the event says so.
    """
    argv = [
        "journalctl", "--utc", "--no-pager", "-o", "json",
        "--since", f"@{int(window.start.timestamp())}",
        "--until", f"@{int(window.end.timestamp())}",
        "-n", str(MAX_JOURNAL_RECORDS),
        "--output-fields=_EXE,_COMM,_PID,_UID,_CMDLINE,_SYSTEMD_UNIT,_BOOT_ID,_AUDIT_LOGINUID",
    ]
    status, output = runner(argv)
    if status != AVAILABLE:
        detail = {
            NOT_AVAILABLE: "journalctl is not present or returned an error; this host may not use systemd-journald.",
            PERMISSION_DENIED: "journalctl refused access. Reading other users' journal records usually requires membership of the systemd-journal group.",
        }[status]
        return source_record("systemd journal", status, detail=detail), []

    grouped, scanned, malformed = {}, 0, 0
    for line in output.splitlines():
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled while reading the systemd journal")
        line = line.strip()
        if not line:
            continue
        scanned += 1
        try:
            record = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        executable = record.get("_EXE")
        if not executable:
            # Only records carrying a trusted _EXE say anything about execution.
            continue
        try:
            moment = int(record["__REALTIME_TIMESTAMP"]) / 1_000_000
        except (KeyError, TypeError, ValueError):
            malformed += 1
            continue
        key = (record.get("_BOOT_ID"), record.get("_PID"), executable)
        entry = grouped.get(key)
        if entry is None:
            if len(grouped) >= MAX_EVENTS_PER_SOURCE:
                continue
            grouped[key] = entry = {"first": moment, "last": moment, "count": 0, "record": record}
        entry["first"] = min(entry["first"], moment)
        entry["last"] = max(entry["last"], moment)
        entry["count"] += 1
        if moment == entry["last"]:
            entry["record"] = record

    events = []
    for (boot_id, pid, executable), entry in grouped.items():
        record = entry["record"]
        name = record.get("_COMM") or os.path.basename(executable)
        unavailable = {
            "parent_process": "the systemd journal does not record a parent process",
            "parent_pid": "the systemd journal does not record a parent PID",
        }
        observed = {
            "process_name": name,
            "executable": executable,
            "pid": int(pid) if str(pid or "").isdigit() else None,
            "user": record.get("_UID"),
        }
        if include_command_lines and record.get("_CMDLINE"):
            observed["command_line"], redacted = redact_command_line(record["_CMDLINE"])
            if redacted:
                unavailable["command_line_secrets"] = "values resembling credentials were masked before storage"
        else:
            unavailable["command_line"] = (
                "collected only when the investigator opts in; command-line arguments can carry credentials"
            )
        events.append(build_event(
            source="systemd journal",
            source_record_id=record.get("__CURSOR"),
            timestamp=_iso(entry["first"]),
            last_seen=_iso(entry["last"]),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength=(
                "The executable was running when it wrote to the journal. The timestamp is when it "
                "logged, not when it started, and absence of a record does not mean it did not run."
            ),
            provenance=f"systemd-journald, boot {boot_id}",
            observed=observed,
            derived={
                "interpreter": interpreter_for(name, executable),
                "journal_record_count": entry["count"],
                "systemd_unit": record.get("_SYSTEMD_UNIT"),
            },
            unavailable=unavailable,
            raw={"_BOOT_ID": boot_id, "_SYSTEMD_UNIT": record.get("_SYSTEMD_UNIT"), "_UID": record.get("_UID")},
        ))

    truncated = scanned >= MAX_JOURNAL_RECORDS or len(grouped) >= MAX_EVENTS_PER_SOURCE
    detail = f"{scanned} journal records read; {len(events)} distinct process instances carried a trusted executable path."
    if malformed:
        detail += f" {malformed} records were unreadable and were skipped."
    if truncated:
        detail += " The journal query hit its bound; older records in the window were not read."
    return source_record(
        "systemd journal", AVAILABLE, detail=detail, event_count=len(events), truncated=truncated,
        evidence_strength="executable running at log time", location="systemd-journald",
    ), events


_BASH_TIMESTAMP = re.compile(r"^#(\d{9,11})$")
_ZSH_ENTRY = re.compile(r"^:\s*(\d+):(\d+);(.*)$")


def _read_tail(path: Path) -> tuple[str, int]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > MAX_HISTORY_BYTES:
            handle.seek(size - MAX_HISTORY_BYTES)
            handle.readline()  # discard the partial first line
        return handle.read().decode("utf-8", "replace"), size


def collect_shell_history(window, *, home=None, cancel=None):
    """Read shell history files the running user can already read.

    History proves a command was *entered*, never that it ran. Bash omits
    timestamps unless HISTTIMEFORMAT is configured, so untimestamped entries
    are reported with an explicit unavailable timestamp and bounded only by the
    file's modification time.
    """
    home = Path(home or Path.home())
    candidates = [
        ("bash", home / ".bash_history"),
        ("zsh", home / ".zsh_history"),
        ("fish", home / ".local/share/fish/fish_history"),
    ]
    events, notes, found, denied = [], [], False, False
    for shell, path in candidates:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled while reading shell history")
        try:
            if not path.is_file():
                continue
            text, size = _read_tail(path)
            modified = path.stat().st_mtime
        except PermissionError:
            denied = True
            notes.append(f"{path} could not be read (permission denied)")
            continue
        except OSError:
            continue
        found = True
        if modified < window.start.timestamp():
            notes.append(f"{path} was last modified before the collection window and was not parsed")
            continue
        lines = text.splitlines()[-MAX_HISTORY_LINES:]
        pending_timestamp, index = None, 0
        for line in lines:
            index += 1
            if not line.strip():
                continue
            moment, command = None, line
            stamp = _BASH_TIMESTAMP.match(line.strip())
            if stamp:
                pending_timestamp = int(stamp.group(1))
                continue
            zsh = _ZSH_ENTRY.match(line)
            if zsh:
                moment, command = int(zsh.group(1)), zsh.group(3)
            elif pending_timestamp is not None:
                moment, pending_timestamp = pending_timestamp, None
            if moment is not None and not window.contains(datetime.fromtimestamp(moment, timezone.utc)):
                continue
            if len(events) >= MAX_EVENTS_PER_SOURCE:
                break
            # The command text is the evidence; it is redacted like any other
            # command line because history routinely contains credentials.
            masked, redacted = redact_command_line(command.strip())
            program = (masked or "").split()[0] if masked and masked.split() else None
            unavailable = {}
            if moment is None:
                unavailable["timestamp"] = (
                    "this shell does not record per-entry timestamps (HISTTIMEFORMAT is not configured); "
                    f"the entry is only known to predate {_iso(modified)}"
                )
            if redacted:
                unavailable["command_line_secrets"] = "values resembling credentials were masked before storage"
            events.append(build_event(
                source=f"{shell} history",
                source_record_id=f"{path}:{index}",
                timestamp=_iso(moment) if moment is not None else None,
                classification=HISTORICAL_EVIDENCE,
                evidence_strength=(
                    "A command was entered into a shell. This does not establish that it ran, that it "
                    "succeeded, or that it ran at this time."
                ),
                provenance=str(path),
                observed={"command_line": masked, "process_name": program},
                derived={
                    "interpreter": shell,
                    "executable": None,
                    "history_file_modified": _iso(modified),
                },
                unavailable={
                    **unavailable,
                    "pid": "shell history does not record process identifiers",
                    "parent_pid": "shell history does not record process identifiers",
                    "executable": "shell history records the typed text, not a resolved executable path",
                },
                raw={"shell": shell, "file_size_bytes": size},
            ))
    if denied and not events:
        return source_record("shell history", PERMISSION_DENIED,
                             detail="; ".join(notes) or "shell history files could not be read"), []
    if not found:
        return source_record("shell history", NOT_AVAILABLE,
                             detail="No readable shell history file was found for the collecting user."), []
    detail = f"{len(events)} history entries within the collection window."
    if notes:
        detail += " " + "; ".join(notes) + "."
    untimestamped = sum(1 for event in events if event["timestamp"] is None)
    if untimestamped:
        detail += f" {untimestamped} entries carry no timestamp because the shell was not configured to record one."
    return source_record(
        "shell history", AVAILABLE, detail=detail, event_count=len(events),
        truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="command entered, not command executed", location=str(home),
    ), events


_AUDIT_EXE = re.compile(r'\bexe="([^"]+)"')
_AUDIT_PID = re.compile(r"\bpid=(\d+)")
_AUDIT_PPID = re.compile(r"\bppid=(\d+)")
_AUDIT_UID = re.compile(r"\buid=(\d+)")
_AUDIT_TIME = re.compile(r"\bmsg=audit\((\d+)\.(\d+):(\d+)\)")
_AUDIT_COMM = re.compile(r'\bcomm="([^"]+)"')


def collect_audit_log(window, *, path="/var/log/audit/audit.log", cancel=None):
    """Parse kernel audit execve records when the log exists and is readable.

    This is the only Linux source that records execution itself rather than a
    side effect of it. It is usually root-only, and is frequently not enabled.
    """
    log = Path(path)
    try:
        if not log.exists():
            return source_record(
                "kernel audit log", NOT_AVAILABLE, location=path,
                detail="No audit log is present. auditd is not installed or has never written a log on this host.",
            ), []
        size = log.stat().st_size
        with log.open("rb") as handle:
            if size > MAX_AUDIT_BYTES:
                handle.seek(size - MAX_AUDIT_BYTES)
                handle.readline()
            payload = handle.read().decode("utf-8", "replace")
    except PermissionError:
        return source_record(
            "kernel audit log", PERMISSION_DENIED, location=path,
            detail="The audit log exists but is not readable by the collecting user. It is normally readable only by root.",
        ), []
    except OSError as error:
        return source_record("kernel audit log", NOT_AVAILABLE, location=path,
                             detail=f"The audit log could not be read: {error.strerror or error}"), []

    events, malformed = [], 0
    for line in payload.splitlines():
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled while reading the audit log")
        if "type=SYSCALL" not in line or "exe=" not in line:
            continue
        stamp = _AUDIT_TIME.search(line)
        executable = _AUDIT_EXE.search(line)
        if not stamp or not executable:
            malformed += 1
            continue
        moment = int(stamp.group(1))
        if not window.contains(datetime.fromtimestamp(moment, timezone.utc)):
            continue
        if len(events) >= MAX_EVENTS_PER_SOURCE:
            break
        pid = _AUDIT_PID.search(line)
        ppid = _AUDIT_PPID.search(line)
        uid = _AUDIT_UID.search(line)
        comm = _AUDIT_COMM.search(line)
        name = comm.group(1) if comm else os.path.basename(executable.group(1))
        events.append(build_event(
            source="kernel audit log",
            source_record_id=f"audit:{stamp.group(3)}",
            timestamp=_iso(moment),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength="The kernel audit subsystem recorded this executable being executed.",
            provenance=path,
            observed={
                "process_name": name,
                "executable": executable.group(1),
                "pid": int(pid.group(1)) if pid else None,
                "parent_pid": int(ppid.group(1)) if ppid else None,
                "user": uid.group(1) if uid else None,
            },
            derived={"interpreter": interpreter_for(name, executable.group(1))},
            unavailable={
                "command_line": "argument vectors live in separate EXECVE records and are not correlated here",
                "parent_process": "the audit record carries a parent PID but not a parent image name",
            },
            raw={"audit_serial": stamp.group(3)},
        ))
    detail = f"{len(events)} execve records within the collection window."
    if malformed:
        detail += f" {malformed} records were unparseable and were skipped."
    return source_record(
        "kernel audit log", AVAILABLE, detail=detail, event_count=len(events),
        truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="kernel-recorded execution", location=path,
    ), events


def collect_process_accounting(window, *, runner=run_command, paths=None, cancel=None):
    """BSD process accounting, when the administrator has enabled it.

    Accounting records a process *exit*, which is execution evidence. It is off
    by default on every mainstream distribution; JOCKY reports that rather than
    enabling it.
    """
    candidates = [Path(p) for p in (paths or ("/var/log/account/pacct", "/var/account/pacct", "/var/log/pacct"))]
    present = [p for p in candidates if p.exists()]
    if not present:
        return source_record(
            "process accounting", NOT_ENABLED,
            detail=("No process accounting file exists. BSD process accounting is disabled by default; "
                    "enabling it is an administrative change JOCKY does not make."),
            location=", ".join(str(p) for p in candidates),
        ), []
    status, output = runner(["lastcomm", "--file", str(present[0])])
    if status != AVAILABLE:
        return source_record(
            "process accounting", status, location=str(present[0]),
            detail=("An accounting file exists but lastcomm could not read it."
                    if status == NOT_AVAILABLE else
                    "An accounting file exists but is not readable by the collecting user."),
        ), []
    events = []
    for index, line in enumerate(output.splitlines()):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled while reading process accounting")
        parts = line.split()
        if len(parts) < 4 or len(events) >= MAX_EVENTS_PER_SOURCE:
            continue
        events.append(build_event(
            source="process accounting",
            source_record_id=f"pacct:{index}",
            timestamp=None,
            classification=HISTORICAL_EVIDENCE,
            evidence_strength="The kernel recorded this command exiting.",
            provenance=str(present[0]),
            observed={"process_name": parts[0], "user": parts[-4] if len(parts) >= 4 else None},
            derived={"interpreter": interpreter_for(parts[0], None)},
            unavailable={
                "timestamp": "lastcomm output was not parsed for an absolute timestamp",
                "executable": "process accounting records a command name, not a resolved path",
                "pid": "process accounting does not record process identifiers",
            },
            raw={"line": line},
        ))
    return source_record(
        "process accounting", AVAILABLE, detail=f"{len(events)} accounting records.",
        event_count=len(events), evidence_strength="kernel-recorded process exit", location=str(present[0]),
    ), events


def collect_login_sessions(window, *, path="/var/log/wtmp", cancel=None):
    """Login/logout records from wtmp.

    Session context, not process execution: it shows who could have been at the
    machine when something ran. Parsed from the binary record directly so the
    result does not depend on the locale-formatted output of `last`.
    """
    log = Path(path)
    try:
        if not log.exists():
            return source_record("login sessions (wtmp)", NOT_AVAILABLE, location=path,
                                 detail="No wtmp file is present on this host."), []
        size = log.stat().st_size
        if size % UTMP_SIZE:
            return source_record(
                "login sessions (wtmp)", NOT_AVAILABLE, location=path,
                detail=(f"wtmp is {size} bytes, which is not a multiple of this platform's {UTMP_SIZE}-byte "
                        "record. The layout does not match and no records were decoded."),
            ), []
        with log.open("rb") as handle:
            if size > MAX_WTMP_RECORDS * UTMP_SIZE:
                handle.seek(size - MAX_WTMP_RECORDS * UTMP_SIZE)
            payload = handle.read()
    except PermissionError:
        return source_record("login sessions (wtmp)", PERMISSION_DENIED, location=path,
                             detail="wtmp exists but is not readable by the collecting user."), []
    except OSError as error:
        return source_record("login sessions (wtmp)", NOT_AVAILABLE, location=path,
                             detail=f"wtmp could not be read: {error.strerror or error}"), []

    events = []
    for offset in range(0, len(payload) - UTMP_SIZE + 1, UTMP_SIZE):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled while reading login records")
        fields = struct.unpack(UTMP_RECORD, payload[offset:offset + UTMP_SIZE])
        kind, pid, line, _id, user, host = fields[0], fields[1], _text(fields[2]), _text(fields[3]), _text(fields[4]), _text(fields[5])
        seconds = fields[9]
        if not user or kind not in UTMP_TYPES:
            continue
        if not window.contains(datetime.fromtimestamp(seconds, timezone.utc)):
            continue
        if len(events) >= MAX_EVENTS_PER_SOURCE:
            break
        events.append(build_event(
            source="login sessions (wtmp)",
            source_record_id=f"wtmp:{offset}",
            timestamp=_iso(seconds),
            classification=HISTORICAL_EVIDENCE,
            evidence_strength=(
                "A login session record. This establishes session context, not that any particular "
                "program was executed."
            ),
            provenance=path,
            observed={"user": user, "pid": pid or None, "process_name": UTMP_TYPES[kind]},
            derived={"session_line": line, "session_host": host or None},
            unavailable={
                "executable": "wtmp records sessions, not executables",
                "command_line": "wtmp records sessions, not commands",
            },
            raw={"record_type": UTMP_TYPES[kind], "line": line, "host": host},
        ))
    return source_record(
        "login sessions (wtmp)", AVAILABLE, detail=f"{len(events)} session records within the collection window.",
        event_count=len(events), truncated=len(events) >= MAX_EVENTS_PER_SOURCE,
        evidence_strength="session context", location=path,
    ), events


def collect(window, *, include_command_lines=False, cancel=None, **overrides):
    """Run every Linux source and return (source records, events)."""
    sources, events = [], []
    collectors = (
        lambda: collect_journal(window, include_command_lines=include_command_lines, cancel=cancel,
                                **({"runner": overrides["runner"]} if "runner" in overrides else {})),
        lambda: collect_shell_history(window, cancel=cancel,
                                      **({"home": overrides["home"]} if "home" in overrides else {})),
        lambda: collect_audit_log(window, cancel=cancel,
                                  **({"path": overrides["audit_path"]} if "audit_path" in overrides else {})),
        lambda: collect_process_accounting(window, cancel=cancel,
                                           **({"runner": overrides["runner"]} if "runner" in overrides else {}),
                                           **({"paths": overrides["accounting_paths"]} if "accounting_paths" in overrides else {})),
        lambda: collect_login_sessions(window, cancel=cancel,
                                       **({"path": overrides["wtmp_path"]} if "wtmp_path" in overrides else {})),
    )
    for collector in collectors:
        record, produced = collector()
        sources.append(record)
        events.extend(produced)
    return sources, events
