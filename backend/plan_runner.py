"""
Execution of a compiled plan against the local host.

The single most important property of this module is that a plan cannot name
code that JOCKY did not already choose to expose. The registry below is the
complete list of things a plan can cause to happen. A plan task carries a
dotted collector path for the record, and that path is *checked against* the
registry rather than imported from it -- resolving it dynamically would turn the
investigation language into an arbitrary-code loader, which is exactly the
property a forensic tool must not have.

Everything here observes. Nothing here changes the host.
"""

from __future__ import annotations

import logging

from analysis.artifacts import collect_artifacts
from analysis.browser import collect_browser_artifacts
from analysis.drivers import collect_driver_inventory
from analysis.memory import analyze_memory_image
from analysis.network import collect_network
from analysis.system_services import collect_services
from analysis.execution_history import collect_execution_history
from analysis.system import get_system_info
from analysis.usb import collect_removable_media
from backend.collectors import process_snapshot
from compiler.plan import READY

#: source -> (callable, dotted path the plan must agree with, evidence action)
#:
#: This is the complete list of what any plan can cause to happen, locally or on
#: an enrolled endpoint.
REGISTRY = {
    "SYSTEM": (get_system_info, "analysis.system.get_system_info", "SYSTEM INFO"),
    "PROCESSES": (process_snapshot, "backend.collectors.process_snapshot", "PROCESSES"),
    "EXECUTION": (collect_execution_history,
                  "analysis.execution_history.collect_execution_history", "EXECUTION HISTORY"),
    "FILES": (collect_artifacts, "analysis.artifacts.collect_artifacts", "ARTIFACTS"),
    "NETWORK": (collect_network, "analysis.network.collect_network", "NETWORK"),
    "BROWSER": (collect_browser_artifacts, "analysis.browser.collect_browser_artifacts", "BROWSER"),
    "USB": (collect_removable_media, "analysis.usb.collect_removable_media", "USB"),
    "DRIVERS": (collect_driver_inventory, "analysis.drivers.collect_driver_inventory", "DRIVERS"),
    "MEMORY": (analyze_memory_image, "analysis.memory.analyze_memory_image", "MEMORY"),
    "SERVICES": (collect_services, "analysis.system_services.collect_services", "SERVICES"),
}

#: Sources the local collector always runs itself, in a fixed order, before any
#: program-selected source. A program can ask for more evidence but can never
#: leave the report without the evidence it is built from, so these are skipped
#: when running a plan locally and collected normally on an endpoint.
BASELINE = ("SYSTEM", "PROCESSES", "EXECUTION", "FILES")

SOURCE_DESCRIPTIONS = {
    "SYSTEM": "local operating system",
    "PROCESSES": "psutil current process snapshot",
    "EXECUTION": "documented operating system execution telemetry",
    "FILES": "files referenced by historical execution evidence",
    "NETWORK": "local network configuration and socket table",
    "BROWSER": "local browser history and download records",
    "USB": "removable media identity, kernel attach events and mounts",
    "DRIVERS": "loaded kernel modules checked against a known-abused reference",
    "MEMORY": "memory image analysis (read-only)",
    "SERVICES": "service units and scheduled jobs",
}

#: Sources that read an investigator-supplied artefact rather than the live host.
NEEDS_ARGUMENT = {"MEMORY"}

#: Collectors that complete in one bounded read and take no cancellation token.
UNCANCELLABLE = {"SYSTEM"}


def selectable_sources() -> list:
    """Sources an investigator may add to a local collection on this build."""
    return sorted(set(REGISTRY) - set(BASELINE))


def endpoint_sources() -> list:
    """Sources an enrolled endpoint can collect. Endpoints have no baseline."""
    return sorted(REGISTRY)


def _arguments(source, task, options):
    """Bounded keyword arguments for one collector.

    Options come from a validated IR, but this is the boundary where they become
    real call arguments, so each collector's inputs are named explicitly. A
    collector never receives the option dictionary wholesale.
    """
    window = options.get("window_hours")
    if source == "EXECUTION":
        return {"window_hours": window,
                "include_command_lines": bool(options.get("include_command_lines"))}
    if source == "PROCESSES":
        return {"include_command_lines": bool(options.get("include_command_lines"))}
    if source == "FILES":
        # COLLECT FILES names absolute paths in the program, and validation has
        # already rejected relative ones.
        return {"selected_paths": tuple(task.get("arguments") or ())}
    if source == "SYSTEM":
        return {}
    if source == "BROWSER":
        return {"window_hours": window}
    if source == "USB":
        return {}
    if source == "MEMORY":
        arguments = task.get("arguments") or []
        return {"image_path": arguments[0] if arguments else None}
    return {}


def runnable_tasks(plan: dict, *, skip_baseline=True) -> list:
    """Plan tasks this build can actually execute, with their callables.

    A READY task naming a collector the registry does not recognise is dropped
    with a warning rather than run. That can only happen if a plan and this
    build disagree, and in that case refusing is the honest answer -- but it is
    never a silent one: a task the plan promised and this build cannot keep is
    the kind of gap an investigator has to be told about.
    """
    runnable = []
    for task in plan.get("tasks", []):
        if task.get("status") != READY:
            continue
        if skip_baseline and task["source"] in BASELINE:
            continue
        entry = REGISTRY.get(task["source"])
        if entry is None:
            logging.warning(
                "Plan task %s names source %s, which this build has no collector for. "
                "Nothing was collected for it and nothing is claimed about it.",
                task.get("collection_id"), task["source"])
            continue
        function, dotted, action = entry
        if task.get("collector") != dotted:
            logging.warning("Plan task %s names %s for %s; this build provides %s. Task refused.",
                            task.get("collection_id"), task.get("collector"), task["source"], dotted)
            continue
        runnable.append({"task": task, "function": function, "action": action,
                         "source_description": SOURCE_DESCRIPTIONS[task["source"]]})
    return runnable


def call(entry: dict, *, options: dict, cancel=None):
    """Invoke one registered collector with bounded arguments."""
    task = entry["task"]
    arguments = _arguments(task["source"], task, options)
    if task["source"] in NEEDS_ARGUMENT and not arguments.get("image_path"):
        return {"status": "success", "classification": "UNAVAILABLE",
                "source_status": "NOT_COLLECTED",
                "warnings": [f"{task['source']} was requested without an image to analyse. "
                             "Nothing was collected and nothing is claimed."]}
    if task["source"] in UNCANCELLABLE:
        return entry["function"](**arguments)
    return entry["function"](cancel=cancel, **arguments)
