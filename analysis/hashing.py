"""
Cryptographic hashing for digital evidence integrity verification.

Read-only: opens the target file, streams it through a hash digest, and
reports metadata. Never modifies the file being analyzed.

Also runs a lightweight structural integrity pre-check (analysis/integrity.py)
and compares the freshly computed digest against JOCKY's own hash ledger
(analysis/ledger.py) so the analyst immediately knows both (a) whether the
file looks structurally intact, and (b) whether it has changed since JOCKY
last hashed it.
"""

from __future__ import annotations

from contextvars import ContextVar

import hashlib
import os
from datetime import datetime, timezone

from .indicators import evaluate_filename
from .integrity import check_basic_integrity
from .ledger import observe_hash

SUPPORTED_ALGORITHMS = ("sha256", "sha1", "md5", "sha512")
CHUNK_SIZE = 65536
hash_observer = ContextVar("hash_observer", default=observe_hash)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _identity(stat: os.stat_result) -> tuple:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def hash_file(path: str, algorithm: str = "sha256") -> dict:
    if not path:
        raise ValueError("No file path provided")

    algorithm = (algorithm or "sha256").lower()
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(
            f"Unsupported algorithm '{algorithm}'. Supported: {', '.join(SUPPORTED_ALGORITHMS)}"
        )

    if not os.path.exists(path):
        raise FileNotFoundError(f"Target not found: {path}")
    if not os.path.isfile(path):
        raise ValueError(f"Target is not a file: {path}")

    absolute_path = os.path.abspath(path)
    before = os.stat(path)

    # Structural sanity check first -- corruption doesn't prevent hashing
    # (a corrupted file's hash is still valid evidence), so this never
    # blocks the digest below; it's reported alongside it.
    integrity_check = check_basic_integrity(path)

    digest = hashlib.new(algorithm)
    size_bytes = 0
    with open(path, "rb") as handle:
        opened = os.fstat(handle.fileno())
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size_bytes += len(chunk)
        after_read = os.fstat(handle.fileno())

    stat = os.stat(path)
    # Two comparisons, each between snapshots taken the same way.
    #
    # An open handle and a path report the same file differently on Windows --
    # os.fstat and os.stat return different device and index values for it --
    # so comparing one against the other reported every file as having changed
    # and refused to record any digest at all. Comparing like with like detects
    # both of the things this check is for: the file changing while it was read
    # (the handle, before and after), and the path coming to mean something else
    # (the path, before and after).
    if _identity(after_read) != _identity(opened):
        raise RuntimeError("File changed while it was being read; digest was not recorded")
    if _identity(stat) != _identity(before):
        raise RuntimeError("The file at this path changed during hashing; "
                           "digest was not recorded")
    if size_bytes != before.st_size:
        raise RuntimeError("File changed during hashing; digest was not recorded")

    hash_value = digest.hexdigest()

    # Compare against JOCKY's own prior record for this exact path BEFORE
    # writing the new one, then record the new observation for next time.
    previous_hash, integrity_history = hash_observer.get()(absolute_path, algorithm, hash_value, size_bytes)

    filename = os.path.basename(path)
    birth_time = getattr(stat, "st_birthtime", stat.st_ctime if os.name == "nt" else None)

    verification_state = {
        "first_recorded": "computed (first record)",
        "unchanged": "verified unchanged",
        "altered": "ALTERED since last hash",
        "algorithm_mismatch": "computed (algorithm differs from last record)",
    }[integrity_history["status"]]

    return {
        "action": "hash",
        "target": path,
        "filename": filename,
        "algorithm": algorithm.upper(),
        "hash": hash_value,
        "size_bytes": size_bytes,
        "modified": _iso(stat.st_mtime),
        "created": _iso(birth_time) if birth_time is not None else None,
        "metadata_changed": _iso(stat.st_ctime) if os.name != "nt" else None,
        "absolute_path": absolute_path,
        "verification_state": verification_state,
        "integrity_check": integrity_check,
        "previous_hash": previous_hash,
        "integrity_history": integrity_history,
        "indicators": evaluate_filename(filename),
        "status": "success",
        "message": f"{algorithm.upper()} digest computed for {filename}",
    }
