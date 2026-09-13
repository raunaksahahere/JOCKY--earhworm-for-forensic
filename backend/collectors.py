"""Bounded current observations. Nothing here establishes historical execution."""
import os
from datetime import datetime, timezone

import psutil

from analysis.execution_model import INTERPRETERS, redact_command_line

# Bounded, but no longer arbitrarily small. A desktop routinely runs more than
# 256 processes, and the old cap silently dropped whatever iteration order
# happened to reach last.
DEFAULT_MAX_PROCESSES = 4096
MAX_PROCESSES_CEILING = 20000


def process_snapshot(cancel=None, *, max_processes=DEFAULT_MAX_PROCESSES, include_command_lines=False):
    """Observe the processes running right now.

    Truncation is deterministic: process identifiers are sorted before
    collection, so the same machine state yields the same snapshot and the
    omitted range is stated rather than left to iteration order.
    """
    try:
        max_processes = int(max_processes)
    except (TypeError, ValueError):
        raise ValueError("max_processes must be an integer")
    if max_processes < 1 or max_processes > MAX_PROCESSES_CEILING:
        raise ValueError(f"max_processes must be between 1 and {MAX_PROCESSES_CEILING}")

    identifiers = sorted(psutil.pids())
    selected = identifiers[:max_processes]
    truncated = len(identifiers) > max_processes
    rows, vanished, denied, redacted_count = [], [], 0, 0

    for pid in selected:
        if cancel and cancel.is_set():
            raise InterruptedError("Collection cancelled between process observations")
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            # Exited between enumeration and inspection. Recorded, never dropped.
            vanished.append(pid)
            continue
        except psutil.AccessDenied:
            denied += 1
            rows.append({"pid": pid, "classification": "CURRENT_OBSERVATION", "source": "psutil current process snapshot",
                         "name": None, "executable": None, "parent_pid": None, "started_at": None,
                         "command_line": None, "interpreter": None,
                         "unavailable": {field: "permission_denied" for field in
                                         ("name", "executable", "parent_pid", "started_at", "command_line")}})
            continue

        row = {"pid": pid, "classification": "CURRENT_OBSERVATION", "source": "psutil current process snapshot"}
        unavailable = {}
        for field, method in (("name", "name"), ("executable", "exe"), ("parent_pid", "ppid"), ("started_at", "create_time")):
            try:
                value = getattr(process, method)()
                if field == "started_at":
                    value = datetime.fromtimestamp(value, timezone.utc).isoformat()
                row[field] = value or None
                if not value:
                    unavailable[field] = "unavailable"
            except psutil.NoSuchProcess:
                row[field] = None
                unavailable[field] = "process exited during collection"
            except (psutil.Error, OSError, ValueError) as error:
                row[field] = None
                unavailable[field] = "permission_denied" if isinstance(error, psutil.AccessDenied) else "unavailable"
                denied += isinstance(error, psutil.AccessDenied)

        # Arguments routinely carry passwords and tokens, so they are off unless
        # the investigator opts in, and are redacted even then.
        if include_command_lines:
            try:
                row["command_line"], was_redacted = redact_command_line(" ".join(process.cmdline()))
                redacted_count += was_redacted
                if was_redacted:
                    unavailable["command_line_secrets"] = "values resembling credentials were masked before storage"
            except (psutil.Error, OSError) as error:
                row["command_line"] = None
                unavailable["command_line"] = "permission_denied" if isinstance(error, psutil.AccessDenied) else "unavailable"
        else:
            row["command_line"] = None
            unavailable["command_line"] = "skipped: command-line arguments may contain credentials"

        row["interpreter"] = row["name"] if (row["name"] or "").lower() in INTERPRETERS else None
        row["unavailable"] = unavailable
        rows.append(row)

    warnings = [
        "CURRENT OBSERVATION: a running process establishes the present. It does not establish that any "
        "program ran before this collection, and it is not historical execution evidence.",
    ]
    if not include_command_lines:
        warnings.append("Command-line arguments were skipped to avoid collecting credentials.")
    if truncated:
        warnings.append(
            f"Process snapshot truncated at {max_processes} of {len(identifiers)} processes. Processes with "
            f"identifiers above {selected[-1]} were running but were not recorded."
        )
    if denied:
        warnings.append(f"{denied} processes could not be fully inspected with the collector's privileges.")
    if vanished:
        warnings.append(f"{len(vanished)} processes exited between enumeration and inspection.")

    return {
        "action": "process_snapshot",
        "status": "success",
        "classification": "CURRENT_OBSERVATION",
        "processes": rows,
        "truncated": truncated,
        "skipped": vanished,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "statistics": {
            "processes_present": len(identifiers),
            "processes_recorded": len(rows),
            "processes_exited_during_collection": len(vanished),
            "permission_denied": denied,
            "command_lines_redacted": redacted_count,
            "highest_pid_recorded": selected[-1] if selected else None,
        },
        "limits": {"max_processes": max_processes, "ceiling": MAX_PROCESSES_CEILING,
                   "ordering": "ascending process identifier",
                   "command_lines_collected": include_command_lines},
        "warnings": warnings,
        "complete": not truncated,
    }
