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
), 3: (
    # Investigator-facing columns. The full command line is stored as its own
    # column so it can be searched and displayed without unpacking the payload,
    # and `reference` is the short stable identifier a report cites.
    "ALTER TABLE execution_events ADD COLUMN evidence_kind TEXT NOT NULL DEFAULT 'EXECUTION_EVIDENCE'",
    "ALTER TABLE execution_events ADD COLUMN full_command_line TEXT",
    "ALTER TABLE execution_events ADD COLUMN normalized_command TEXT",
    "ALTER TABLE execution_events ADD COLUMN command_reconstruction_status TEXT",
    "ALTER TABLE execution_events ADD COLUMN command_evidence_strength TEXT",
    "ALTER TABLE execution_events ADD COLUMN execution_confirmed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE execution_events ADD COLUMN reference TEXT",
    "ALTER TABLE execution_events ADD COLUMN triage TEXT",
    "CREATE INDEX execution_event_command ON execution_events(full_command_line)",
    "CREATE INDEX execution_event_reference ON execution_events(investigation_id,reference)",
    "ALTER TABLE artifact_observations ADD COLUMN reference TEXT",
    "ALTER TABLE findings ADD COLUMN triage TEXT",
    "ALTER TABLE findings ADD COLUMN why TEXT",
    "ALTER TABLE findings ADD COLUMN reference TEXT",
    # Collection limitations were previously written as findings. They are a
    # separate kind of statement and now live in their own table, so an
    # investigator's finding list is not padded with missing-telemetry notes.
    "CREATE TABLE collection_limitations (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), evidence_id TEXT REFERENCES evidence(id), category TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL, explanation TEXT NOT NULL, classification TEXT NOT NULL, detail TEXT)",
    "CREATE INDEX limitation_case ON collection_limitations(investigation_id)",
), 4: (
    # Investigator priority, kept separate from the classification so the two
    # can disagree: an ordinary system service is honestly uncertain and still
    # not worth an investigator's morning.
    "ALTER TABLE execution_events ADD COLUMN investigator_priority TEXT",
    "ALTER TABLE execution_events ADD COLUMN priority_score INTEGER",
    "CREATE INDEX execution_event_priority ON execution_events(investigation_id,investigator_priority)",
    "ALTER TABLE findings ADD COLUMN investigator_priority TEXT",
), 5: (
    # Cases hold investigations; an investigation still stands alone when no
    # case is named, so existing rows keep working untouched.
    "CREATE TABLE cases (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, closed_at TEXT, status TEXT NOT NULL DEFAULT 'open', examiner TEXT, reference TEXT, notes TEXT, metadata TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX case_status ON cases(status,created_at DESC)",
    "ALTER TABLE investigations ADD COLUMN case_id TEXT REFERENCES cases(id)",
    "CREATE INDEX investigation_case ON investigations(case_id)",
    # Evidence sources are registered, hashed and verified before anything acts
    # on them. A reprocessed copy is a new row, never an overwrite of the
    # original: losing the first acquisition is exactly what must not happen.
    "CREATE TABLE evidence_sources (id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id), reference TEXT NOT NULL, endpoint TEXT, source_type TEXT NOT NULL, description TEXT, original_path TEXT, stored_path TEXT, size_bytes INTEGER, sha256 TEXT, acquired_at TEXT NOT NULL, registered_at TEXT NOT NULL, collector TEXT, collector_version TEXT, acquisition_status TEXT NOT NULL, verification_state TEXT NOT NULL, supersedes TEXT REFERENCES evidence_sources(id), provenance TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX evidence_source_case ON evidence_sources(case_id,registered_at)",
    "CREATE INDEX evidence_source_hash ON evidence_sources(sha256)",
    "CREATE TABLE evidence_integrity_events (id INTEGER PRIMARY KEY, evidence_source_id TEXT NOT NULL REFERENCES evidence_sources(id), timestamp TEXT NOT NULL, event TEXT NOT NULL, expected_sha256 TEXT, observed_sha256 TEXT, outcome TEXT NOT NULL, detail TEXT)",
    "CREATE INDEX integrity_event_source ON evidence_integrity_events(evidence_source_id,timestamp)",
    # What the application and the investigator did, separate from what the
    # host was observed doing.
    "CREATE TABLE audit_events (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT, object_id TEXT, case_id TEXT, investigation_id TEXT, outcome TEXT NOT NULL, detail TEXT)",
    "CREATE INDEX audit_time ON audit_events(timestamp DESC)",
    "CREATE INDEX audit_case ON audit_events(case_id,timestamp)",
    # Investigator interpretation, kept apart from machine-derived evidence.
    "CREATE TABLE notes (id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id), investigation_id TEXT REFERENCES investigations(id), subject_type TEXT NOT NULL, subject_id TEXT, author TEXT, created_at TEXT NOT NULL, body TEXT NOT NULL)",
    "CREATE INDEX note_subject ON notes(subject_type,subject_id)",
    # What JOCKY actually ran, so an investigation can be reproduced.
    "CREATE TABLE investigation_programs (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), created_at TEXT NOT NULL, source TEXT, ir_version INTEGER, ir TEXT, plan_version INTEGER, plan TEXT, platform TEXT, versions TEXT NOT NULL)",
    "CREATE INDEX program_investigation ON investigation_programs(investigation_id)",
), 6: (
    # Authorized endpoints. An endpoint exists only because an operator issued
    # an enrollment token for it; nothing self-registers. The long-lived
    # credential is stored as a salted digest, so the database never holds a
    # token that could be replayed against an endpoint.
    "CREATE TABLE endpoints (id TEXT PRIMARY KEY, name TEXT NOT NULL, hostname TEXT, platform TEXT, platform_release TEXT, agent_version TEXT, address TEXT, enrolled_at TEXT NOT NULL, last_seen_at TEXT, status TEXT NOT NULL DEFAULT 'enrolled', token_salt TEXT NOT NULL, token_digest TEXT NOT NULL, capabilities TEXT NOT NULL DEFAULT '[]', authorization_reference TEXT, metadata TEXT NOT NULL DEFAULT '{}')",
    "CREATE UNIQUE INDEX endpoint_name ON endpoints(name)",
    "CREATE INDEX endpoint_status ON endpoints(status,last_seen_at)",
    # Enrollment tokens are single-use and expire. Issuing one is the explicit
    # authorization step that precedes any collection on another machine.
    "CREATE TABLE enrollment_tokens (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, issued_by TEXT NOT NULL, endpoint_name TEXT NOT NULL, token_salt TEXT NOT NULL, token_digest TEXT NOT NULL, used_at TEXT, endpoint_id TEXT REFERENCES endpoints(id), authorization_reference TEXT)",
    "CREATE INDEX enrollment_open ON enrollment_tokens(used_at,expires_at)",
    # One structured collection task for one endpoint. `plan_task` holds a
    # source name and bounded options only. There is no column for a command,
    # because an endpoint is never sent one.
    "CREATE TABLE endpoint_tasks (id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL REFERENCES endpoints(id), investigation_id TEXT REFERENCES investigations(id), case_id TEXT REFERENCES cases(id), source TEXT NOT NULL, plan_task TEXT NOT NULL, created_at TEXT NOT NULL, available_at TEXT NOT NULL, dispatched_at TEXT, completed_at TEXT, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, result TEXT, error TEXT, result_sha256 TEXT)",
    "CREATE INDEX endpoint_task_queue ON endpoint_tasks(endpoint_id,status,available_at)",
    "CREATE INDEX endpoint_task_investigation ON endpoint_tasks(investigation_id)",
    # Enrollment, heartbeat, dispatch and result activity, for the audit trail.
    "CREATE TABLE endpoint_events (id INTEGER PRIMARY KEY, endpoint_id TEXT REFERENCES endpoints(id), timestamp TEXT NOT NULL, event TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT)",
    "CREATE INDEX endpoint_event_time ON endpoint_events(endpoint_id,timestamp DESC)",
), 7: (
    # Recognition is computed once during analysis and stored with the record.
    # Recomputing it per screen would re-read the package database every time an
    # investigator scrolled a list.
    "ALTER TABLE artifact_observations ADD COLUMN recognition TEXT",
    "ALTER TABLE artifact_observations ADD COLUMN recognized_name TEXT",
    "ALTER TABLE artifact_observations ADD COLUMN recognition_confidence TEXT",
    "CREATE INDEX artifact_recognized ON artifact_observations(investigation_id,recognized_name)",
    "ALTER TABLE execution_events ADD COLUMN recognition TEXT",
    "ALTER TABLE execution_events ADD COLUMN recognized_name TEXT",
    "CREATE INDEX event_recognized ON execution_events(investigation_id,recognized_name)",
    # An investigator's judgement, stored beside the machine's rather than over
    # it. The machine classification and priority are copied in at the moment
    # the assessment is made, so a later re-analysis cannot make it look as
    # though the investigator disagreed with something they never saw.
    "CREATE TABLE investigator_assessments (id TEXT PRIMARY KEY, investigation_id TEXT REFERENCES investigations(id), case_id TEXT REFERENCES cases(id), subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, machine_classification TEXT, machine_priority TEXT, assessment TEXT NOT NULL, note TEXT, author TEXT NOT NULL, created_at TEXT NOT NULL, superseded_by TEXT)",
    "CREATE INDEX assessment_subject ON investigator_assessments(investigation_id,subject_type,subject_id,created_at DESC)",
    # A generated brief is part of the record of the investigation: what JOCKY
    # said about one subject, from which evidence, under which versions.
    "CREATE TABLE review_briefs (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), case_id TEXT REFERENCES cases(id), subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, created_at TEXT NOT NULL, author TEXT, payload TEXT NOT NULL, evidence_ids TEXT NOT NULL, versions TEXT NOT NULL)",
    "CREATE INDEX brief_subject ON review_briefs(investigation_id,subject_type,subject_id)",
    # Which evidence each generated paragraph rests on, so the narrative in the
    # report can be audited rather than taken on trust.
    "CREATE TABLE report_narrative (id INTEGER PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), report_id TEXT, section TEXT NOT NULL, statement TEXT NOT NULL, evidence_ids TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE INDEX narrative_investigation ON report_narrative(investigation_id,section)",
    # One memory-analysis run against one registered image.
    "CREATE TABLE memory_analyses (id TEXT PRIMARY KEY, investigation_id TEXT REFERENCES investigations(id), case_id TEXT REFERENCES cases(id), evidence_source_id TEXT REFERENCES evidence_sources(id), image_path TEXT, image_sha256 TEXT, tool TEXT, tool_version TEXT, plugin TEXT, provenance TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, result TEXT, error TEXT, versions TEXT NOT NULL)",
    "CREATE INDEX memory_analysis_case ON memory_analyses(case_id,started_at DESC)",
    # File and forensic-image handling state for a registered source.
    "ALTER TABLE evidence_sources ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'REGISTERED'",
    "ALTER TABLE evidence_sources ADD COLUMN container_format TEXT",
    "ALTER TABLE evidence_sources ADD COLUMN format_detail TEXT",
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
