"""
Lightweight, read-only structural sanity checks.

This module never claims to be a general-purpose corruption oracle -- for
most file types "is this corrupted" is undecidable without a known-good
reference. What it DOES do is catch the common, mechanically detectable
cases: files that are empty, unreadable, or that fail a basic structural
check for their own declared format (bad ZIP CRCs, a JPEG missing its
end-of-image marker, a PDF missing its trailer, etc). Everything here is
read-only: files are opened for reading only, never modified.
"""

from __future__ import annotations

import gzip
import os
import zipfile
import zlib

# Statuses, in increasing order of concern.
STATUS_OK = "ok"
STATUS_UNKNOWN = "unknown"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10000


def _limit_result() -> dict:
    return {"status": STATUS_UNKNOWN, "message": "Structural check resource limit reached; integrity is unknown."}


def _read_head_tail(path: str, head: int = 16, tail: int = 1024) -> tuple[bytes, bytes]:
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head_bytes = handle.read(head)
        handle.seek(max(0, size - tail))
        tail_bytes = handle.read(tail)
    return head_bytes, tail_bytes


def _check_zip_family(path: str) -> dict:
    if not zipfile.is_zipfile(path):
        return {
            "status": STATUS_CRITICAL,
            "message": "File has a ZIP-family extension but is not a valid ZIP archive.",
        }
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_DECOMPRESSED_BYTES:
                return _limit_result()
            read_bytes = 0
            for member in members:
                with archive.open(member) as stream:
                    while chunk := stream.read(min(1024 * 1024, MAX_DECOMPRESSED_BYTES - read_bytes + 1)):
                        read_bytes += len(chunk)
                        if read_bytes > MAX_DECOMPRESSED_BYTES:
                            return _limit_result()
    except (RuntimeError, NotImplementedError) as err:
        return {"status": STATUS_UNKNOWN, "message": f"ZIP contents could not be checked: {err}"}
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as err:
        return {"status": STATUS_CRITICAL, "message": f"ZIP archive failed to open: {err}"}
    return {"status": STATUS_OK, "message": "ZIP archive structure and CRCs check out."}


def _check_gzip(path: str) -> dict:
    try:
        with gzip.open(path, "rb") as handle:
            read_bytes = 0
            while chunk := handle.read(min(1024 * 1024, MAX_DECOMPRESSED_BYTES - read_bytes + 1)):
                read_bytes += len(chunk)
                if read_bytes > MAX_DECOMPRESSED_BYTES:
                    return _limit_result()
    except (OSError, EOFError, zlib.error) as err:
        return {"status": STATUS_CRITICAL, "message": f"GZIP stream failed CRC/integrity check: {err}"}
    return {"status": STATUS_OK, "message": "GZIP stream decompressed and checksummed cleanly."}


def _check_jpeg(path: str) -> dict:
    head, tail = _read_head_tail(path)
    if not head.startswith(b"\xff\xd8\xff"):
        return {"status": STATUS_CRITICAL, "message": "JPEG is missing its start-of-image marker."}
    if not tail.rstrip(b"\x00").endswith(b"\xff\xd9"):
        return {
            "status": STATUS_WARNING,
            "message": "JPEG is missing its end-of-image marker; the file may be truncated.",
        }
    return {"status": STATUS_OK, "message": "JPEG start/end markers are present."}


def _check_png(path: str) -> dict:
    head, tail = _read_head_tail(path)
    if not head.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"status": STATUS_CRITICAL, "message": "PNG signature header is missing or invalid."}
    if b"IEND" not in tail:
        return {
            "status": STATUS_WARNING,
            "message": "PNG is missing its IEND chunk near the end of the file; it may be truncated.",
        }
    return {"status": STATUS_OK, "message": "PNG signature and IEND chunk are present."}


def _check_pdf(path: str) -> dict:
    head, tail = _read_head_tail(path, head=8, tail=2048)
    if not head.startswith(b"%PDF-"):
        return {"status": STATUS_CRITICAL, "message": "PDF header (%PDF-) is missing."}
    if b"%%EOF" not in tail:
        return {
            "status": STATUS_WARNING,
            "message": "PDF trailer (%%EOF) was not found near the end of the file; it may be truncated.",
        }
    return {"status": STATUS_OK, "message": "PDF header and trailer markers are present."}


_CHECKERS = {
    ".zip": (_check_zip_family, "zip"),
    ".docx": (_check_zip_family, "zip (Office document)"),
    ".xlsx": (_check_zip_family, "zip (Office document)"),
    ".pptx": (_check_zip_family, "zip (Office document)"),
    ".jar": (_check_zip_family, "zip (Java archive)"),
    ".apk": (_check_zip_family, "zip (Android package)"),
    ".gz": (_check_gzip, "gzip"),
    ".jpg": (_check_jpeg, "jpeg"),
    ".jpeg": (_check_jpeg, "jpeg"),
    ".png": (_check_png, "png"),
    ".pdf": (_check_pdf, "pdf"),
}


def check_basic_integrity(path: str) -> dict:
    """
    Run the best available structural sanity check for this file's type.

    Returns:
        {
          "performed": bool,       -- whether a real structural check ran
          "file_type": str,        -- detected type label
          "status": "ok" | "warning" | "critical" | "unknown",
          "message": str,
        }
    """
    try:
        size = os.path.getsize(path)
    except OSError as err:
        return {
            "performed": True,
            "file_type": "unknown",
            "status": STATUS_CRITICAL,
            "message": f"File could not be accessed for an integrity check: {err}",
        }

    if size == 0:
        return {
            "performed": True,
            "file_type": "unknown",
            "status": STATUS_WARNING,
            "message": "File is empty (0 bytes).",
        }

    if size > MAX_INPUT_BYTES:
        return {"performed": False, "file_type": "unknown", **_limit_result()}

    ext = os.path.splitext(path)[1].lower()
    checker_entry = _CHECKERS.get(ext)

    if checker_entry is None:
        # No format-specific check available for this extension. Confirming
        # the file is at least fully readable is still useful signal, but
        # it is NOT the same as confirming the file's contents are intact,
        # so this is reported as "unknown", never as "ok".
        try:
            with open(path, "rb") as handle:
                while handle.read(1024 * 1024):
                    pass
        except OSError as err:
            return {
                "performed": True,
                "file_type": ext.lstrip(".") or "unknown",
                "status": STATUS_CRITICAL,
                "message": f"File could not be fully read: {err}",
            }
        return {
            "performed": False,
            "file_type": ext.lstrip(".") or "unknown",
            "status": STATUS_UNKNOWN,
            "message": (
                "No format-specific integrity check is available for this file type. "
                "The file was fully readable, but that does not confirm its contents are intact."
            ),
        }

    checker_fn, type_label = checker_entry
    try:
        result = checker_fn(path)
    except OSError as err:
        return {
            "performed": True,
            "file_type": type_label,
            "status": STATUS_CRITICAL,
            "message": f"Integrity check could not complete: {err}",
        }

    return {"performed": True, "file_type": type_label, **result}
