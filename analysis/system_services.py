"""
Read-only service and scheduling metadata.

What is configured to start, and what is scheduled to run. Both are ordinary
persistence locations, so an investigator wants to see them; JOCKY reads them
and changes nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .execution_linux import run_command
from .execution_model import AVAILABLE, NOT_AVAILABLE, PERMISSION_DENIED, source_record

MAX_UNITS = 1000
MAX_JOBS = 500

CRON_LOCATIONS = ("/etc/crontab", "/etc/cron.d", "/var/spool/cron/crontabs")


def _units(runner=run_command, limit=MAX_UNITS):
    """systemd units and their current state, via systemd's own JSON output."""
    status, output = runner(["systemctl", "list-units", "--all", "--no-pager", "--no-legend",
                             "--output=json", "--type=service"])
    if status != AVAILABLE:
        return [], source_record("systemd units", status, location="systemctl",
                                 detail="systemd unit state could not be read on this host.")
    try:
        rows = json.loads(output)
    except ValueError:
        return [], source_record("systemd units", NOT_AVAILABLE, location="systemctl",
                                 detail="systemctl produced output JOCKY could not parse.")
    units = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        units.append({
            "unit": row.get("unit"), "load": row.get("load"), "active": row.get("active"),
            "sub": row.get("sub"), "description": row.get("description"),
            "classification": "CURRENT_OBSERVATION", "source": "systemctl list-units",
            "evidence_strength": ("The unit's state as systemd reports it now. Configuration, not "
                                  "a record of past execution."),
        })
    return units, source_record("systemd units", AVAILABLE, location="systemctl",
                                detail=f"{len(units)} service units.", event_count=len(units))


def _cron(locations=CRON_LOCATIONS, limit=MAX_JOBS):
    """Scheduled jobs, read from the ordinary crontab locations."""
    jobs, unreadable = [], []
    for location in locations:
        path = Path(location)
        try:
            files = [path] if path.is_file() else sorted(path.iterdir()) if path.is_dir() else []
        except PermissionError:
            unreadable.append(location)
            continue
        except OSError:
            continue
        for entry in files:
            if len(jobs) >= limit:
                break
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except PermissionError:
                unreadable.append(str(entry))
                continue
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" in stripped.split()[0:1][0:1]:
                    continue
                if stripped.startswith("@") or stripped[0].isdigit() or stripped[0] == "*":
                    jobs.append({
                        "schedule_file": str(entry), "line": number, "entry": stripped[:500],
                        "classification": "CURRENT_OBSERVATION", "source": str(entry),
                        "evidence_strength": ("A scheduled job as configured now. It does not "
                                              "establish that the job has run."),
                    })
    status = AVAILABLE if jobs or not unreadable else PERMISSION_DENIED
    detail = f"{len(jobs)} scheduled jobs."
    if unreadable:
        detail += f" {len(unreadable)} locations were not readable."
    return jobs, source_record("scheduled jobs", status,
                               location=", ".join(locations), detail=detail, event_count=len(jobs))


def collect_services(cancel=None, *, runner=run_command, cron_locations=CRON_LOCATIONS) -> dict:
    """Services and scheduled jobs, read-only."""
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled before services were read")

    units, unit_source = _units(runner)
    jobs, cron_source = _cron(cron_locations)
    sources = [unit_source, cron_source]

    warnings = [
        "CURRENT OBSERVATION: services and schedules describe how the host is configured now. "
        "Neither establishes that anything has run.",
    ]
    for source in sources:
        if source["status"] != AVAILABLE:
            warnings.append(f"{source['name']}: {source['detail']}")

    return {
        "action": "services_and_scheduling",
        "status": "success",
        "classification": "CURRENT_OBSERVATION",
        "units": units,
        "scheduled_jobs": jobs,
        "sources": sources,
        "statistics": {"units": len(units), "scheduled_jobs": len(jobs),
                       "active_units": sum(1 for unit in units if unit.get("active") == "active")},
        "limits": {"max_units": MAX_UNITS, "max_jobs": MAX_JOBS},
        "truncated": len(units) >= MAX_UNITS or len(jobs) >= MAX_JOBS,
        "complete": all(source["status"] == AVAILABLE for source in sources),
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
