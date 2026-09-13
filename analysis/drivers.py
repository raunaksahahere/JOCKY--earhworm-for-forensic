"""
Driver inventory and risk verification.

Verification only. This module reads which drivers or kernel modules are
present, normalises their metadata, and compares them against a reference of
drivers documented as vulnerable or malicious. It never loads, unloads,
modifies, disables or exploits a driver, and it never executes anything in
kernel space — a match is a reason for an investigator to look, stated with its
source and its matching criterion.

On Linux the inventory is the loaded kernel modules. On Windows it would be the
driver files themselves; that path is implemented against the same normalised
model but has not been run on a real Windows host.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .execution_model import AVAILABLE, NOT_AVAILABLE, PERMISSION_DENIED, source_record

REFERENCE_PATH = Path(__file__).resolve().parent / "data" / "driver_risk_reference.json"
MAX_MODULES = 2000

MATCHED = "MATCHED"
NOT_MATCHED = "NOT_MATCHED"
UNKNOWN = "UNKNOWN"

_reference_cache = None


def load_reference(path: Path | str = REFERENCE_PATH) -> dict:
    """The known-risk reference, indexed by name and by digest.

    Loaded once and cached: it is a few hundred kilobytes and every driver in an
    inventory is checked against it.
    """
    global _reference_cache
    if _reference_cache is not None and _reference_cache["path"] == str(path):
        return _reference_cache
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _reference_cache = {"path": str(path), "available": False, "detail": str(error),
                            "by_name": {}, "by_hash": {}, "entry_count": 0, "source": None}
        return _reference_cache
    by_name, by_hash = {}, {}
    for entry in data.get("entries", []):
        for name in entry.get("names", []):
            by_name.setdefault(name.lower(), []).append(entry)
        for digest in entry.get("sha256", []):
            by_hash[digest.lower()] = entry
    _reference_cache = {
        "path": str(path), "available": True, "by_name": by_name, "by_hash": by_hash,
        "entry_count": data.get("entry_count", len(data.get("entries", []))),
        "name": data.get("name"), "source": data.get("source"),
        "description": data.get("description"), "version": data.get("reference_version"),
    }
    return _reference_cache


def verify_driver(driver: dict, reference: dict | None = None) -> dict:
    """Compare one driver against the reference, and say how it was matched.

    A digest match is the strong one: it identifies the exact bytes. A filename
    match only says the name is shared with a documented driver, which a benign
    file can be, so it is reported with lower confidence and says so.
    """
    reference = reference or load_reference()
    if not reference["available"]:
        return {"risk_status": UNKNOWN, "matched_on": None, "confidence": "none",
                "detail": "The known-risk reference could not be loaded, so no comparison was made.",
                "reference": None}

    digest = (driver.get("sha256") or "").lower()
    if digest and digest in reference["by_hash"]:
        entry = reference["by_hash"][digest]
        return {
            "risk_status": MATCHED, "matched_on": "sha256", "confidence": "high",
            "detail": ("The driver's SHA-256 digest matches a driver documented as "
                       f"{entry.get('category', 'known-risk')}. The digest identifies the exact "
                       "bytes, so this is an identification rather than a resemblance."),
            "reference": {"id": entry.get("id"), "category": entry.get("category"),
                          "mitre_id": entry.get("mitre_id"), "source": reference["source"]},
        }

    name = (driver.get("name") or driver.get("filename") or "").lower()
    # The reference documents Windows drivers. A Linux kernel module that
    # happens to share a bare name with one -- `msr` against `msr.sys` -- is a
    # coincidence, not evidence, and reporting it as a match is noise an
    # investigator has to disprove. Only compare names when the record is
    # actually a Windows-style driver file.
    windows_style = name.endswith((".sys", ".exe")) or driver.get("kind") == "windows_driver"
    candidates = (name,) if windows_style else ()
    for candidate in candidates:
        if candidate and candidate in reference["by_name"]:
            entry = reference["by_name"][candidate][0]
            return {
                "risk_status": MATCHED, "matched_on": "filename", "confidence": "low",
                "detail": (f"The driver's name matches '{candidate}', documented as "
                           f"{entry.get('category', 'known-risk')}. A name is not an "
                           "identification: an unrelated file can carry the same name, and the "
                           "digest did not match. Verify the file itself before concluding "
                           "anything."),
                "reference": {"id": entry.get("id"), "category": entry.get("category"),
                              "mitre_id": entry.get("mitre_id"), "source": reference["source"]},
            }

    if not digest:
        detail = ("No digest was available for this driver, so only its name could be compared, "
                  "and the name did not match the reference.")
        if not windows_style:
            detail = ("No digest was available, and the known-risk reference documents Windows "
                      "driver files. A kernel module's bare name is not comparable against it, so "
                      "nothing was concluded about this module.")
        return {"risk_status": UNKNOWN, "matched_on": None, "confidence": "none",
                "detail": detail, "reference": None}
    return {"risk_status": NOT_MATCHED, "matched_on": None, "confidence": "medium",
            "detail": ("Neither the digest nor the name matches the known-risk reference. The "
                       "reference covers documented drivers only; absence from it is not a "
                       "statement that the driver is safe."),
            "reference": None}


def _linux_modules(path="/proc/modules", limit=MAX_MODULES):
    """Loaded kernel modules, read from proc rather than by running a tool."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return [], source_record("loaded kernel modules", NOT_AVAILABLE, location=path,
                                 detail="This host exposes no module list.")
    except PermissionError:
        return [], source_record("loaded kernel modules", PERMISSION_DENIED, location=path,
                                 detail="The module list is not readable.")
    except OSError as error:
        return [], source_record("loaded kernel modules", NOT_AVAILABLE, location=path,
                                 detail=str(error))

    modules = []
    for line in lines[:limit]:
        fields = line.split()
        if len(fields) < 4:
            continue
        name, size, used_by = fields[0], fields[1], fields[3]
        modules.append({
            "name": name,
            "kind": "kernel_module",
            "size_bytes": int(size) if size.isdigit() else None,
            "used_by": None if used_by == "-" else used_by.strip(","),
            "path": None,
            "sha256": None,
            "signed": None,
            "classification": "CURRENT_OBSERVATION",
            "source": path,
            "evidence_strength": ("The module is loaded now. Its on-disk file was not hashed, so "
                                  "only its name could be compared against the reference."),
        })
    return modules, source_record("loaded kernel modules", AVAILABLE, location=path,
                                  detail=f"{len(modules)} modules loaded.",
                                  event_count=len(modules))


def collect_driver_inventory(cancel=None, *, modules_path="/proc/modules",
                             reference_path=REFERENCE_PATH, extra_drivers=()) -> dict:
    """Inventory the drivers present and verify each against the reference.

    `extra_drivers` accepts already-normalised driver records — a Windows
    inventory, or a fixture — so the same verification runs over evidence this
    host did not produce.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled before the driver inventory was read")

    reference = load_reference(reference_path)
    modules, module_source = _linux_modules(modules_path)
    drivers = list(modules) + [dict(driver) for driver in extra_drivers]

    matched = []
    for driver in drivers:
        driver["verification"] = verify_driver(driver, reference)
        if driver["verification"]["risk_status"] == MATCHED:
            matched.append(driver)

    reference_source = source_record(
        "known-risk driver reference",
        AVAILABLE if reference["available"] else NOT_AVAILABLE,
        location=str(reference_path),
        detail=(f"{reference['entry_count']} documented drivers from {reference.get('source')}."
                if reference["available"] else reference.get("detail", "unavailable")),
        event_count=reference.get("entry_count", 0))

    warnings = [
        "Verification only. JOCKY never loads, unloads, modifies, disables or exploits a driver.",
        "Absence from the reference is not a statement that a driver is safe; the reference "
        "covers documented drivers only.",
    ]
    if modules and not any(driver.get("sha256") for driver in modules):
        warnings.append(
            "Loaded kernel modules were compared by name only. Their on-disk files were not "
            "hashed, so a name match is a resemblance rather than an identification.")
    if not reference["available"]:
        warnings.append("The known-risk reference could not be loaded; nothing was compared.")

    return {
        "action": "driver_inventory",
        "status": "success",
        "classification": "CURRENT_OBSERVATION",
        "drivers": drivers,
        "matched": matched,
        "sources": [module_source, reference_source],
        "reference": {"name": reference.get("name"), "source": reference.get("source"),
                      "version": reference.get("version"),
                      "entry_count": reference.get("entry_count", 0),
                      "available": reference["available"]},
        "statistics": {
            "drivers_inventoried": len(drivers),
            "matched": len(matched),
            "not_matched": sum(1 for driver in drivers
                               if driver["verification"]["risk_status"] == NOT_MATCHED),
            "unknown": sum(1 for driver in drivers
                           if driver["verification"]["risk_status"] == UNKNOWN),
        },
        "limits": {"max_modules": MAX_MODULES, "drivers_loaded_or_modified": False},
        "truncated": len(modules) >= MAX_MODULES,
        "complete": module_source["status"] == AVAILABLE and reference["available"],
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
