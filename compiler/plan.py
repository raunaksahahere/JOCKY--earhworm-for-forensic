"""
IR to platform execution plan.

The language says *what* an investigation needs. An adapter says *how* one
operating system provides it. Keeping those apart is what lets the same program
produce a Linux plan today and a Windows plan later without the program, the
parser or the IR changing.

An adapter never receives a command to run. It receives a source name and
bounded options, and answers with named collector tasks that JOCKY already
implements. There is no path from a program to an arbitrary execution.
"""

from __future__ import annotations

import platform as platform_module

from .investigation import ProgramError, validate_ir

PLAN_VERSION = 1

UNSUPPORTED = "UNSUPPORTED"
REQUIRES_ARGUMENT = "REQUIRES_ARGUMENT"
READY = "READY"


class PlatformAdapter:
    """One operating system's answer to the IR's requests."""

    name = "unknown"
    #: source -> (collector task name, capability)
    supported: dict = {}
    #: source -> why this platform does not collect it, where there is more to
    #: say than "no collector". An investigator reading a skipped source should
    #: learn where that evidence does come from, if it comes from anywhere.
    unsupported_reasons: dict = {}

    def task_for(self, collection: dict) -> dict:
        source = collection["source"]
        if source not in self.supported:
            return {
                "collection_id": collection["id"], "source": source, "status": UNSUPPORTED,
                "detail": self.unsupported_reasons.get(
                    source, f"{self.name} has no collector for {source} in this build."),
            }
        collector, capability = self.supported[source]
        return {
            "collection_id": collection["id"],
            "source": source,
            "status": READY,
            "collector": collector,
            "capability": capability,
            "arguments": list(collection["arguments"]),
            "options": dict(collection["options"]),
        }


class LinuxAdapter(PlatformAdapter):
    """The real adapter. Every collector named here exists and is tested."""

    name = "linux"
    supported = {
        "SYSTEM": ("analysis.system.get_system_info", "collect.system"),
        "PROCESSES": ("backend.collectors.process_snapshot", "collect.processes"),
        "EXECUTION": ("analysis.execution_history.collect_execution_history", "collect.execution"),
        "FILES": ("analysis.artifacts.collect_artifacts", "collect.files"),
        "NETWORK": ("analysis.network.collect_network", "collect.network"),
        "BROWSER": ("analysis.browser.collect_browser_artifacts", "collect.browser"),
        "USB": ("analysis.usb.collect_removable_media", "collect.usb"),
        "DRIVERS": ("analysis.drivers.collect_driver_inventory", "collect.drivers"),
        "MEMORY": ("analysis.memory.analyze_memory_image", "collect.memory"),
        "SERVICES": ("analysis.system_services.collect_services", "collect.services"),
    }
    # LOGS is absent deliberately. The system journal is already read as part of
    # EXECUTION, and offering it separately would promise a collection this
    # build does not perform on its own. A program asking for it gets a named
    # UNSUPPORTED task saying where the evidence actually comes from.
    unsupported_reasons = {
        "LOGS": ("The system journal is collected as part of EXECUTION on Linux; there is no "
                 "separate LOGS collector in this build."),
    }


class WindowsAdapter(PlatformAdapter):
    """Interface and mapping only.

    The collectors named here exist and are fixture-tested, but no plan produced
    by this adapter has been executed against a real Windows host. It is listed
    so the IR stays platform-neutral and so the gap is visible rather than
    implied.
    """

    name = "windows"
    validated = False
    supported = {
        "SYSTEM": ("analysis.system.get_system_info", "collect.system"),
        "PROCESSES": ("backend.collectors.process_snapshot", "collect.processes"),
        "EXECUTION": ("analysis.execution_history.collect_execution_history", "collect.execution"),
        "FILES": ("analysis.artifacts.collect_artifacts", "collect.files"),
        "NETWORK": ("analysis.network.collect_network", "collect.network"),
        "MEMORY": ("analysis.memory.analyze_memory_image", "collect.memory"),
    }


ADAPTERS = {"linux": LinuxAdapter(), "windows": WindowsAdapter()}


def adapter_for(name: str | None = None) -> PlatformAdapter:
    key = (name or platform_module.system()).lower()
    if key not in ADAPTERS:
        raise ProgramError(f"No platform adapter for '{key}'")
    return ADAPTERS[key]


def build_plan(ir: dict, *, platform_name: str | None = None) -> dict:
    """Compile validated IR into one platform's execution plan.

    A source the platform cannot provide becomes an UNSUPPORTED task rather than
    an error: an investigator is better served by a plan that runs what it can
    and says plainly what it could not, than by a refusal.
    """
    validate_ir(ir)
    adapter = adapter_for(platform_name)

    for target in ir["targets"]:
        constraint = target.get("platform", "any")
        if constraint not in ("any", adapter.name):
            raise ProgramError(
                f"Target '{target['name']}' requires platform {constraint}, "
                f"but this plan is being built for {adapter.name}")

    tasks = [adapter.task_for(collection) for collection in ir["collections"]]
    ready = [task for task in tasks if task["status"] == READY]
    unsupported = [task for task in tasks if task["status"] == UNSUPPORTED]

    return {
        "plan_version": PLAN_VERSION,
        "ir_version": ir["ir_version"],
        "platform": adapter.name,
        "platform_validated": getattr(adapter, "validated", True),
        "case_id": ir["case"]["id"],
        "targets": ir["targets"],
        "window_hours": ir.get("window_hours"),
        "tasks": tasks,
        "ready_task_count": len(ready),
        "unsupported": [
            {"collection_id": task["collection_id"], "source": task["source"],
             "detail": task["detail"]} for task in unsupported],
        "filters": ir["filters"],
        "correlations": ir["correlations"],
        "timeline": ir["timeline"],
        "reports": ir["reports"],
        "capabilities_required": sorted({task["capability"] for task in ready}),
        "note": ("A plan names collectors JOCKY implements and bounded options. It never carries "
                 "a command to run."),
    }


def describe_plan(plan: dict) -> str:
    lines = [f"JOCKY execution plan v{plan['plan_version']} for {plan['platform']}"
             + ("" if plan["platform_validated"] else "  (NOT VALIDATED ON A REAL HOST)"),
             f"  case    {plan['case_id']}",
             f"  targets {', '.join(target['name'] for target in plan['targets'])}"]
    for task in plan["tasks"]:
        if task["status"] == READY:
            arguments = " ".join(str(argument) for argument in task["arguments"])
            lines.append(f"  task    {task['collection_id']} {task['source']:10s} "
                         f"-> {task['collector']} {arguments}".rstrip())
        else:
            lines.append(f"  skip    {task['collection_id']} {task['source']:10s} "
                         f"-> {task['status']}: {task['detail']}")
    return "\n".join(lines)
