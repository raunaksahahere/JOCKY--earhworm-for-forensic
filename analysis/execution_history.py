"""
Platform-neutral entry point for historical execution evidence.

Each platform has its own collector because the available telemetry differs in
kind, not just in spelling: Linux has a journal and an optional kernel audit
trail, Windows has event log channels, prefetch and registry artefacts. They
are normalised at the event level (see `execution_model`), never forced into a
single implementation.

A platform with no usable source returns an explicit set of unavailable source
records. It never returns an empty success.
"""

from __future__ import annotations

import platform as platform_module
from datetime import datetime

from . import execution_linux, execution_windows
from .execution_model import (
    AVAILABLE, NOT_AVAILABLE, NOT_COLLECTED, CollectionWindow, HISTORICAL_EVIDENCE,
    source_record,
)

MAX_TOTAL_EVENTS = 5000


class ExecutionTelemetryCollector:
    """Common interface. Subclasses gather one platform's sources."""

    platform_name = "unknown"

    def gather(self, window, *, include_command_lines=False, cancel=None, **overrides):
        raise NotImplementedError

    def collect(self, window, *, include_command_lines=False, cancel=None, **overrides) -> dict:
        sources, events = self.gather(
            window, include_command_lines=include_command_lines, cancel=cancel, **overrides
        )
        return finalize(self.platform_name, window, sources, events,
                        include_command_lines=include_command_lines)


class LinuxExecutionTelemetryCollector(ExecutionTelemetryCollector):
    platform_name = "Linux"

    def gather(self, window, *, include_command_lines=False, cancel=None, **overrides):
        return execution_linux.collect(
            window, include_command_lines=include_command_lines, cancel=cancel, **overrides
        )


class WindowsExecutionTelemetryCollector(ExecutionTelemetryCollector):
    platform_name = "Windows"

    def gather(self, window, *, include_command_lines=False, cancel=None, **overrides):
        return execution_windows.collect(
            window, include_command_lines=include_command_lines, cancel=cancel, **overrides
        )


class UnsupportedPlatformCollector(ExecutionTelemetryCollector):
    """Everything else. Says so, rather than returning a misleading empty set."""

    def __init__(self, name):
        self.platform_name = name

    def gather(self, window, *, include_command_lines=False, cancel=None, **overrides):
        return [source_record(
            "historical execution telemetry", NOT_AVAILABLE,
            detail=(f"JOCKY has no historical execution collector for {self.platform_name}. "
                    "No historical execution evidence was collected on this host."),
        )], []


def collector_for(name=None) -> ExecutionTelemetryCollector:
    name = name or platform_module.system()
    if name == "Linux":
        return LinuxExecutionTelemetryCollector()
    if name == "Windows":
        return WindowsExecutionTelemetryCollector()
    return UnsupportedPlatformCollector(name or "this platform")


def _sort_key(event):
    """Order by timestamp, with undated events last rather than dropped."""
    stamp = event.get("timestamp")
    if not stamp:
        return (1, "")
    return (0, stamp)


def finalize(platform_name, window, sources, events, *, include_command_lines=False) -> dict:
    """Bound, de-duplicate, order and summarise one platform's collection."""
    seen, unique, duplicates = set(), [], 0
    for event in sorted(events, key=_sort_key):
        key = (event.get("source"), event.get("source_record_id"))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if len(unique) >= MAX_TOTAL_EVENTS:
            break
        unique.append(event)

    truncated = len(events) - duplicates > MAX_TOTAL_EVENTS or any(s["truncated"] for s in sources)
    available = [s for s in sources if s["status"] == AVAILABLE]
    undated = sum(1 for event in unique if not event.get("timestamp"))

    warnings = [
        "HISTORICAL EVIDENCE: each event below is bounded by what its source actually records. "
        "Absence of an event is not evidence that a program did not run.",
    ]
    if not available:
        warnings.append(
            "No historical execution telemetry was available on this host. The investigation therefore "
            "rests on current observation only, which cannot establish what ran in the past."
        )
    if undated:
        warnings.append(
            f"{undated} events carry no timestamp because their source does not record one. They are "
            "ordered last and must not be read as the most recent activity."
        )
    if truncated:
        warnings.append("Historical collection hit its bounds; older or additional events were not read.")
    if not include_command_lines:
        warnings.append(
            "Command-line arguments were not collected from process telemetry. They frequently carry "
            "credentials; enable them explicitly per investigation when they are needed."
        )

    return {
        "action": "execution_history",
        "status": "success",
        "classification": HISTORICAL_EVIDENCE if available else NOT_COLLECTED,
        "platform": platform_name,
        "telemetry_available": bool(available),
        "window": window.to_dict(),
        "sources": sources,
        "events": unique,
        "event_count": len(unique),
        "duplicate_records_discarded": duplicates,
        "undated_event_count": undated,
        "truncated": truncated,
        "complete": not truncated,
        "limits": {
            "max_total_events": MAX_TOTAL_EVENTS,
            "max_events_per_source": execution_linux.MAX_EVENTS_PER_SOURCE,
            "max_journal_records": execution_linux.MAX_JOURNAL_RECORDS,
            "command_lines_collected": include_command_lines,
        },
        "statistics": {
            "sources_queried": len(sources),
            "sources_available": len(available),
            "events_by_source": {s["name"]: s["event_count"] for s in sources},
            "source_status": {s["name"]: s["status"] for s in sources},
        },
        "warnings": warnings,
        "collected_at": datetime.now().astimezone().isoformat(),
    }


def collect_execution_history(*, window_hours=None, include_command_lines=False, cancel=None,
                              platform_name=None, **overrides) -> dict:
    window = CollectionWindow.resolve(window_hours)
    return collector_for(platform_name).collect(
        window, include_command_lines=include_command_lines, cancel=cancel, **overrides
    )
