"""Transactional SQLite repository, explicit migrations, backup and ledger import."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from analysis.ledger import _validate_entry, compare_to_last, LedgerError
from backend.versions import DATABASE_SCHEMA_VERSION


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return str(uuid.uuid4())


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class StorageError(RuntimeError):
    pass


MIGRATIONS = {1: (
    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE investigations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, status TEXT NOT NULL, device TEXT NOT NULL DEFAULT '{}', metadata TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX investigation_date ON investigations(created_at DESC)",
    "CREATE TABLE executions (id TEXT PRIMARY KEY, investigation_id TEXT REFERENCES investigations(id), command TEXT NOT NULL, normalized_command TEXT, state TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, result TEXT, error TEXT, idempotency_key TEXT UNIQUE, versions TEXT NOT NULL)",
    "CREATE INDEX execution_case ON executions(investigation_id,created_at)",
    "CREATE TABLE evidence (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), execution_id TEXT REFERENCES executions(id), type TEXT NOT NULL, source TEXT NOT NULL, collected_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX evidence_case ON evidence(investigation_id)",
    "CREATE TABLE findings (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), evidence_id TEXT REFERENCES evidence(id), category TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL, explanation TEXT NOT NULL, classification TEXT NOT NULL)",
    "CREATE INDEX finding_case ON findings(investigation_id)",
    "CREATE TABLE reports (id TEXT PRIMARY KEY, investigation_id TEXT REFERENCES investigations(id), execution_id TEXT REFERENCES executions(id), schema_version INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX report_case ON reports(investigation_id,created_at)",
    "CREATE TABLE transitions (id INTEGER PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), state TEXT NOT NULL, timestamp TEXT NOT NULL, detail TEXT)",
    "CREATE TABLE hash_observations (id TEXT PRIMARY KEY, path TEXT NOT NULL, algorithm TEXT NOT NULL, digest TEXT NOT NULL, size_bytes INTEGER NOT NULL, timestamp TEXT NOT NULL, execution_id TEXT REFERENCES executions(id), provenance TEXT NOT NULL)",
    "CREATE INDEX hash_path ON hash_observations(path,timestamp)",
), 2: (
    # Historical execution evidence, the artifacts it names, the merged
    # timeline, and the evidence each finding rests on. Payload columns hold
    # the normalized record; file contents are never stored, only metadata and
    # digests, so a database stays proportional to the investigation rather
    # than to the disk it examined.
    "CREATE TABLE execution_events (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), evidence_id TEXT REFERENCES evidence(id), source TEXT NOT NULL, source_record_id TEXT, timestamp TEXT, last_seen TEXT, process_name TEXT, executable TEXT, pid INTEGER, parent_pid INTEGER, account TEXT, classification TEXT NOT NULL, collection_status TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX execution_event_case ON execution_events(investigation_id,timestamp)",
    "CREATE INDEX execution_event_executable ON execution_events(executable)",
    "CREATE TABLE artifact_observations (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), evidence_id TEXT REFERENCES evidence(id), path TEXT NOT NULL, filename TEXT NOT NULL, extension TEXT, size_bytes INTEGER, modified TEXT, hash TEXT, collection_status TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX artifact_case ON artifact_observations(investigation_id,path)",
    "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), kind TEXT NOT NULL, timestamp TEXT, title TEXT NOT NULL, source TEXT, classification TEXT, payload TEXT NOT NULL)",
    "CREATE INDEX timeline_case ON timeline_events(investigation_id,timestamp)",
    "CREATE TABLE finding_evidence (id INTEGER PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id), investigation_id TEXT NOT NULL REFERENCES investigations(id), kind TEXT NOT NULL, reference TEXT NOT NULL, detail TEXT)",
    "CREATE INDEX finding_evidence_finding ON finding_evidence(finding_id)",
    # Existing findings keep their rows; confidence is unqualified until a
    # collector that records one writes it.
    "ALTER TABLE findings ADD COLUMN confidence TEXT NOT NULL DEFAULT 'unqualified'",
    "ALTER TABLE findings ADD COLUMN detail TEXT",
)}


class Store:
    def __init__(self, paths):
        self.paths = paths
        paths.initialize()
        try:
            with self.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise StorageError("Database integrity check failed; preserve it and restore a verified backup")
            with self.transaction() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > DATABASE_SCHEMA_VERSION:
                    raise StorageError("Database belongs to a newer backend")
                for target in range(version + 1, DATABASE_SCHEMA_VERSION + 1):
                    for statement in MIGRATIONS[target]:
                        db.execute(statement)
                    db.execute(f"PRAGMA user_version={target}")
        except sqlite3.DatabaseError as error:
            raise StorageError("Database initialization failed; original storage was preserved") from error

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.paths.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def rows(self, query, args=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(query, args)]

    def backup(self):
        destination = self.paths.backups / f"workstation-{identifier()}.sqlite3"
        with self.connection() as source, sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise StorageError("Backup verification failed")
        return destination

    def observe_hash(self, path, algorithm, digest, size, execution_id=None):
        observation = {"algorithm": algorithm.upper(), "hash": digest, "size_bytes": size, "timestamp": now()}
        _validate_entry(observation)
        with self.transaction() as db:
            row = db.execute("SELECT algorithm,digest AS hash,size_bytes,timestamp FROM hash_observations WHERE path=? ORDER BY rowid DESC LIMIT 1", (path,)).fetchone()
            previous = dict(row) if row else None
            comparison = compare_to_last(previous, algorithm, digest)
            db.execute("INSERT INTO hash_observations VALUES (?,?,?,?,?,?,?,?)",
                       (identifier(), path, algorithm.upper(), digest, size, observation["timestamp"], execution_id, "local observation"))
        return previous, comparison

    def migrate_ledger(self, path):
        path = Path(path)
        raw = path.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        marker = "legacy_ledger:" + fingerprint
        if self.rows("SELECT key FROM metadata WHERE key=?", (marker,)):
            return {"imported": 0, "already_imported": True}
        try:
            ledger = json.loads(raw)
            if not isinstance(ledger, dict):
                raise ValueError("Expected path/history mapping")
            for key, history in ledger.items():
                if not key or not isinstance(history, list) or not history:
                    raise ValueError("Invalid history")
                for entry in history:
                    _validate_entry(entry)
        except (ValueError, TypeError, LedgerError) as error:
            raise StorageError("Legacy ledger is invalid; no observations were imported") from error
        backup = self.paths.backups / f"legacy-ledger-{fingerprint}.json"
        if not backup.exists():
            with backup.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                import os
                os.fsync(handle.fileno())
        if backup.read_bytes() != raw:
            raise StorageError("Legacy ledger backup verification failed")
        count = 0
        with self.transaction() as db:
            if db.execute("SELECT key FROM metadata WHERE key=?", (marker,)).fetchone():
                return {"imported": 0, "already_imported": True}
            for key, history in ledger.items():
                for entry in history:
                    db.execute("INSERT INTO hash_observations VALUES (?,?,?,?,?,?,?,?)",
                               (identifier(), key, entry["algorithm"], entry["hash"], entry["size_bytes"], entry["timestamp"], None, str(backup)))
                    count += 1
            db.execute("INSERT INTO metadata VALUES (?,?)", (marker, encode({"source": str(path), "backup": str(backup), "count": count})))
        return {"imported": count, "backup": str(backup)}
