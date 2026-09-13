"""
Local hash ledger.

Every time JOCKY hashes a file, it records {algorithm, hash, size, timestamp}
for that absolute path in a small local JSON file. The next time the same
path is hashed, JOCKY can tell the analyst whether the file has changed
since the last time JOCKY looked at it -- entirely from its own prior
observations, with no external "known-good" reference required.

This is local, evidentiary bookkeeping only: it reads and appends to one
JSON file under jocky/data/ and never touches the files being analyzed.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_LEDGER_LOCK = threading.RLock()
from backend.paths import Paths

_DATA_DIR = str(Paths.resolve().data)
_LEDGER_PATH = os.path.join(_DATA_DIR, "hash_ledger.json")

MAX_HISTORY_PER_FILE = 20


class LedgerError(RuntimeError):
    """Hash history cannot be trusted or persisted; never report verification."""


def _validate_entry(entry: dict) -> None:
    lengths = {"SHA256": 64, "SHA1": 40, "MD5": 32, "SHA512": 128}
    try:
        algorithm, digest = entry["algorithm"], entry["hash"]
        size, timestamp = entry["size_bytes"], entry["timestamp"]
        valid = (
            isinstance(algorithm, str) and algorithm.upper() in lengths
            and isinstance(digest, str) and len(digest) == lengths[algorithm.upper()]
            and all(c in "0123456789abcdef" for c in digest.lower())
            and type(size) is int and size >= 0 and isinstance(timestamp, str)
        )
        if not valid:
            raise ValueError("Invalid observation fields")
        if datetime.fromisoformat(timestamp).tzinfo is None:
            raise ValueError("Observation timestamp must contain a timezone")
    except (KeyError, TypeError, ValueError) as error:
        raise LedgerError("Hash ledger contains an invalid observation") from error


def _load_ledger() -> dict:
    try:
        with open(_LEDGER_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise LedgerError("Hash ledger is unreadable or corrupt; verification unavailable") from error
    if not isinstance(data, dict):
        raise LedgerError("Hash ledger must contain a path-to-history mapping")
    for path, history in data.items():
        if not isinstance(path, str) or not path or not isinstance(history, list) or not history:
            raise LedgerError("Hash ledger contains invalid history")
        for entry in history:
            _validate_entry(entry)
    return data


def _save_ledger(ledger: dict) -> None:
    tmp_path = _LEDGER_PATH + ".tmp"
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(ledger, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, _LEDGER_PATH)
    except OSError as error:
        raise LedgerError("Hash ledger could not be saved; verification unavailable") from error


def get_last_hash(absolute_path: str) -> dict | None:
    """Return the most recent recorded hash entry for this path, or None."""
    with _LEDGER_LOCK:
        ledger = _load_ledger()
    history = ledger.get(absolute_path) or []
    return history[-1] if history else None


def record_hash(absolute_path: str, algorithm: str, hash_value: str, size_bytes: int) -> None:
    """Append a new hash observation for this path to the ledger."""
    entry = {
        "algorithm": algorithm.upper(),
        "hash": hash_value,
        "size_bytes": size_bytes,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    _validate_entry(entry)
    if not isinstance(absolute_path, str) or not absolute_path:
        raise LedgerError("An observation requires a nonempty path")
    with _LEDGER_LOCK:
        ledger = _load_ledger()
        history = ledger.get(absolute_path) or []
        history.append(entry)
        ledger[absolute_path] = history[-MAX_HISTORY_PER_FILE:]
        _save_ledger(ledger)


def observe_hash(absolute_path: str, algorithm: str, hash_value: str, size_bytes: int) -> tuple:
    """Compare and append atomically within this backend process."""
    with _LEDGER_LOCK:
        previous = get_last_hash(absolute_path)
        comparison = compare_to_last(previous, algorithm, hash_value)
        record_hash(absolute_path, algorithm, hash_value, size_bytes)
        return previous, comparison


def compare_to_last(previous: dict | None, algorithm: str, hash_value: str) -> dict:
    """
    Build a human-readable comparison between a freshly computed hash and
    the previously recorded one (if any) for the same file.

    Returns:
        {
          "has_previous": bool,
          "status": "first_recorded" | "unchanged" | "altered" | "algorithm_mismatch",
          "message": str,
        }
    """
    if previous is None:
        return {
            "has_previous": False,
            "status": "first_recorded",
            "message": "No prior JOCKY hash is on record for this file; this is the first observation.",
        }

    _validate_entry(previous)

    if previous["algorithm"].upper() != algorithm.upper():
        return {
            "has_previous": True,
            "status": "algorithm_mismatch",
            "message": (
                f"A previous {previous['algorithm']} hash is on record from {previous['timestamp']}, "
                f"but this run used {algorithm.upper()}. Re-run with {previous['algorithm']} to compare directly."
            ),
        }

    if previous["hash"].lower() == hash_value.lower():
        return {
            "has_previous": True,
            "status": "unchanged",
            "message": f"Unchanged since it was last hashed by JOCKY at {previous['timestamp']}.",
        }

    return {
        "has_previous": True,
        "status": "altered",
        "message": (
            f"ALTERED since it was last hashed by JOCKY at {previous['timestamp']}: "
            f"the {algorithm.upper()} digest no longer matches."
        ),
    }
