"""Durable local jobs and investigation orchestration; single bounded worker."""
import json
import logging
import os
import platform
import queue
import socket
import sqlite3
import threading
import time
from pathlib import Path

from analysis import hashing
from analysis.files import list_files
from analysis.system import get_system_info
from backend.collectors import process_snapshot
from backend.storage import encode, identifier, now
from backend.versions import versions, REPORT_SCHEMA_VERSION
from compiler.parser import parse_validated_command
from communication.dispatcher import execute_command
from reports.report import create_report

TERMINAL = {"completed", "failed", "partially_completed", "cancelled", "interrupted"}


class ServiceError(ValueError):
    def __init__(self, message, code="validation_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class Workstation:
    def __init__(self, store):
        self.store = store
        self.queue = queue.Queue(maxsize=8)
        self.cancel_events = {}
        self.stopping = threading.Event()
        self.storage_failure = None
        self.lock = threading.RLock()
        # Runtime guarantees one owner per workspace before constructing service.
        with store.transaction() as db:
            db.execute("UPDATE executions SET state='interrupted',completed_at=?,error=? WHERE state IN ('queued','running')", (now(), encode({"code": "interrupted", "message": "Backend stopped before completion"})))
            unfinished = db.execute("SELECT id FROM investigations WHERE status IN ('collecting','analyzing','finalizing')").fetchall()
            for row in unfinished:
                db.execute("UPDATE investigations SET status='interrupted',completed_at=? WHERE id=?", (now(), row[0]))
                db.execute("INSERT INTO transitions(investigation_id,state,timestamp,detail) VALUES (?,?,?,?)", (row[0], "interrupted", now(), "Backend restarted before collection completed"))
        self.worker = threading.Thread(target=self._work, name="jocky-worker", daemon=True)
        self.worker.start()

    def close(self):
        self.stopping.set()
        for event in list(self.cancel_events.values()):
            event.set()
        self.worker.join(timeout=5)

    def _work(self):
        while not self.stopping.is_set():
            try:
                action, args = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                action(*args)
            except Exception:
                self.storage_failure = "Collection could not persist its final state; check workspace storage. Unfinished work will be interrupted on restart."
                logging.exception("Worker failed to persist state")
            finally:
                self.queue.task_done()

    def create_case(self, data):
        title = data.get("title", "Local device investigation")
        if not isinstance(title, str) or not title.strip() or len(title) > 240:
            raise ServiceError("title must contain 1-240 characters")
        case_id = identifier()
        metadata = {"examiner": str(data.get("examiner", ""))[:240], "notes": str(data.get("notes", ""))[:10000],
                    "workstation": {"hostname": socket.gethostname(), "platform": platform.platform()}, "reference": str(data.get("reference", ""))[:240]}
        with self.store.transaction() as db:
            db.execute("INSERT INTO investigations(id,title,created_at,status,metadata) VALUES (?,?,?,?,?)", (case_id, title.strip(), now(), "created", encode(metadata)))
            db.execute("INSERT INTO transitions(investigation_id,state,timestamp) VALUES (?,?,?)", (case_id, "created", now()))
        return self.get_case(case_id)

    def get_case(self, case_id):
        rows = self.store.rows("SELECT * FROM investigations WHERE id=?", (case_id,))
        if not rows:
            raise ServiceError("Investigation not found", "not_found", 404)
        row = rows[0]
        row["device"] = json.loads(row["device"])
        row["metadata"] = json.loads(row["metadata"])
        for table, name in (("evidence", "evidence_count"), ("findings", "finding_count")):
            row[name] = self.store.rows(f"SELECT count(*) AS n FROM {table} WHERE investigation_id=?", (case_id,))[0]["n"]
        return row

    def list_cases(self, search="", status=None):
        rows = self.store.rows("SELECT id FROM investigations WHERE (title LIKE ? OR device LIKE ? OR id LIKE ?) ORDER BY created_at DESC LIMIT 1000", tuple([f"%{search}%"] * 3))
        return [case for row in rows if (case := self.get_case(row["id"])) and (not status or case["status"] == status)]

    def related(self, case_id, table):
        self.get_case(case_id)
        if table not in {"evidence", "findings", "reports", "transitions", "executions"}:
            raise ServiceError("Unknown collection")
        rows = self.store.rows(f"SELECT * FROM {table} WHERE investigation_id=? ORDER BY rowid", (case_id,))
        for row in rows:
            for key in ("payload", "normalized_command", "result", "error", "versions"):
                if key in row and row[key] is not None:
                    row[key] = json.loads(row[key])
        return rows

    def transition(self, case_id, state, detail=None):
        with self.store.transaction() as db:
            db.execute("UPDATE investigations SET status=?,completed_at=CASE WHEN ? THEN ? ELSE completed_at END WHERE id=?", (state, state in TERMINAL, now(), case_id))
            db.execute("INSERT INTO transitions(investigation_id,state,timestamp,detail) VALUES (?,?,?,?)", (case_id, state, now(), detail))

    def collect(self, case_id, data):
        paths = data.get("paths", [])
        if not isinstance(paths, list) or len(paths) > 20 or any(not isinstance(p, str) or not p or not os.path.isabs(p) for p in paths):
            raise ServiceError("paths must be at most 20 explicit absolute file/directory paths")
        with self.lock:
            case = self.get_case(case_id)
            if case["status"] != "created":
                raise ServiceError("Collection already submitted; create a new investigation to collect again", "conflict", 409)
            if self.queue.full() or self.stopping.is_set():
                raise ServiceError("Local worker is busy or stopping", "unavailable", 503)
            with self.store.transaction() as db:
                db.execute("UPDATE investigations SET status='collecting',started_at=? WHERE id=?", (now(), case_id))
                db.execute("INSERT INTO transitions(investigation_id,state,timestamp,detail) VALUES (?,?,?,?)", (case_id, "collecting", now(), "Queued for local collector"))
            self.cancel_events[case_id] = threading.Event()
            self.queue.put_nowait((self._collect, (case_id, paths)))
        return self.get_case(case_id)

    def cancel(self, case_id):
        case = self.get_case(case_id)
        event = self.cancel_events.get(case_id)
        if event and case["status"] not in TERMINAL:
            event.set()
            return {"id": case_id, "cancellation_requested": True, "status": case["status"]}
        raise ServiceError("Investigation is not running", "conflict", 409)

    def _step(self, case_id, action, collector, source):
        execution_id = identifier()
        with self.store.transaction() as db:
            db.execute("INSERT INTO executions(id,investigation_id,command,state,created_at,started_at,versions) VALUES (?,?,?,'running',?,?,?)", (execution_id, case_id, action, now(), now(), encode(versions())))
        token = hashing.hash_observer.set(lambda *args: self.store.observe_hash(*args, execution_id=execution_id))
        try:
            result = collector()
            state = "completed" if result.get("status") not in {"failed", "error"} else "failed"
            error = None
        except InterruptedError:
            result, state, error = {}, "cancelled", {"code": "cancelled", "message": "Cancellation acknowledged"}
        except Exception as exception:
            result, state = {}, "failed"
            expected = isinstance(exception, (OSError, ValueError, RuntimeError))
            error = {"code": "permission_denied" if isinstance(exception, PermissionError) else "collection_failed", "message": str(exception) if expected else "Collector failed unexpectedly; no successful observation is claimed"}
            if not expected:
                logging.exception("Collector failed")
        finally:
            hashing.hash_observer.reset(token)
        evidence_id = identifier()
        with self.store.transaction() as db:
            db.execute("UPDATE executions SET state=?,completed_at=?,result=?,error=? WHERE id=?", (state, now(), encode(result), encode(error) if error else None, execution_id))
            db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)", (evidence_id, case_id, execution_id, action, source, now(), state, encode(result if not error else {"error": error, "classification": "UNAVAILABLE"})))
        return state, result, evidence_id

    def _finalize(self, case_id, status, limitation=None):
        completed = now()
        report = self.report_payload(case_id, status=status)
        report["investigation"].update(status=status, completed_at=completed)
        if limitation:
            report["limitations"].append(limitation)
        report["timeline"].append({"investigation_id": case_id, "state": status, "timestamp": completed, "detail": limitation})
        with self.store.transaction() as db:
            db.execute("UPDATE investigations SET status=?,completed_at=? WHERE id=?", (status, completed, case_id))
            db.execute("INSERT INTO transitions(investigation_id,state,timestamp,detail) VALUES (?,?,?,?)", (case_id, status, completed, limitation))
            db.execute("INSERT INTO reports VALUES (?,?,NULL,?,?,?)", (report["report_id"], case_id, REPORT_SCHEMA_VERSION, report["created_at"], encode(report)))

    def _collect(self, case_id, paths):
        event = self.cancel_events[case_id]
        failures, incomplete = 0, False
        try:
            if event.is_set():
                self._finalize(case_id, "cancelled", "Collection cancelled before observations started")
                return
            state, device, _ = self._step(case_id, "SYSTEM INFO", get_system_info, "local operating system")
            failures += state == "failed"
            with self.store.transaction() as db:
                db.execute("UPDATE investigations SET device=? WHERE id=?", (encode(device), case_id))
            steps = [("PROCESSES", lambda: process_snapshot(event), "psutil current process snapshot")]
            for path in paths:
                def observe(path=path):
                    if os.path.isdir(path):
                        return list_files(path)
                    if os.stat(path).st_size > 128 * 1024 * 1024:
                        return {"status": "success", "target": path, "complete": False, "skipped": True, "warnings": ["File exceeds the 128 MiB collection limit; hash and integrity checks skipped."]}
                    return hashing.hash_file(path)
                steps.append(("FILES", observe, path))
            results = []
            for action, collector, source in steps:
                if event.is_set():
                    break
                state, result, evidence_id = self._step(case_id, action, collector, source)
                failures += state == "failed"
                incomplete |= result.get("complete") is False or bool(result.get("truncated"))
                results.append((result, evidence_id))
            self.transition(case_id, "analyzing")
            for result, evidence_id in results:
                indicators = result.get("indicators", [])
                for indicator in indicators:
                    with self.store.transaction() as db:
                        db.execute("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?)", (identifier(), case_id, evidence_id, "filename", indicator.get("level", "info"), indicator["label"], indicator["detail"], "INFERRED"))
            self.transition(case_id, "finalizing")
            status = "cancelled" if event.is_set() else "partially_completed" if failures or incomplete else "completed"
            self._finalize(case_id, status)
        except Exception as error:
            try:
                self._finalize(case_id, "failed", f"Collection failed ({type(error).__name__}) before all stages completed. Review persisted evidence and diagnostics.")
            except sqlite3.Error:
                self.storage_failure = "Storage failure: committed observations preserved; collection is not complete. Restore writable storage and restart."
                raise
            logging.exception("Investigation collection failed")
        finally:
            self.cancel_events.pop(case_id, None)

    def report_payload(self, case_id, status=None):
        case = self.get_case(case_id)
        return {"report_id": identifier(), "schema_version": REPORT_SCHEMA_VERSION, "created_at": now(),
                "investigation_id": case_id, "investigation": case, "status": status or case["status"],
                "versions": versions(), "device": case["device"],
                "summary": "Authorized local defensive collection. Observations are limited to the sources listed below.",
                "evidence": self.related(case_id, "evidence"), "executions": self.related(case_id, "executions"),
                "findings": self.related(case_id, "findings"), "timeline": self.related(case_id, "transitions"),
                "limitations": ["CURRENT OBSERVATION: process snapshots do not establish historical execution.",
                                "HISTORICAL EVIDENCE: no OS event log or historical execution source was collected.",
                                "A hash compares bytes; it does not prove authenticity or acquisition-chain integrity.",
                                "Only explicitly selected file sources were inspected. No whole-disk acquisition was performed.",
                                "Live collection changes host activity and cannot provide an atomic snapshot of the device.",
                                "Unavailable, skipped and truncated fields remain explicit in each evidence payload."],
                "provenance": {"collector": "JOCKY local Python service", "classification": "OBSERVED", "offline": True}}

    def get_report(self, report_id):
        rows = self.store.rows("SELECT payload FROM reports WHERE id=?", (report_id,))
        if not rows:
            raise ServiceError("Report not found", "not_found", 404)
        return json.loads(rows[0]["payload"])

    def command(self, text, case_id=None):
        if not isinstance(text, str):
            raise ServiceError("command must be a string")
        if case_id:
            self.get_case(case_id)
        execution_id, started = identifier(), time.perf_counter()
        parsed, result, error = None, None, None
        with self.store.transaction() as db:
            db.execute("INSERT INTO executions(id,investigation_id,command,state,created_at,started_at,versions) VALUES (?,?,?,'running',?,?,?)", (execution_id, case_id, text, now(), now(), encode(versions())))
        token = hashing.hash_observer.set(lambda *args: self.store.observe_hash(*args, execution_id=execution_id))
        try:
            parsed = parse_validated_command(text)
            result = execute_command(parsed.to_dispatch_dict())
        except Exception as exception:
            from communication.server import _error_details
            code, kind, http_status = _error_details(exception)
            error = {"code": code, "kind": kind, "message": str(exception) if http_status < 500 else "Internal command execution error", "http_status": http_status}
        finally:
            hashing.hash_observer.reset(token)
        normalized = parsed.to_dict() if parsed else None
        report = create_report(text, parsed.action if parsed else None, parsed.path if parsed else None,
                               status="failed" if error else "completed", result=result,
                               execution_time_ms=round((time.perf_counter() - started) * 1000, 2), errors=[error["message"]] if error else [])
        report.update(normalized_command=normalized, execution_id=execution_id, investigation_id=case_id, versions=versions())
        with self.store.transaction() as db:
            db.execute("UPDATE executions SET normalized_command=?,state=?,completed_at=?,result=?,error=? WHERE id=?", (encode(normalized), "failed" if error else "completed", now(), encode(result), encode(error) if error else None, execution_id))
            db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)", (report["report_id"], case_id, execution_id, 1, now(), encode(report)))
        return {"status": "error" if error else "success", "execution_id": execution_id, "command": text,
                "normalized_command": normalized, "result": result, "report": report,
                "error": error["message"] if error else None, "error_code": error["code"] if error else None,
                "error_kind": error["kind"] if error else None}, error["http_status"] if error else 200
