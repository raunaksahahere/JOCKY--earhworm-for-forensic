"""Compatibility projection for the existing Flutter case/history widgets.

Only editable case metadata is accepted from clients. Execution/report data
always comes from SQLite, never from a client-supplied success assertion.
"""
import json
from backend.storage import encode, now
from backend.service import ServiceError


def view(service):
    investigations = []
    for case in service.list_cases():
        metadata = case["metadata"]
        investigations.append({"id": case["id"], "title": case["title"], "opened_at": case["created_at"],
                               "closed_at": metadata.get("closed_at"), "notes": metadata.get("notes", ""),
                               "reference": metadata.get("reference"), "examiner": metadata.get("examiner"),
                               "evidence": metadata.get("attached_sources", [])})
    executions = []
    for row in service.store.rows("SELECT e.*,r.payload AS report FROM executions e LEFT JOIN reports r ON r.execution_id=e.id ORDER BY e.created_at DESC LIMIT 1000"):
        error = json.loads(row["error"]) if row["error"] else {}
        executions.append({"id": row["id"], "submitted_at": row["created_at"], "command_text": row["command"],
                           "outcome": "completed" if row["state"] == "completed" else "abandoned" if row["state"] in {"queued", "running", "cancelled", "interrupted"} else "failed",
                           "origin": "command_center", "case_id": row["investigation_id"], "client_elapsed_ms": 0,
                           "report": json.loads(row["report"]) if row["report"] else None,
                           "failure_message": error.get("message"), "failure_code": error.get("code")})
    active = service.store.rows("SELECT value FROM metadata WHERE key='active_case'")
    return {"store_version": 1, "investigations": investigations, "executions": executions,
            "active_case_id": json.loads(active[0]["value"]) if active else None}


def save_metadata(service, data):
    cases = data.get("investigations", [])
    if not isinstance(cases, list) or len(cases) > 1000:
        raise ServiceError("Invalid case metadata")
    with service.store.transaction() as db:
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("title"), str) or not case["title"].strip():
                raise ServiceError("Invalid case identity/title")
            row = db.execute("SELECT metadata FROM investigations WHERE id=?", (case["id"],)).fetchone()
            metadata = json.loads(row[0]) if row else {}
            metadata.update({key: case.get(key) for key in ("notes", "examiner", "reference", "closed_at")})
            metadata["attached_sources"] = case.get("evidence", [])
            if row:
                db.execute("UPDATE investigations SET title=?,metadata=? WHERE id=?", (case["title"][:240], encode(metadata), case["id"]))
            else:
                db.execute("INSERT INTO investigations(id,title,created_at,status,metadata) VALUES (?,?,?,'created',?)", (case["id"], case["title"][:240], now(), encode(metadata)))
                db.execute("INSERT INTO transitions(investigation_id,state,timestamp) VALUES (?,'created',?)", (case["id"], now()))
        active = data.get("active_case_id")
        if active is not None and not db.execute("SELECT id FROM investigations WHERE id=?", (active,)).fetchone():
            raise ServiceError("Active investigation does not exist")
        db.execute("INSERT INTO metadata VALUES ('active_case',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode(active),))
    return view(service)


def import_legacy(service, path):
    """Explicit import of former Flutter JSON records with provenance and backup."""
    import hashlib
    from pathlib import Path
    from datetime import datetime
    source = Path(path)
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ServiceError("Legacy record store exceeds the 32 MiB import limit")
    raw = source.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    marker = "legacy_workstation:" + fingerprint
    if service.store.rows("SELECT key FROM metadata WHERE key=?", (marker,)):
        return {"already_imported": True}
    try:
        data = json.loads(raw)
        if data.get("store_version") != 1 or not isinstance(data.get("investigations"), list) or not isinstance(data.get("executions"), list):
            raise ValueError("Unsupported legacy store")
        ids = set()
        for case in data["investigations"]:
            if not isinstance(case["id"], str) or not case["id"] or not isinstance(case["title"], str):
                raise ValueError("Invalid case")
            if case["id"] in ids: raise ValueError("Duplicate case identity")
            ids.add(case["id"])
            if datetime.fromisoformat(case["opened_at"]).tzinfo is None: raise ValueError("Naive timestamp")
        execution_ids = set()
        for execution in data["executions"]:
            if execution["id"] in execution_ids: raise ValueError("Duplicate execution")
            execution_ids.add(execution["id"])
            if execution.get("case_id") is not None and execution["case_id"] not in ids: raise ValueError("Unknown case reference")
            if execution["outcome"] not in {"completed", "failed", "abandoned"}: raise ValueError("Unknown outcome")
            if datetime.fromisoformat(execution["submitted_at"]).tzinfo is None: raise ValueError("Naive timestamp")
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ServiceError("Legacy store is invalid; nothing imported") from error
    backup = service.store.paths.backups / f"legacy-workstation-{fingerprint}.json"
    if not backup.exists():
        with backup.open('xb') as handle:
            handle.write(raw); handle.flush()
            import os
            os.fsync(handle.fileno())
    if backup.read_bytes() != raw: raise ServiceError("Backup verification failed")
    with service.store.transaction() as db:
        for case in data["investigations"]:
            metadata = {key: case.get(key) for key in ('notes','examiner','reference','closed_at')}
            metadata.update(attached_sources=case.get('evidence', []), provenance="Imported former Flutter client record", backup=str(backup))
            if db.execute("SELECT id FROM investigations WHERE id=?", (case['id'],)).fetchone():
                raise ServiceError("Legacy case ID conflicts with existing data; no records imported", "conflict", 409)
            db.execute("INSERT INTO investigations(id,title,created_at,status,metadata) VALUES (?,?,?,'created',?)", (case['id'], case['title'], case['opened_at'], encode(metadata)))
        for execution in data['executions']:
            report = execution.get('report')
            error = {'code':execution.get('failure_code'), 'message':execution.get('failure_message'), 'provenance':'legacy client record'}
            db.execute("INSERT INTO executions(id,investigation_id,command,normalized_command,state,created_at,completed_at,result,error,versions) VALUES (?,?,?,?,?,?,?,?,?,?)", (
                execution['id'], execution.get('case_id'), execution.get('command_text',''), encode(report.get('normalized_command')) if report else None,
                'interrupted' if execution['outcome']=='abandoned' else execution['outcome'], execution['submitted_at'], None,
                encode(report.get('result')) if report else None, encode(error), encode({'provenance':'legacy client record; engine version unavailable'})))
            if report:
                db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)", (report['report_id'], execution.get('case_id'), execution['id'], report.get('schema_version',1), report['timestamp'], encode(report)))
        db.execute("INSERT INTO metadata VALUES (?,?)", (marker, encode({'backup':str(backup)})))
    return {'investigations_imported':len(data['investigations']), 'executions_imported':len(data['executions']), 'backup':str(backup)}


def clear_history(service):
    """Delete the whole execution log: every row the History screen lists.

    This clears the record of the commands and collection steps this
    workstation ran, including the steps belonging to investigations. That is
    the operator's decision to make, and the button says plainly what it does.

    What it deliberately does not do is cascade into the evidence. Observations,
    findings, artifacts, execution events, the merged timeline and each
    investigation's own report all survive; their `execution_id` link is cleared
    rather than the rows being deleted, so an investigation still holds what was
    observed and can still export its report. The hash ledger survives for the
    same reason: it is what tells an investigator whether a file changed between
    sightings, and it spans investigations.

    What is lost is the job log: when each step ran, how long it took, its state,
    and which evidence row came from which step. Per-command reports issued for
    Command Center runs go with their executions, since nothing would reference
    them afterwards.

    The clearance is itself recorded. Unrecorded destruction has no place in a
    forensic workstation.
    """
    with service.store.transaction() as db:
        total = db.execute("SELECT count(*) FROM executions").fetchone()[0]
        preserved = {
            "evidence": db.execute("SELECT count(*) FROM evidence").fetchone()[0],
            "findings": db.execute("SELECT count(*) FROM findings").fetchone()[0],
            "investigation_reports": db.execute(
                "SELECT count(*) FROM reports WHERE execution_id IS NULL").fetchone()[0],
            "hash_observations": db.execute("SELECT count(*) FROM hash_observations").fetchone()[0],
        }
        # Detach before deleting: the evidence is the forensic record and must
        # outlive the job log that produced it.
        db.execute("UPDATE evidence SET execution_id=NULL")
        db.execute("UPDATE hash_observations SET execution_id=NULL")
        db.execute("DELETE FROM reports WHERE execution_id IS NOT NULL")
        db.execute("DELETE FROM executions")
        record = {"timestamp": now(), "deleted": total, "retained": 0, "preserved": preserved}
        existing = db.execute("SELECT value FROM metadata WHERE key='history_clearances'").fetchone()
        history = (json.loads(existing[0]) if existing else [])[-99:] + [record]
        db.execute(
            "INSERT INTO metadata VALUES ('history_clearances',?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode(history),))
    return {"deleted": total, "retained": 0,
            "retained_reason": None,
            "preserved": preserved,
            "preserved_reason": ("Observations, findings, artifacts and each investigation's own "
                                 "report were kept. Only the execution log was removed."),
            "recorded_at": record["timestamp"], "workstation": view(service)}
