"""
Read-only directory listing and file-search analysis.

Both functions only read filesystem metadata (names, sizes, timestamps).
Neither opens file contents, executes anything, nor modifies the
filesystem in any way.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .indicators import evaluate_filename

MAX_LIST_ENTRIES = 500
MAX_LIST_ENTRIES_SCANNED = 20000
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_ENTRIES_SCANNED = 20000


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def list_files(path: str) -> dict:
    if not path:
        path = "."

    if not os.path.exists(path):
        raise FileNotFoundError(f"Path not found: {path}")
    if not os.path.isdir(path):
        raise ValueError(f"Path is not a directory: {path}")

    entries = []
    skipped = 0
    scanned = 0
    scan_limited = False
    with os.scandir(path) as it:
        for entry in it:
            if scanned >= MAX_LIST_ENTRIES_SCANNED:
                scan_limited = True
                break
            scanned += 1
            try:
                stat = entry.stat(follow_symlinks=False)
                entries.append(
                    {
                        "name": entry.name,
                        "path": os.path.join(path, entry.name),
                        "type": "directory" if entry.is_dir(follow_symlinks=False) else "file",
                        "size_bytes": stat.st_size if entry.is_file(follow_symlinks=False) else 0,
                        "modified": _iso(stat.st_mtime),
                        "indicators": evaluate_filename(entry.name),
                    }
                )
            except OSError:
                skipped += 1
                continue

    entries.sort(key=lambda e: (e["type"] != "directory", e["name"].lower()))
    truncated = scan_limited or len(entries) > MAX_LIST_ENTRIES
    limited = entries[:MAX_LIST_ENTRIES]

    return {
        "action": "list",
        "target": os.path.abspath(path),
        "entry_count": len(entries),
        "returned_count": len(limited),
        "truncated": truncated,
        "entries_scanned": scanned,
        "skipped_count": skipped,
        "complete": not truncated and not skipped,
        "warnings": ([f"{skipped} entries could not be read."] if skipped else [])
                    + (["Directory listing was truncated."] if truncated else []),
        "entries": limited,
        "status": "success",
        "message": f"{len(entries)} entries found in {path}",
    }


def search_file(filename: str, search_path: str) -> dict:
    if not filename:
        raise ValueError("No filename provided to search for")
    if not search_path:
        search_path = "."
    if not os.path.exists(search_path):
        raise FileNotFoundError(f"Search directory not found: {search_path}")
    if not os.path.isdir(search_path):
        raise NotADirectoryError(f"Search path is not a directory: {search_path}")

    matches = []
    scanned = 0
    truncated_by_scan_limit = False
    truncated_by_match_limit = False
    needle = filename.lower()
    skipped = 0
    warnings = []

    def walk_error(error):
        nonlocal skipped
        if os.path.abspath(error.filename or search_path) == os.path.abspath(search_path):
            raise error
        skipped += 1

    for root, _dirs, files in os.walk(search_path, onerror=walk_error):
        for name in files:
            if scanned >= MAX_SEARCH_ENTRIES_SCANNED:
                truncated_by_scan_limit = True
                break
            scanned += 1
            if needle in name.lower():
                full_path = os.path.join(root, name)
                try:
                    stat = os.stat(full_path)
                    matches.append(
                        {
                            "name": name,
                            "path": full_path,
                            "size_bytes": stat.st_size,
                            "modified": _iso(stat.st_mtime),
                            "indicators": evaluate_filename(name),
                        }
                    )
                except OSError:
                    skipped += 1
                    continue
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated_by_match_limit = True
                    break
        if truncated_by_scan_limit or truncated_by_match_limit:
            break

    truncated = truncated_by_scan_limit or truncated_by_match_limit
    if skipped:
        warnings.append(f"{skipped} files or directories could not be read.")
    if truncated:
        warnings.append("Search was truncated; additional matches may exist.")

    return {
        "action": "search",
        "search_target": filename,
        "search_directory": os.path.abspath(search_path),
        "match_count": len(matches),
        "entries_scanned": scanned,
        "truncated": truncated,
        "skipped_count": skipped,
        "complete": not truncated and not skipped,
        "warnings": warnings,
        "results": matches,
        "status": "success",
        "message": f"{len(matches)} match(es) for '{filename}' under {search_path}",
    }
