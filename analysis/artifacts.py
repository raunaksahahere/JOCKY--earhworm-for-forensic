"""
Bounded artifact collection driven by evidence, not by scanning the disk.

Artifacts come from two places only: paths the investigator selected
explicitly, and executables named by historical execution evidence. There is no
whole-disk sweep and no unbounded recursion -- a collector that wanders the
filesystem is both a performance hazard and a privacy one.

Everything here reuses the existing primitives: `hashing.hash_file` for the
digest, structural integrity check and ledger comparison, and
`indicators.evaluate_filename` for triage labels.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from . import hashing
from .indicators import evaluate_filename

MAX_ARTIFACTS = 200
MAX_HASH_BYTES = 128 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 200

COLLECTED = "COLLECTED"
MISSING = "MISSING"
PERMISSION_DENIED = "PERMISSION_DENIED"
SKIPPED_TOO_LARGE = "SKIPPED_TOO_LARGE"
NOT_A_FILE = "NOT_A_FILE"

# Directories where an executing image is worth an analyst's attention. These
# are ordinary writable/temporary locations, not a malware verdict: plenty of
# legitimate software runs from them.
NOTABLE_LOCATIONS = {
    "posix": ("/tmp/", "/var/tmp/", "/dev/shm/", "/run/shm/"),
    "nt": ("\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\", "\\downloads\\",
           "\\users\\public\\", "\\programdata\\", "\\$recycle.bin\\"),
}


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def notable_location(path: str | None) -> str | None:
    """Name the writable/temporary directory an image sits in, if any.

    Both platforms' patterns are checked so a Windows path recorded by Windows
    telemetry is still recognised when the report is read elsewhere. The most
    specific match wins: "\\AppData\\Local\\Temp\\" is more informative than the
    "\\Temp\\" that also matches it.
    """
    if not path:
        return None
    lowered = path.replace("\\", "/").lower()
    best = None
    for patterns in NOTABLE_LOCATIONS.values():
        for pattern in patterns:
            needle = pattern.replace("\\", "/").lower()
            if needle in lowered and (best is None or len(needle) > len(best[0])):
                best = (needle, pattern.strip("\\/"))
    return best[1] if best else None


def observe_artifact(path, *, source, cancel=None) -> dict:
    """Metadata, hash, indicators and integrity for one path.

    A path that is absent or unreadable still produces a record: "the evidence
    named this file and it is not here" is a finding, not a gap to hide.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled between artifact observations")
    absolute = os.path.abspath(path)
    filename = os.path.basename(absolute) or absolute
    record = {
        "path": absolute,
        "filename": filename,
        "extension": os.path.splitext(filename)[1].lower() or None,
        "source": source,
        "size_bytes": None,
        "modified": None,
        "created": None,
        "metadata_changed": None,
        "hash": None,
        "hash_algorithm": None,
        "collection_status": COLLECTED,
        "indicators": evaluate_filename(filename),
        "integrity": None,
        "integrity_history": None,
        "previous_hash": None,
        "notable_location": notable_location(absolute),
        "classification": "OBSERVED",
        "unavailable": {},
    }
    try:
        stat = os.stat(absolute)
    except FileNotFoundError:
        record.update(collection_status=MISSING, classification="UNAVAILABLE")
        record["unavailable"]["file"] = "the path named by the evidence does not exist at collection time"
        return record
    except PermissionError:
        record.update(collection_status=PERMISSION_DENIED, classification="UNAVAILABLE")
        record["unavailable"]["file"] = "the path exists but its metadata could not be read"
        return record
    except OSError as error:
        record.update(collection_status=PERMISSION_DENIED, classification="UNAVAILABLE")
        record["unavailable"]["file"] = f"the path could not be inspected: {error.strerror or error}"
        return record

    record["size_bytes"] = stat.st_size
    record["modified"] = _iso(stat.st_mtime)
    record["metadata_changed"] = _iso(stat.st_ctime)
    birth = getattr(stat, "st_birthtime", None)
    if birth:
        record["created"] = _iso(birth)
    else:
        record["unavailable"]["created"] = "this filesystem does not expose a creation time"

    if not os.path.isfile(absolute):
        record.update(collection_status=NOT_A_FILE)
        record["unavailable"]["hash"] = "the path is a directory or special file, not a regular file"
        return record
    if stat.st_size > MAX_HASH_BYTES:
        record.update(collection_status=SKIPPED_TOO_LARGE)
        record["unavailable"]["hash"] = (
            f"the file exceeds the {MAX_HASH_BYTES // (1024 * 1024)} MiB hashing limit; "
            "metadata was recorded but no digest was computed"
        )
        return record

    try:
        digest = hashing.hash_file(absolute)
    except PermissionError:
        record.update(collection_status=PERMISSION_DENIED)
        record["unavailable"]["hash"] = "the file could not be opened for reading"
        return record
    except (OSError, ValueError, RuntimeError) as error:
        record["unavailable"]["hash"] = f"the digest could not be computed: {error}"
        return record

    record.update(
        hash=digest["hash"],
        hash_algorithm=digest["algorithm"],
        integrity=digest["integrity_check"],
        integrity_history=digest["integrity_history"],
        previous_hash=digest["previous_hash"],
        created=record["created"] or digest.get("created"),
        indicators=digest["indicators"] or record["indicators"],
    )
    return record


def _referenced_paths(events):
    """Executable paths named by execution evidence, in first-seen order."""
    ordered = []
    for event in events:
        path = event.get("executable")
        # Shell history records typed text, not a resolved path; a bare word is
        # not a filesystem location and must not be treated as one.
        if not path or not os.path.isabs(path):
            continue
        if path not in ordered:
            ordered.append(path)
    return ordered


def collect_artifacts(*, selected_paths=(), events=(), cancel=None) -> dict:
    """Observe explicitly selected paths, then executables the evidence names."""
    records, seen, skipped_for_bound = [], set(), 0

    def add(path, source):
        nonlocal skipped_for_bound
        absolute = os.path.abspath(path)
        if absolute in seen:
            return
        if len(records) >= MAX_ARTIFACTS:
            skipped_for_bound += 1
            return
        seen.add(absolute)
        records.append(observe_artifact(absolute, source=source, cancel=cancel))

    for path in selected_paths:
        if os.path.isdir(path):
            # One level only: bounded, predictable, and never a recursive sweep.
            try:
                children = sorted(Path(path).iterdir())[:MAX_DIRECTORY_ENTRIES]
            except (OSError, PermissionError):
                add(path, "investigator-selected path")
                continue
            add(path, "investigator-selected path")
            for child in children:
                add(str(child), f"investigator-selected directory {path} (one level)")
        else:
            add(path, "investigator-selected path")

    for path in _referenced_paths(events):
        add(path, "referenced by historical execution evidence")

    statuses = {}
    for record in records:
        statuses[record["collection_status"]] = statuses.get(record["collection_status"], 0) + 1

    warnings = []
    if skipped_for_bound:
        warnings.append(
            f"{skipped_for_bound} candidate artifacts were not observed because the bound of "
            f"{MAX_ARTIFACTS} artifacts per investigation was reached."
        )
    if statuses.get(MISSING):
        warnings.append(
            f"{statuses[MISSING]} artifacts named by evidence were not present at collection time."
        )
    if statuses.get(PERMISSION_DENIED):
        warnings.append(
            f"{statuses[PERMISSION_DENIED]} artifacts could not be read with the collector's privileges."
        )

    return {
        "action": "artifact_collection",
        "status": "success",
        "classification": "OBSERVED",
        "artifacts": records,
        "artifact_count": len(records),
        "statistics": {"by_collection_status": statuses,
                       "selected_path_count": len(list(selected_paths)),
                       "referenced_path_count": len(_referenced_paths(events))},
        "truncated": bool(skipped_for_bound),
        "complete": not skipped_for_bound,
        "limits": {"max_artifacts": MAX_ARTIFACTS, "max_hash_bytes": MAX_HASH_BYTES,
                   "max_directory_entries": MAX_DIRECTORY_ENTRIES, "recursive": False},
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def artifact_from_hash_result(result: dict, *, source: str) -> dict:
    """Adapt an existing `hashing.hash_file` result into an artifact record.

    Explicitly selected files already go through the hashing collector, which
    produces a richer result than a second pass would. Reusing it keeps one
    digest per file per collection: hashing a file twice would add a spurious
    "unchanged" entry to the hash ledger and read large files twice.
    """
    path = result.get("absolute_path") or result.get("target") or ""
    filename = result.get("filename") or os.path.basename(path)
    return {
        "path": path,
        "filename": filename,
        "extension": os.path.splitext(filename)[1].lower() or None,
        "source": source,
        "size_bytes": result.get("size_bytes"),
        "modified": result.get("modified"),
        "created": result.get("created"),
        "metadata_changed": result.get("metadata_changed"),
        "hash": result.get("hash"),
        "hash_algorithm": result.get("algorithm"),
        "collection_status": COLLECTED,
        "indicators": result.get("indicators") or evaluate_filename(filename),
        "integrity": result.get("integrity_check"),
        "integrity_history": result.get("integrity_history"),
        "previous_hash": result.get("previous_hash"),
        "notable_location": notable_location(path),
        "classification": "OBSERVED",
        "unavailable": {},
    }


def merge_artifacts(*collections) -> dict:
    """Combine artifact results, keeping the first record for each path."""
    merged, seen, warnings, truncated = [], set(), [], False
    statuses, selected, referenced = {}, 0, 0
    for collection in collections:
        if not collection:
            continue
        truncated |= bool(collection.get("truncated"))
        warnings.extend(collection.get("warnings", []))
        statistics = collection.get("statistics", {})
        selected += statistics.get("selected_path_count", 0)
        referenced += statistics.get("referenced_path_count", 0)
        for record in collection.get("artifacts", []) or []:
            if record["path"] in seen:
                continue
            seen.add(record["path"])
            merged.append(record)
    for record in merged:
        statuses[record["collection_status"]] = statuses.get(record["collection_status"], 0) + 1
    return {
        "action": "artifact_collection",
        "status": "success",
        "classification": "OBSERVED",
        "artifacts": merged,
        "artifact_count": len(merged),
        "statistics": {"by_collection_status": statuses, "selected_path_count": selected,
                       "referenced_path_count": referenced},
        "truncated": truncated,
        "complete": not truncated,
        "limits": {"max_artifacts": MAX_ARTIFACTS, "max_hash_bytes": MAX_HASH_BYTES,
                   "max_directory_entries": MAX_DIRECTORY_ENTRIES, "recursive": False},
        "warnings": list(dict.fromkeys(warnings)),
    }
