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
ANALYSIS_TIMEOUT = 900

#: Tools JOCKY knows how to drive, in order of preference. Each is read-only
#: and takes an image path.
TOOLS = (
    {"name": "volatility3", "executable": "vol", "argv": ["-q", "-r", "json", "-f", "{image}",
                                                          "linux.pslist.PsList"]},
    {"name": "volatility3", "executable": "vol.py", "argv": ["-q", "-r", "json", "-f", "{image}",
                                                             "linux.pslist.PsList"]},
)


def available_tool(finder=shutil.which):
    """The first supported memory-analysis tool present on this host."""
    for tool in TOOLS:
        path = finder(tool["executable"])
        if path:
            return {**tool, "path": path}
    return None


def _normalize_processes(rows, *, provenance, image, tool):
    """Map a tool's process list into JOCKY's evidence vocabulary."""
    records = []
    for row in rows[:MAX_PROCESSES]:
        if not isinstance(row, dict):
            continue
        # Volatility3 names this column differently per plugin: ImageFileName on
        # windows.pslist, COMM on linux.pslist, Name on mac.pslist.
        name = (row.get("ImageFileName") or row.get("COMM") or row.get("Name")
                or row.get("name") or row.get("process_name"))
        records.append({
            "process_name": name,
            "pid": next((row[key] for key in ("PID", "pid") if row.get(key) is not None), None),
            # `or` would turn a real ppid of 0 into None; kernel roots have one.
            "parent_pid": next((row[key] for key in ("PPID", "ppid", "parent_pid")
                                if row.get(key) is not None), None),
            "user": str(row.get("UID")) if row.get("UID") is not None else None,
            "started_at": row.get("CREATE TIME") or row.get("start_time"),
            "classification": "HISTORICAL_EVIDENCE",
            "source": f"memory analysis ({tool})",
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
                         finder=shutil.which, cancel=None) -> dict:
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
                                         tool=label)
        return _result(
            provenance=FIXTURE, processes=processes, image=str(image_path or label), tool=label,
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
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=None,
                                   detail="No memory image was supplied to analyse.")],
            warnings=["No memory image was supplied, so no memory evidence was collected."])

    image = Path(image_path)
    if not image.is_file():
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=None,
            collected_at=collected_at,
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=str(image),
                                   detail="The memory image does not exist at that path.")],
            warnings=[f"No memory image at {image}."])

    tool = available_tool(finder)
    if not tool:
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=None,
            collected_at=collected_at,
            sources=[source_record(
                "memory analysis", NOT_AVAILABLE, location=str(image),
                detail=("No supported memory-analysis tool is installed. JOCKY drives existing "
                        "read-only tooling rather than parsing images itself; install one to "
                        "analyse this image."))],
            warnings=["No memory-analysis tool is available on this host."])

    argv = [tool["path"]] + [part.format(image=str(image)) for part in tool["argv"]]
    status, output = runner(argv, timeout=ANALYSIS_TIMEOUT)
    if status != AVAILABLE:
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=tool["name"],
            collected_at=collected_at,
            sources=[source_record("memory analysis", status, location=str(image),
                                   detail=f"{tool['name']} could not analyse the image.")],
            warnings=[f"{tool['name']} did not complete; no memory evidence was produced."])

    try:
        rows = json.loads(output)
    except ValueError:
        return _result(
            provenance=UNAVAILABLE, processes=[], image=str(image), tool=tool["name"],
            collected_at=collected_at,
            sources=[source_record("memory analysis", NOT_AVAILABLE, location=str(image),
                                   detail=f"{tool['name']} produced output JOCKY could not parse.")],
            warnings=["The memory-analysis tool's output could not be parsed."])

    processes = _normalize_processes(rows if isinstance(rows, list) else rows.get("rows", []),
                                     provenance=REAL, image=str(image), tool=tool["name"])
    return _result(
        provenance=REAL, processes=processes, image=str(image), tool=tool["name"],
        collected_at=collected_at,
        sources=[source_record("memory analysis", AVAILABLE, location=str(image),
                               detail=f"{tool['name']} analysed the image read-only.",
                               event_count=len(processes))],
        warnings=[])


def _result(*, provenance, processes, image, tool, collected_at, sources, warnings):
    return {
        "action": "memory_analysis",
        "status": "success",
        "provenance": provenance,
        "classification": "HISTORICAL_EVIDENCE" if processes else "UNAVAILABLE",
        "image": image,
        "tool": tool,
        "processes": processes,
        "sources": sources,
        "statistics": {"processes": len(processes)},
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
