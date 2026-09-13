"""Bounded current observations. No historical execution inference or native agent."""
import os
from datetime import datetime, timezone

import psutil

MAX_PROCESSES = 256
INTERPRETERS = {"python", "python3", "python.exe", "python3.exe", "bash", "sh", "zsh", "node", "node.exe", "powershell.exe", "pwsh", "cmd.exe", "wscript.exe", "cscript.exe", "perl", "ruby"}


def process_snapshot(cancel=None):
    rows, skipped = [], []
    truncated = False
    for process in psutil.process_iter():
        if cancel and cancel.is_set():
            raise InterruptedError("Collection cancelled between process observations")
        if len(rows) + len(skipped) >= MAX_PROCESSES:
            truncated = True
            break
        row = {"pid": process.pid, "classification": "OBSERVED", "source": "psutil current process snapshot"}
        unavailable = {}
        for field, method in (("name", "name"), ("executable", "exe"), ("parent_pid", "ppid"), ("started_at", "create_time")):
            try:
                value = getattr(process, method)()
                if field == "started_at":
                    value = datetime.fromtimestamp(value, timezone.utc).isoformat()
                row[field] = value or None
                if not value:
                    unavailable[field] = "unavailable"
            except (psutil.Error, OSError, ValueError) as error:
                row[field] = None
                unavailable[field] = "permission_denied" if isinstance(error, psutil.AccessDenied) else "unavailable"
        # Arguments can expose passwords/tokens. Their collection is deliberately
        # not enabled; interpreter identity alone is never proof of a script run.
        row["command_line"] = None
        unavailable["command_line"] = "skipped: command-line arguments may contain credentials"
        row["interpreter"] = row["name"] if (row["name"] or "").lower() in INTERPRETERS else None
        row["unavailable"] = unavailable
        rows.append(row)
    return {"action": "process_snapshot", "status": "success", "classification": "OBSERVED",
            "processes": rows, "truncated": truncated, "skipped": skipped,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "warnings": ["CURRENT OBSERVATION only; no historical execution telemetry is available.",
                         "Command-line arguments were skipped to avoid collecting credentials."] +
                        (["Process snapshot truncated at 256 entries."] if truncated else []),
            "complete": not truncated}
