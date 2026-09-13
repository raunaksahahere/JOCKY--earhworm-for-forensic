"""
Read-only process observation for forensic context.

Lists currently running processes and basic resource metadata. This
module only *reads* process table information via psutil; it never
starts, stops, suspends, injects into, or otherwise controls a process.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

MAX_PROCESSES_RETURNED = 60


def list_processes() -> dict:
    if psutil is None:
        raise RuntimeError("psutil is required for process observation but is not installed")

    collected = []
    total_seen = 0
    skipped = 0
    unavailable = 0
    for proc in psutil.process_iter(
        ["pid", "name", "username", "status", "memory_percent", "create_time"]
    ):
        total_seen += 1
        try:
            data = proc.info
            if data.get("memory_percent") is None:
                unavailable += 1
            collected.append(
                {
                    "pid": data.get("pid"),
                    "name": data.get("name") or "unknown",
                    "username": data.get("username") or "n/a",
                    "status": data.get("status") or "unknown",
                    "memory_percent": (round(data["memory_percent"], 3)
                                       if data.get("memory_percent") is not None else None),
                    # A single process snapshot cannot establish an interval
                    # CPU percentage. Never turn an unprimed sample into zero.
                    "cpu_percent": None,
                    "created": (
                        datetime.fromtimestamp(data["create_time"], tz=timezone.utc).isoformat()
                        if data.get("create_time") is not None
                        else None
                    ),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            skipped += 1
            continue

    collected.sort(key=lambda p: p["memory_percent"] if p["memory_percent"] is not None else -1, reverse=True)
    truncated = len(collected) > MAX_PROCESSES_RETURNED
    top = collected[:MAX_PROCESSES_RETURNED]

    return {
        "action": "processes",
        "process_count": total_seen,
        "returned_count": len(top),
        "truncated": truncated,
        "skipped_count": skipped,
        "complete": not truncated and not skipped and not unavailable,
        "warnings": ["Per-process CPU percentage was not sampled; null means unavailable."]
                    + ([f"{skipped} processes could not be read."] if skipped else [])
                    + ([f"{unavailable} processes have unavailable memory measurements."] if unavailable else [])
                    + (["Process list was truncated."] if truncated else []),
        "processes": top,
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
        "status": "success",
        "message": f"{total_seen} processes observed (showing top {len(top)} by memory use)",
    }
