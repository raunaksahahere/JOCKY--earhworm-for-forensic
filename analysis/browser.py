"""
Read-only browser artifact collection.

History, downloads and profile identity. Deliberately *not* cookies, saved
passwords, session tokens, form data or anything else that would amount to
credential acquisition — the goal is forensic metadata about what was visited
and fetched, which is what correlates a download with a file on disk and with
execution evidence.

Browser databases are SQLite files the browser may hold open. Each is copied to
a temporary location and opened read-only there, so a live browser is never
disturbed and the original is never written to.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_RECORDS_PER_PROFILE = 2000
MAX_PROFILES = 20
MAX_DATABASE_BYTES = 512 * 1024 * 1024

#: Firefox stores microseconds since the Unix epoch; Chromium stores
#: microseconds since 1601-01-01.
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

FIREFOX_ROOTS = ("~/.mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox",
                 "~/.var/app/org.mozilla.firefox/.mozilla/firefox")
CHROMIUM_ROOTS = (
    "~/.config/google-chrome", "~/.config/chromium", "~/.config/microsoft-edge",
    "~/.config/BraveSoftware/Brave-Browser", "~/snap/chromium/common/chromium",
    "~/.var/app/com.google.Chrome/config/google-chrome",
)


def _iso(value):
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def _chrome_time(value):
    if not value:
        return None
    try:
        return (CHROME_EPOCH + timedelta(microseconds=int(value))).isoformat()
    except (OverflowError, ValueError, TypeError):
        return None


def _firefox_time(value):
    return _iso(int(value) / 1_000_000) if value else None


def _query(database: Path, sql: str, limit: int):
    """Copy the database aside and read it there.

    A browser holds its profile open, and querying it in place risks both a lock
    error and a write to the original. Copying first keeps the evidence
    untouched, which matters more than the extra I/O.
    """
    size = database.stat().st_size
    if size > MAX_DATABASE_BYTES:
        raise ValueError(f"profile database exceeds the {MAX_DATABASE_BYTES // (1024**2)} MiB limit")
    with tempfile.TemporaryDirectory(prefix="jocky-browser-") as workspace:
        copy = Path(workspace) / database.name
        shutil.copy2(database, copy)
        for suffix in ("-wal", "-shm"):
            sidecar = database.with_name(database.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, copy.with_name(copy.name + suffix))
        connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql + f" LIMIT {int(limit)}")]
        finally:
            connection.close()


def _firefox_profiles(roots):
    for root in roots:
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        for profile in sorted(base.iterdir()):
            if (profile / "places.sqlite").is_file():
                yield {"browser": "firefox", "profile": profile.name, "path": str(profile),
                       "database": profile / "places.sqlite"}


def _chromium_profiles(roots):
    for root in roots:
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        for profile in sorted(base.iterdir()):
            if (profile / "History").is_file():
                yield {"browser": base.name, "profile": profile.name, "path": str(profile),
                       "database": profile / "History"}


def _read_firefox(profile, limit, window_start):
    visits = _query(profile["database"], """
        SELECT p.url AS url, p.title AS title, p.visit_count AS visit_count,
               v.visit_date AS visited_at
        FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
        ORDER BY v.visit_date DESC""", limit)
    downloads = _query(profile["database"], """
        SELECT p.url AS url, a.content AS target, p.last_visit_date AS visited_at
        FROM moz_annos a JOIN moz_places p ON p.id = a.place_id
        JOIN moz_anno_attributes t ON t.id = a.anno_attribute_id
        WHERE t.name = 'downloads/destinationFileURI'
        ORDER BY a.dateAdded DESC""", limit)
    history = [{"url": row["url"], "title": row["title"], "visit_count": row["visit_count"],
                "visited_at": _firefox_time(row["visited_at"])} for row in visits]
    fetched = [{"url": row["url"],
                "target_path": (row["target"] or "").replace("file://", "") or None,
                "downloaded_at": _firefox_time(row["visited_at"])} for row in downloads]
    return history, fetched


def _read_chromium(profile, limit, window_start):
    visits = _query(profile["database"], """
        SELECT u.url AS url, u.title AS title, u.visit_count AS visit_count,
               v.visit_time AS visited_at
        FROM visits v JOIN urls u ON u.id = v.url
        ORDER BY v.visit_time DESC""", limit)
    downloads = _query(profile["database"], """
        SELECT d.target_path AS target, d.start_time AS started_at, d.received_bytes AS bytes,
               c.url AS url
        FROM downloads d LEFT JOIN downloads_url_chains c
          ON c.id = d.id AND c.chain_index = 0
        ORDER BY d.start_time DESC""", limit)
    history = [{"url": row["url"], "title": row["title"], "visit_count": row["visit_count"],
                "visited_at": _chrome_time(row["visited_at"])} for row in visits]
    fetched = [{"url": row["url"], "target_path": row["target"],
                "size_bytes": row["bytes"], "downloaded_at": _chrome_time(row["started_at"])}
               for row in downloads]
    return history, fetched


def collect_browser_artifacts(cancel=None, *, window_hours=None, roots=None,
                              limit=MAX_RECORDS_PER_PROFILE) -> dict:
    """Browser history and downloads, as forensic metadata only."""
    firefox_roots = (roots or {}).get("firefox", FIREFOX_ROOTS)
    chromium_roots = (roots or {}).get("chromium", CHROMIUM_ROOTS)
    window_start = None
    if window_hours:
        window_start = datetime.now(timezone.utc) - timedelta(hours=float(window_hours))

    profiles, history, downloads, problems = [], [], [], []
    discovered = list(_firefox_profiles(firefox_roots)) + list(_chromium_profiles(chromium_roots))

    for profile in discovered[:MAX_PROFILES]:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Collection cancelled between browser profiles")
        reader = _read_firefox if profile["browser"] == "firefox" else _read_chromium
        record = {"browser": profile["browser"], "profile": profile["profile"],
                  "path": profile["path"], "status": "AVAILABLE",
                  "history_records": 0, "download_records": 0}
        try:
            profile_history, profile_downloads = reader(profile, limit, window_start)
        except PermissionError:
            record.update(status="PERMISSION_DENIED",
                          detail="the profile database is not readable by the collecting user")
            problems.append(record["detail"])
            profiles.append(record)
            continue
        except (sqlite3.Error, OSError, ValueError) as error:
            record.update(status="NOT_AVAILABLE", detail=f"{type(error).__name__}: {error}")
            problems.append(record["detail"])
            profiles.append(record)
            continue

        for entry in profile_history:
            entry.update(browser=profile["browser"], profile=profile["profile"],
                         classification="HISTORICAL_EVIDENCE", source=f"{profile['browser']} history",
                         evidence_strength=("The browser recorded visiting this URL. It does not "
                                            "establish who was at the keyboard."))
        for entry in profile_downloads:
            entry.update(browser=profile["browser"], profile=profile["profile"],
                         classification="HISTORICAL_EVIDENCE",
                         source=f"{profile['browser']} downloads",
                         evidence_strength=("The browser recorded fetching this file to this path. "
                                            "Whether the file is still there is a separate "
                                            "observation."))
        if window_start:
            def inside(value):
                if not value:
                    return True
                try:
                    return datetime.fromisoformat(value) >= window_start
                except ValueError:
                    return True
            profile_history = [entry for entry in profile_history if inside(entry["visited_at"])]
            profile_downloads = [entry for entry in profile_downloads
                                 if inside(entry["downloaded_at"])]

        record.update(history_records=len(profile_history), download_records=len(profile_downloads))
        profiles.append(record)
        history.extend(profile_history)
        downloads.extend(profile_downloads)

    available = [profile for profile in profiles if profile["status"] == "AVAILABLE"]
    warnings = [
        "Browser history and downloads only. Cookies, saved passwords, session tokens and form "
        "data are never read: this module collects forensic metadata, not credentials.",
        "Profile databases were copied before reading, so the browser's own files were not "
        "modified or locked.",
    ]
    if not discovered:
        warnings.append("No browser profile was found for the collecting user.")
    warnings.extend(problems)

    return {
        "action": "browser_artifacts",
        "status": "success",
        "classification": "HISTORICAL_EVIDENCE",
        "profiles": profiles,
        "history": history,
        "downloads": downloads,
        "statistics": {"profiles_discovered": len(discovered), "profiles_read": len(available),
                       "history_records": len(history), "download_records": len(downloads)},
        "limits": {"max_records_per_profile": limit, "max_profiles": MAX_PROFILES,
                   "secrets_collected": False, "passwords_read": False,
                   "cookies_read": False, "tokens_read": False, "form_data_read": False},
        "truncated": any(profile["history_records"] >= limit for profile in profiles),
        "complete": len(available) == len(discovered),
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
