"""
Read-only memory-forensics integration.

JOCKY does not parse memory images itself. Mature tooling exists, is far better
at it, and writing another parser would be the wrong kind of work. This module
is the boundary: it locates an analysis tool, runs it read-only against an
image, and normalises whatever it returns into the same evidence model
everything else uses.

Strictly read-only. There is no memory writing, no injection, no process
manipulation and no code execution into a live process — the input is an image
file and the output is a list of observations.

Every result states its provenance as one of:

    REAL        an analysis tool ran against a real image
    FIXTURE     a recorded or synthetic result, for demonstration and tests
    UNAVAILABLE no tool and no fixture, so nothing was analysed
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .execution_linux import run_command
from .execution_model import AVAILABLE, NOT_AVAILABLE, source_record

REAL = "REAL"
FIXTURE = "FIXTURE"
UNAVAILABLE = "UNAVAILABLE"

MAX_PROCESSES = 2000
MAX_MODULES = 2000
MAX_MAPPINGS = 5000
ANALYSIS_TIMEOUT = 900

#: Tools JOCKY knows how to drive, in order of preference. Each is read-only
#: and takes an image path.
TOOLS = (
    {"name": "volatility3", "executable": "vol", "argv": ["-q", "-r", "json", "-f", "{image}",
                                                          "{plugin}"]},
    {"name": "volatility3", "executable": "vol.py", "argv": ["-q", "-r", "json", "-f", "{image}",
                                                             "{plugin}"]},
)

#: Plugins by what they produce, per platform. The profile of an image is not
#: known in advance, so JOCKY tries each platform's process listing and keeps
#: the first that returns rows -- which is also how it learns which platform the
#: image is, without having to be told.
PLUGINS = {
    "linux": {"processes": "linux.pslist.PsList", "modules": "linux.lsmod.Lsmod",
              "mappings": "linux.proc.Maps"},
    "windows": {"processes": "windows.pslist.PsList", "modules": "windows.modules.Modules",
                "mappings": "windows.vadinfo.VadInfo"},
}
PLATFORM_ORDER = ("linux", "windows")

#: How far a memory observation goes. A process listing is a direct read of
#: kernel structures; a mapping list is derived from them.
DIRECT = "Read directly from the image by the analysis tool."
DERIVED_FROM_IMAGE = ("Derived by the analysis tool from structures in the image, which depends on "
                      "its symbol table matching the kernel that produced the image.")


def plugin_for(platform, kind):
    return PLUGINS.get(platform, {}).get(kind)


def available_tool(finder=shutil.which):
    """The first supported memory-analysis tool present on this host."""
    for tool in TOOLS:
        path = finder(tool["executable"])
        if path:
            return {**tool, "path": path}
    return None


def _normalize_modules(rows, *, provenance, image, tool, plugin):
    """Kernel modules or loaded modules a memory plugin reported."""
    records = []
    for row in (rows or [])[:MAX_MODULES]:
        if not isinstance(row, dict):
            continue
        records.append({
            "name": row.get("Name") or row.get("name") or row.get("Module"),
            "path": row.get("Path") or row.get("path") or row.get("File"),
            "size_bytes": row.get("Size") or row.get("size"),
            "offset": row.get("Offset") or row.get("Offset(V)"),
            "base": row.get("Base"),
            "classification": "HISTORICAL_EVIDENCE",
            "source": f"memory analysis ({tool})",
            "source_plugin": plugin,
            "confidence": DIRECT,
            "provenance": provenance,
            "image": image,
            "raw": dict(row),
        })
    return records


def _normalize_mappings(rows, *, provenance, image, tool, plugin):
    """Memory regions a mapping plugin reported, per process."""
    records = []
    for row in (rows or [])[:MAX_MAPPINGS]:
        if not isinstance(row, dict):
            continue
        records.append({
            "pid": next((row[key] for key in ("PID", "pid") if row.get(key) is not None), None),
            "start": row.get("Start") or row.get("Start VPN") or row.get("Offset"),
            "end": row.get("End") or row.get("End VPN"),
            "permissions": row.get("Flags") or row.get("Protection") or row.get("Permissions"),
            "path": row.get("File Path") or row.get("FileName") or row.get("Path"),
            "classification": "HISTORICAL_EVIDENCE",
            "source": f"memory analysis ({tool})",
            "source_plugin": plugin,
            "confidence": DERIVED_FROM_IMAGE,
            "provenance": provenance,
            "image": image,
            "raw": dict(row),
        })
    return records


def _normalize_processes(rows, *, provenance, image, tool, plugin=None):
    """Map a tool's process list into JOCKY's evidence vocabulary."""
    records = []
    for row in rows[:MAX_PROCESSES]:
        if not isinstance(row, dict):
            continue
        # Volatility3 names this column differently per plugin: ImageFileName on
        # windows.pslist, COMM on linux.pslist, Name on mac.pslist.
        name = (row.get("ImageFileName") or row.get("COMM") or row.get("Name")
                or row.get("name") or row.get("process_name"))
        executable = (row.get("Path") or row.get("path") or row.get("EXE") or row.get("Exe")
                      or row.get("CommandLine") or None)
        records.append({
            "process_name": name,
            "pid": next((row[key] for key in ("PID", "pid") if row.get(key) is not None), None),
            # `or` would turn a real ppid of 0 into None; kernel roots have one.
            "parent_pid": next((row[key] for key in ("PPID", "ppid", "parent_pid")
                                if row.get(key) is not None), None),
            "user": str(row.get("UID")) if row.get("UID") is not None else None,
            "started_at": row.get("CREATE TIME") or row.get("start_time"),
            "executable": executable,
            "threads": row.get("THREADS") or row.get("Threads"),
            "offset": row.get("OFFSET (V)") or row.get("Offset(V)") or row.get("Offset"),
            "classification": "HISTORICAL_EVIDENCE",
            "source": f"memory analysis ({tool})",
            "source_plugin": plugin,
            "confidence": DIRECT,
            "provenance": provenance,
            "image": image,
            "evidence_strength": (
                "The process was resident in memory when the image was captured. That is a "
                "snapshot of the captured moment, not a record of when the process started or "
                "what it did."),
            "raw": {key: value for key, value in row.items() if key not in ("__children",)},
        })
    return records


def analyze_memory_image(image_path=None, *, fixture=None, runner=run_command,
                         finder=shutil.which, cancel=None, image_sha256=None,
                         evidence_source_id=None) -> dict:
    """Analyse a memory image, or normalise a fixture result.

    `fixture` is a recorded tool result. It exists so the whole pipeline —
    normalisation, evidence, correlation, findings — can be demonstrated and
    tested without a multi-gigabyte image, and it is labelled FIXTURE
    everywhere it appears.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled before memory analysis started")

    collected_at = datetime.now(timezone.utc).isoformat()

    if fixture is not None:
        rows = fixture.get("processes", []) if isinstance(fixture, dict) else list(fixture)
        label = (fixture.get("label") if isinstance(fixture, dict) else None) or "synthetic fixture"
        processes = _normalize_processes(rows, provenance=FIXTURE, image=str(image_path or label),
                                         tool=label, plugin=fixture.get("plugin")
                                         if isinstance(fixture, dict) else None)
        modules = _normalize_modules(
            fixture.get("modules") if isinstance(fixture, dict) else [], provenance=FIXTURE,
            image=str(image_path or label), tool=label, plugin=None)
        mappings = _normalize_mappings(
            fixture.get("mappings") if isinstance(fixture, dict) else [], provenance=FIXTURE,
            image=str(image_path or label), tool=label, plugin=None)
        return _result(
            provenance=FIXTURE, processes=processes, modules=modules, mappings=mappings,
            image=str(image_path or label), tool=label,
            image_sha256=image_sha256, evidence_source_id=evidence_source_id,
            collected_at=collected_at,
            sources=[source_record("memory analysis", AVAILABLE, location=str(image_path or label),
                                   detail=("A recorded or synthetic analysis result. This is "
                                           "SYNTHETIC/LAB evidence and is not a real memory "
                                           "capture."),
                                   event_count=len(processes))],
            warnings=["SYNTHETIC: this result did not come from a real memory image."])

    if not image_path:
        return _result(
            provenance=UNAVAILABLE, processes=[], image=None, tool=None, collected_at=collected_at,
            image_sha256=image_sha256, evidence_source_id=evidence_source_id,
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=None,
                                   detail="No memory image was supplied to analyse.")],
            warnings=["No memory image was supplied, so no memory evidence was collected."])

    image = Path(image_path)
    if not image.is_file():
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=None,
            collected_at=collected_at, image_sha256=image_sha256,
            evidence_source_id=evidence_source_id,
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=str(image),
                                   detail="The memory image does not exist at that path.")],
            warnings=[f"No memory image at {image}."])

    tool = available_tool(finder)
    if not tool:
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=None,
            collected_at=collected_at, image_sha256=image_sha256,
            evidence_source_id=evidence_source_id,
            sources=[source_record(
                "memory analysis", NOT_AVAILABLE, location=str(image),
                detail=("No supported memory-analysis tool is installed. JOCKY drives existing "
                        "read-only tooling rather than parsing images itself; install one to "
                        "analyse this image."))],
            warnings=["No memory-analysis tool is available on this host."])

    def run_plugin(plugin):
        argv = [tool["path"]] + [part.format(image=str(image), plugin=plugin)
                                 for part in tool["argv"]]
        status, output = runner(argv, timeout=ANALYSIS_TIMEOUT)
        if status != AVAILABLE:
            return status, None
        try:
            parsed = json.loads(output)
        except ValueError:
            return "UNPARSEABLE", None
        return AVAILABLE, parsed if isinstance(parsed, list) else parsed.get("rows", [])

    # The image's platform is not known in advance, so each platform's process
    # listing is tried and the first that returns rows settles it. That is also
    # cheaper than asking the investigator to tell JOCKY something the image
    # already knows.
    detected, rows, attempts = None, None, []
    for candidate in PLATFORM_ORDER:
        plugin = plugin_for(candidate, "processes")
        status, result = run_plugin(plugin)
        attempts.append({"platform": candidate, "plugin": plugin, "status": status,
                         "rows": len(result) if result else 0})
        if status == AVAILABLE and result:
            detected, rows = candidate, result
            break

    if detected is None:
        detail = "; ".join(f"{item['plugin']} -> {item['status']}" for item in attempts)
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=tool["name"],
            collected_at=collected_at, plugins={"attempts": attempts},
            image_sha256=image_sha256, evidence_source_id=evidence_source_id,
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=str(image),
                                   detail=(f"{tool['name']} produced no usable process listing. "
                                           f"Attempts: {detail}"))],
            warnings=[f"{tool['name']} did not produce a process listing for this image."])

    plugins = {"processes": plugin_for(detected, "processes")}
    processes = _normalize_processes(rows, provenance=REAL, image=str(image), tool=tool["name"],
                                     plugin=plugins["processes"])

    # Modules and mappings are additional reads. A plugin that is unavailable
    # for this image is a gap in the result, not a failure of the analysis.
    modules, mappings = [], []
    for kind, normalize in (("modules", _normalize_modules), ("mappings", _normalize_mappings)):
        plugin = plugin_for(detected, kind)
        if not plugin:
            continue
        status, result = run_plugin(plugin)
        plugins[kind] = plugin
        if status == AVAILABLE and result:
            records = normalize(result, provenance=REAL, image=str(image), tool=tool["name"],
                                plugin=plugin)
            if kind == "modules":
                modules = records
            else:
                mappings = records
        else:
            attempts.append({"platform": detected, "plugin": plugin, "status": status, "rows": 0})

    warnings = []
    if not modules:
        warnings.append("No loaded-module listing was produced for this image.")
    if not mappings:
        warnings.append("No memory-mapping listing was produced for this image.")

    return _result(
        provenance=REAL, processes=processes, modules=modules, mappings=mappings,
        image=str(image), tool=tool["name"], platform=detected,
        plugins={**plugins, "attempts": attempts}, image_sha256=image_sha256,
        evidence_source_id=evidence_source_id, collected_at=collected_at,
        sources=[source_record("memory analysis", AVAILABLE, location=str(image),
                               detail=(f"{tool['name']} analysed the image read-only as a "
                                       f"{detected} image."),
                               event_count=len(processes))],
        warnings=warnings)


def _result(*, provenance, processes, image, tool, collected_at, sources, warnings,
            modules=(), mappings=(), platform=None, plugins=None, image_sha256=None,
            evidence_source_id=None):
    modules, mappings = list(modules), list(mappings)
    return {
        "action": "memory_analysis",
        "status": "success",
        "provenance": provenance,
        "classification": "HISTORICAL_EVIDENCE" if processes else "UNAVAILABLE",
        "image": image,
        "image_sha256": image_sha256,
        "evidence_source_id": evidence_source_id,
        "platform": platform,
        "plugins": plugins or {},
        "tool": tool,
        "processes": processes,
        "modules": modules,
        "mappings": mappings,
        "sources": sources,
        "statistics": {"processes": len(processes), "modules": len(modules),
                       "mappings": len(mappings)},
        "limits": {"max_processes": MAX_PROCESSES, "read_only": True,
                   "memory_written": False, "code_executed": False},
        "truncated": len(processes) >= MAX_PROCESSES,
        "complete": provenance in (REAL, FIXTURE),
        "warnings": warnings + [
            "Read-only analysis. JOCKY never writes memory, injects into a process, or executes "
            "code in one.",
            "A memory image is a snapshot of one moment. It shows what was resident then, not "
            "what ran before or after.",
        ],
        "collected_at": collected_at,
    }
