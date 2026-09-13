"""
Cases, evidence sources, audit trail and investigator notes.

Three things are kept deliberately apart here:

  what the host was observed doing   -- evidence, collected by the analysis layer
  what JOCKY and the investigator did -- audit events
  what the investigator thinks        -- notes

Conflating them is how an interpretation ends up looking like an observation.

An evidence source is registered once, hashed, and never overwritten. Bringing
in a second copy of the same file creates a new row that records what it
supersedes, so the original acquisition survives and the relationship between
the two is explicit.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from backend.storage import encode, identifier, now
from backend.versions import versions

CHUNK = 1024 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024 * 1024

REGISTERED = "REGISTERED"
HASHED = "HASHED"
FAILED = "FAILED"

UNVERIFIED = "UNVERIFIED"
VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
MISSING = "MISSING"


class CaseworkError(ValueError):
    def __init__(self, message, code="validation_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def local_actor() -> str:
    """Who the audit trail records as having acted.

    A local workstation has no user directory to consult, so this is the local
    account and host. It is an identity for the record, not an authentication
    claim, and the audit trail says so.
    """
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    return f"{user}@{socket.gethostname()}"


def sha256_file(path: Path, *, chunk=CHUNK) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


class Casework:
    """Case, evidence-source, audit and note operations over one store."""

    def __init__(self, store):
        self.store = store

    # --- audit -----------------------------------------------------------
    def audit(self, action, *, object_type=None, object_id=None, case_id=None,
              investigation_id=None, outcome="success", detail=None, actor=None, db=None):
        """Record something the application or the investigator did.

        Never a place for secrets: `detail` is for identifiers and outcomes.
        """
        row = (now(), actor or local_actor(), action, object_type, object_id, case_id,
               investigation_id, outcome, encode(detail) if detail is not None else None)
        statement = ("INSERT INTO audit_events"
                     " (timestamp,actor,action,object_type,object_id,case_id,investigation_id,"
                     "  outcome,detail) VALUES (?,?,?,?,?,?,?,?,?)")
        if db is not None:
            db.execute(statement, row)
            return
        with self.store.transaction() as connection:
            connection.execute(statement, row)

    def audit_trail(self, *, case_id=None, limit=1000):
        query = "SELECT * FROM audit_events"
        args = ()
        if case_id:
            query += " WHERE case_id=?"
            args = (case_id,)
        rows = self.store.rows(query + " ORDER BY id DESC LIMIT ?", args + (int(limit),))
        for row in rows:
            if row.get("detail"):
                try:
                    row["detail"] = json.loads(row["detail"])
                except ValueError:
                    pass
        return rows

    # --- cases -----------------------------------------------------------
    def create_case(self, data: dict) -> dict:
        title = (data.get("title") or "").strip()
        if not title or len(title) > 240:
            raise CaseworkError("A case title must contain 1-240 characters")
        case_id = (data.get("id") or "").strip() or f"CASE-{identifier()[:8].upper()}"
        if self.store.rows("SELECT id FROM cases WHERE id=?", (case_id,)):
            raise CaseworkError(f"Case {case_id} already exists", "conflict", 409)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO cases (id,title,created_at,status,examiner,reference,notes,metadata)"
                " VALUES (?,?,?,'open',?,?,?,?)",
                (case_id, title, now(), str(data.get("examiner", ""))[:240] or None,
                 str(data.get("reference", ""))[:240] or None,
                 str(data.get("notes", ""))[:10000] or None, encode(data.get("metadata") or {})))
            self.audit("case.created", object_type="case", object_id=case_id, case_id=case_id,
                       detail={"title": title}, db=db)
        return self.get_case(case_id)

    def get_case(self, case_id: str) -> dict:
        rows = self.store.rows("SELECT * FROM cases WHERE id=?", (case_id,))
        if not rows:
            raise CaseworkError("Case not found", "not_found", 404)
        case = rows[0]
        case["metadata"] = json.loads(case["metadata"])
        case["investigation_count"] = self.store.rows(
            "SELECT count(*) AS n FROM investigations WHERE case_id=?", (case_id,))[0]["n"]
        case["evidence_source_count"] = self.store.rows(
            "SELECT count(*) AS n FROM evidence_sources WHERE case_id=?", (case_id,))[0]["n"]
        return case

    def list_cases(self, *, status=None, limit=500) -> list:
        query = "SELECT id FROM cases"
        args = ()
        if status:
            query += " WHERE status=?"
            args = (status,)
        rows = self.store.rows(query + " ORDER BY created_at DESC LIMIT ?", args + (int(limit),))
        return [self.get_case(row["id"]) for row in rows]

    def close_case(self, case_id: str, *, reopen=False) -> dict:
        self.get_case(case_id)
        with self.store.transaction() as db:
            db.execute("UPDATE cases SET status=?,closed_at=? WHERE id=?",
                       ("open" if reopen else "closed", None if reopen else now(), case_id))
            self.audit("case.reopened" if reopen else "case.closed", object_type="case",
                       object_id=case_id, case_id=case_id, db=db)
        return self.get_case(case_id)

    # --- evidence sources ------------------------------------------------
    def register_evidence(self, data: dict) -> dict:
        """Register and hash an evidence source without altering it.

        The file is read to compute its digest and is never written to, moved or
        renamed. When the same bytes are registered again, the new row records
        what it supersedes rather than replacing it.
        """
        path = data.get("path")
        source_type = (data.get("source_type") or "file").strip().lower()
        case_id = data.get("case_id")
        if case_id:
            self.get_case(case_id)
        if not isinstance(path, str) or not path or not os.path.isabs(path):
            raise CaseworkError("An evidence source needs an absolute path")

        evidence_id = f"EV-{identifier()[:8].upper()}"
        target = Path(path)
        acquired_at = data.get("acquired_at") or now()
        provenance = {
            "registered_by": local_actor(),
            "collector": data.get("collector") or "investigator import",
            "collector_version": data.get("collector_version") or versions()["application"],
            "original_path": path,
            "read_only": True,
            "note": ("JOCKY hashed this source in place. The file was not modified, moved or "
                     "renamed."),
        }

        try:
            if not target.is_file():
                raise FileNotFoundError(path)
            size = target.stat().st_size
            if size > MAX_EVIDENCE_BYTES:
                raise CaseworkError(
                    f"Evidence source exceeds the {MAX_EVIDENCE_BYTES // (1024**3)} GiB limit")
            digest, hashed_size = sha256_file(target)
            status, verification = HASHED, VERIFIED
            detail = "Registered and hashed."
        except FileNotFoundError:
            digest, size, hashed_size = None, None, None
            status, verification = FAILED, MISSING
            detail = "No file exists at that path."
        except PermissionError:
            digest, size, hashed_size = None, None, None
            status, verification = FAILED, UNVERIFIED
            detail = "The file exists but is not readable by the collecting user."

        supersedes = None
        if digest:
            previous = self.store.rows(
                "SELECT id FROM evidence_sources WHERE sha256=? ORDER BY registered_at DESC LIMIT 1",
                (digest,))
            if previous:
                supersedes = previous[0]["id"]
                detail += (f" These bytes were already registered as {supersedes}; this row records "
                           "a further acquisition and does not replace it.")

        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO evidence_sources"
                " (id,case_id,reference,endpoint,source_type,description,original_path,stored_path,"
                "  size_bytes,sha256,acquired_at,registered_at,collector,collector_version,"
                "  acquisition_status,verification_state,supersedes,provenance,metadata)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, case_id, data.get("reference") or evidence_id,
                 data.get("endpoint") or socket.gethostname(), source_type,
                 str(data.get("description", ""))[:1000] or None, path, path,
                 hashed_size if hashed_size is not None else size, digest, acquired_at, now(),
                 provenance["collector"], provenance["collector_version"], status, verification,
                 supersedes, encode(provenance), encode(data.get("metadata") or {})))
            db.execute(
                "INSERT INTO evidence_integrity_events"
                " (evidence_source_id,timestamp,event,expected_sha256,observed_sha256,outcome,detail)"
                " VALUES (?,?,?,?,?,?,?)",
                (evidence_id, now(), "registered", None, digest,
                 "success" if digest else "failed", detail))
            self.audit("evidence.registered", object_type="evidence_source",
                       object_id=evidence_id, case_id=case_id,
                       outcome="success" if digest else "failed",
                       detail={"sha256": digest, "supersedes": supersedes, "path": path}, db=db)
        return self.get_evidence(evidence_id)

    def get_evidence(self, evidence_id: str) -> dict:
        rows = self.store.rows("SELECT * FROM evidence_sources WHERE id=?", (evidence_id,))
        if not rows:
            raise CaseworkError("Evidence source not found", "not_found", 404)
        record = rows[0]
        record["provenance"] = json.loads(record["provenance"])
        record["metadata"] = json.loads(record["metadata"])
        record["integrity_events"] = self.store.rows(
            "SELECT * FROM evidence_integrity_events WHERE evidence_source_id=? ORDER BY id",
            (evidence_id,))
        return record

    def list_evidence(self, *, case_id=None, limit=1000) -> list:
        query = "SELECT id FROM evidence_sources"
        args = ()
        if case_id:
            query += " WHERE case_id=?"
            args = (case_id,)
        rows = self.store.rows(query + " ORDER BY registered_at DESC LIMIT ?", args + (int(limit),))
        return [self.get_evidence(row["id"]) for row in rows]

    def verify_evidence(self, evidence_id: str) -> dict:
        """Re-hash a registered source and record what was found.

        A mismatch is never corrected silently: the original digest stays, and
        the integrity event says the bytes changed.
        """
        record = self.get_evidence(evidence_id)
        expected = record["sha256"]
        path = Path(record["stored_path"] or record["original_path"] or "")
        try:
            observed, _size = sha256_file(path)
            if expected and observed == expected:
                state, outcome, detail = VERIFIED, "success", "The digest matches the registration."
            elif expected:
                state, outcome = MISMATCH, "failed"
                detail = ("The digest differs from registration. The original digest is retained; "
                          "this source can no longer be treated as the bytes first registered.")
            else:
                state, outcome = VERIFIED, "success"
                observed, detail = observed, "First successful hash for this source."
        except FileNotFoundError:
            observed, state, outcome = None, MISSING, "failed"
            detail = "The evidence source is no longer present at its recorded path."
        except (PermissionError, OSError) as error:
            observed, state, outcome = None, UNVERIFIED, "failed"
            detail = f"The source could not be read: {error}"

        with self.store.transaction() as db:
            db.execute("UPDATE evidence_sources SET verification_state=? WHERE id=?",
                       (state, evidence_id))
            db.execute(
                "INSERT INTO evidence_integrity_events"
                " (evidence_source_id,timestamp,event,expected_sha256,observed_sha256,outcome,detail)"
                " VALUES (?,?,?,?,?,?,?)",
                (evidence_id, now(), "verified", expected, observed, outcome, detail))
            self.audit("evidence.verified", object_type="evidence_source", object_id=evidence_id,
                       case_id=record["case_id"], outcome=outcome,
                       detail={"state": state, "expected": expected, "observed": observed}, db=db)
        return self.get_evidence(evidence_id)

    # --- notes -----------------------------------------------------------
    def add_note(self, data: dict) -> dict:
        """Investigator interpretation, stored apart from machine evidence."""
        body = (data.get("body") or "").strip()
        if not body or len(body) > 20000:
            raise CaseworkError("A note must contain 1-20000 characters")
        subject_type = (data.get("subject_type") or "case").strip().lower()
        if subject_type not in {"case", "investigation", "finding", "evidence", "timeline",
                                "thread", "artifact"}:
            raise CaseworkError("Unknown note subject")
        note_id = f"NOTE-{identifier()[:8].upper()}"
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO notes (id,case_id,investigation_id,subject_type,subject_id,author,"
                " created_at,body) VALUES (?,?,?,?,?,?,?,?)",
                (note_id, data.get("case_id"), data.get("investigation_id"), subject_type,
                 data.get("subject_id"), data.get("author") or local_actor(), now(), body))
            self.audit("note.added", object_type=subject_type, object_id=data.get("subject_id"),
                       case_id=data.get("case_id"), investigation_id=data.get("investigation_id"),
                       db=db)
        return self.store.rows("SELECT * FROM notes WHERE id=?", (note_id,))[0]

    def list_notes(self, *, case_id=None, subject_type=None, subject_id=None, limit=500) -> list:
        clauses, args = [], []
        for column, value in (("case_id", case_id), ("subject_type", subject_type),
                              ("subject_id", subject_id)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        query = "SELECT * FROM notes"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return self.store.rows(query + " ORDER BY created_at DESC LIMIT ?", tuple(args) + (int(limit),))
