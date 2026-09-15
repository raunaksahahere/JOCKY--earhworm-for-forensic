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
from analysis.activity import assign_references, build_activity, build_routine
from analysis.briefs import BriefError, build_brief
from analysis.case_summary import build_case_summary
from analysis.search import search as search_investigation
from analysis.artifacts import artifact_from_hash_result, collect_artifacts, merge_artifacts
from analysis.correlation import correlate
from analysis.cross_source import correlate_sources
from analysis.detections import detect
from analysis.recognition import (
    RECOGNITION_VERSION, SoftwareIndex, recognize_artifacts, recognize_events,
)
from analysis.execution_history import collect_execution_history
from analysis.execution_model import CollectionWindow
from analysis.files import list_files
from analysis.system import get_system_info
from analysis.threads import build_threads
from analysis.timeline import build_significant_events, build_timeline
from backend.collectors import DEFAULT_MAX_PROCESSES, MAX_PROCESSES_CEILING, process_snapshot
from backend import plan_runner
from backend.casework import Casework, local_actor
from backend.fleet import Fleet
from backend.memory_workflow import MemoryWorkflow
from backend.storage import encode, identifier, now
from backend.versions import versions, REPORT_SCHEMA_VERSION
from compiler.investigation import IR_VERSION, ProgramError, compile_program, describe
from compiler.parser import parse_validated_command
from compiler.plan import PLAN_VERSION, build_plan
from communication.dispatcher import execute_command
from reports.report import create_report

TERMINAL = {"completed", "failed", "partially_completed", "cancelled", "interrupted"}

# Persisted timeline entries per investigation. The timeline is derived from
# records that are themselves stored, so this bound costs detail in the stored
# view, never evidence.
MAX_PERSISTED_TIMELINE = 5000


class ServiceError(ValueError):
    def __init__(self, message, code="validation_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class Workstation:
    def __init__(self, store):
        self.store = store
        self.casework = Casework(store)
        self.fleet = Fleet(store, self.casework)
        self.memory = MemoryWorkflow(store, self.casework)
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
        # An investigation may belong to a case. Migration 5 added the column;
        # nothing wrote it, so every collection looked unattached however it was
        # created -- and the evidence package had no case to describe.
        parent = data.get("case_id")
        if parent:
            self.casework.get_case(parent)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO investigations(id,title,created_at,status,metadata,case_id)"
                " VALUES (?,?,?,?,?,?)",
                (case_id, title.strip(), now(), "created", encode(metadata), parent))
            db.execute("INSERT INTO transitions(investigation_id,state,timestamp) VALUES (?,?,?)", (case_id, "created", now()))
            self.casework.audit("investigation.created", object_type="investigation",
                                object_id=case_id, investigation_id=case_id,
                                case_id=parent, db=db)
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
        # Named here rather than interpolated blindly: `table` reaches this
        # method straight from the URL.
        if table not in {"evidence", "findings", "reports", "transitions", "executions",
                         "execution_events", "artifact_observations", "timeline_events",
                         "finding_evidence", "collection_limitations"}:
            raise ServiceError("Unknown collection")
        order = "timestamp" if table in {"execution_events", "timeline_events"} else "rowid"
        rows = self.store.rows(f"SELECT * FROM {table} WHERE investigation_id=? ORDER BY {order}", (case_id,))
        # Which columns hold JSON depends on the table: `normalized_command` is
        # a JSON structure on executions but plain searchable text on
        # execution_events, so decoding by name alone corrupts the latter.
        encoded = {"payload", "detail", "result", "error", "versions"}
        if table == "executions":
            encoded.add("normalized_command")
        for row in rows:
            for key in encoded:
                if key in row and row[key] is not None:
                    try:
                        row[key] = json.loads(row[key])
                    except (TypeError, ValueError):
                        # A plain-text column that happens to share a name.
                        pass
            # SQLite has no boolean type; the client should not have to know
            # that "execution was confirmed" arrives as 0 or 1.
            if "execution_confirmed" in row:
                row["execution_confirmed"] = bool(row["execution_confirmed"])
        return rows

    def transition(self, case_id, state, detail=None):
        with self.store.transaction() as db:
            db.execute("UPDATE investigations SET status=?,completed_at=CASE WHEN ? THEN ? ELSE completed_at END WHERE id=?", (state, state in TERMINAL, now(), case_id))
            db.execute("INSERT INTO transitions(investigation_id,state,timestamp,detail) VALUES (?,?,?,?)", (case_id, state, now(), detail))

    def collect(self, case_id, data):
        paths = data.get("paths", [])
        if not isinstance(paths, list) or len(paths) > 20 or any(not isinstance(p, str) or not p or not os.path.isabs(p) for p in paths):
            raise ServiceError("paths must be at most 20 explicit absolute file/directory paths")
        options = self._collection_options(data)
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
            self.casework.audit(
                "collection.requested", object_type="investigation", object_id=case_id,
                investigation_id=case_id,
                detail={"path_count": len(paths), "window_hours": options["window_hours"],
                        "sources": [task["source"] for task
                                    in ((options.get("program") or {}).get("plan") or {}).get("tasks", [])],
                        "include_command_lines": options["include_command_lines"]})
            self.queue.put_nowait((self._collect, (case_id, paths, options)))
        return self.get_case(case_id)

    @staticmethod
    def _collection_options(data):
        """Validate the bounded collection settings an investigator may choose."""
        try:
            window = CollectionWindow.resolve(data.get("window_hours"))
        except ValueError as error:
            raise ServiceError(str(error)) from error
        maximum = data.get("max_processes", DEFAULT_MAX_PROCESSES)
        try:
            maximum = int(maximum)
        except (TypeError, ValueError) as error:
            raise ServiceError("max_processes must be an integer") from error
        if not 1 <= maximum <= MAX_PROCESSES_CEILING:
            raise ServiceError(f"max_processes must be between 1 and {MAX_PROCESSES_CEILING}")
        include = data.get("include_command_lines", False)
        if not isinstance(include, bool):
            raise ServiceError("include_command_lines must be true or false")
        options = {"window_hours": window.requested_hours, "max_processes": maximum,
                   "include_command_lines": include}
        options["program"] = Workstation._resolve_program(data, window.requested_hours)
        return options

    @staticmethod
    def _resolve_program(data, window_hours):
        """The investigation program this collection will run.

        An investigator may write one, or may simply tick extra sources in the
        client. Either way a program text is what gets compiled, stored and
        replayed, so a collection driven from the UI is exactly as reproducible
        as one driven from the language.
        """
        source_text = data.get("program")
        if source_text is not None and not isinstance(source_text, str):
            raise ServiceError("program must be JOCKY investigation language text")
        if not source_text:
            selected = data.get("sources") or []
            if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
                raise ServiceError("sources must be a list of source names")
            available = set(plan_runner.selectable_sources())
            unknown = [name for name in selected if name.upper() not in available]
            if unknown:
                raise ServiceError(
                    f"Unknown collection source(s): {', '.join(sorted(unknown))}. "
                    f"This build collects {', '.join(sorted(available))}.")
            if not selected:
                return None
            lines = [f'CASE "{data.get("title") or "collection"}"', 'TARGET "localhost"',
                     f"WINDOW LAST {int(window_hours or CollectionWindow.DEFAULT_HOURS)} HOURS"]
            for name in selected:
                name = name.upper()
                if name == "MEMORY":
                    image = data.get("memory_image")
                    if not isinstance(image, str) or not os.path.isabs(image):
                        raise ServiceError("Collecting MEMORY needs memory_image: an absolute path "
                                           "to an image to analyse. JOCKY does not acquire memory.")
                    lines.append(f'COLLECT MEMORY FROM "{image}"')
                else:
                    lines.append(f"COLLECT {name}")
            lines.append("REPORT SUMMARY")
            source_text = "\n".join(lines) + "\n"
        try:
            ir = compile_program(source_text)
            plan = build_plan(ir)
        except ProgramError as error:
            raise ServiceError(str(error), "program_error") from error
        return {"source": source_text, "ir": ir, "plan": plan}

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

    def _persist_analysis(self, case_id, execution, artifacts, correlation, processes, evidence_ids,
                          activity, recognition=None):
        """Write execution events, artifacts, findings and the timeline.

        One transaction: an investigation must never be left holding findings
        that reference evidence rows that were not committed.
        """
        execution_evidence = evidence_ids.get("EXECUTION HISTORY")
        artifact_evidence = evidence_ids.get("ARTIFACTS")
        timeline = build_timeline(execution=execution, artifacts=artifacts, processes=processes,
                                  findings=correlation["findings"],
                                  transitions=self.related(case_id, "transitions"))
        with self.store.transaction() as db:
            triage_by_reference = {
                record["reference"]: group["classification"]
                for group in activity["groups"] for record in group["records"] if record.get("reference")
            }

            def triage_of(reference, key, default=None):
                return (triage_by_reference.get(reference) or {}).get(key, default)
            for event in execution.get("events", []) or []:
                db.execute(
                    "INSERT INTO execution_events"
                    " (id,investigation_id,evidence_id,source,source_record_id,timestamp,last_seen,"
                    "  process_name,executable,pid,parent_pid,account,classification,collection_status,"
                    "  payload,evidence_kind,full_command_line,normalized_command,"
                    "  command_reconstruction_status,command_evidence_strength,execution_confirmed,"
                    "  reference,triage,investigator_priority,priority_score,"
                    "  recognition,recognized_name)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier(), case_id, execution_evidence, event.get("source"),
                     event.get("source_record_id"), event.get("timestamp"), event.get("last_seen"),
                     event.get("process_name"), event.get("executable"), event.get("pid"),
                     event.get("parent_pid"), str(event.get("user")) if event.get("user") is not None else None,
                     event.get("classification"), event.get("collection_status"), encode(event),
                     event.get("evidence_kind"), event.get("full_command_line"),
                     event.get("normalized_command"), event.get("command_reconstruction_status"),
                     event.get("command_evidence_strength"), 1 if event.get("execution_confirmed") else 0,
                     event.get("reference"), triage_of(event.get("reference"), "category"),
                     triage_of(event.get("reference"), "investigator_priority"),
                     triage_of(event.get("reference"), "score"),
                     encode(event.get("recognition")) if event.get("recognition") else None,
                     (event.get("recognition") or {}).get("recognized_name")))
            for record in artifacts.get("artifacts", []) or []:
                db.execute(
                    "INSERT INTO artifact_observations"
                    " (id,investigation_id,evidence_id,path,filename,extension,size_bytes,modified,"
                    "  hash,collection_status,source,payload,reference,"
                    "  recognition,recognized_name,recognition_confidence)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier(), case_id, artifact_evidence, record["path"], record["filename"],
                     record.get("extension"), record.get("size_bytes"), record.get("modified"),
                     record.get("hash"), record["collection_status"], record.get("source", "unknown"),
                     encode(record), record.get("reference"),
                     encode(record.get("recognition")) if record.get("recognition") else None,
                     (record.get("recognition") or {}).get("recognized_name"),
                     (record.get("recognition") or {}).get("confidence")))
            for index, finding in enumerate(correlation["findings"], start=1):
                finding_id = identifier()
                finding["reference"] = f"F-{index:04d}"
                db.execute(
                    "INSERT INTO findings (id,investigation_id,evidence_id,category,severity,title,explanation,classification,confidence,detail,triage,why,reference,investigator_priority) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (finding_id, case_id, self._finding_evidence_id(finding, evidence_ids), finding["category"],
                     finding["severity"], finding["title"], finding["explanation"], finding["classification"],
                     finding["confidence"], encode(finding.get("evidence_references", [])),
                     finding.get("triage"), finding.get("why"), finding["reference"],
                     finding.get("investigator_priority")))
                for reference in finding.get("evidence_references", []):
                    db.execute(
                        "INSERT INTO finding_evidence (finding_id,investigation_id,kind,reference,detail) VALUES (?,?,?,?,?)",
                        (finding_id, case_id, reference.get("kind", "unknown"), str(reference.get("id")),
                         encode({k: v for k, v in reference.items() if k not in ("kind", "id")})))
            for limitation in correlation.get("limitations", []) or []:
                db.execute(
                    "INSERT INTO collection_limitations VALUES (?,?,?,?,?,?,?,?,?)",
                    (identifier(), case_id, self._finding_evidence_id(limitation, evidence_ids),
                     limitation["category"], limitation["severity"], limitation["title"],
                     limitation["explanation"], limitation["classification"],
                     encode(limitation.get("evidence_references", []))))
            for entry in (timeline["entries"] + timeline["undated_entries"])[:MAX_PERSISTED_TIMELINE]:
                db.execute(
                    "INSERT INTO timeline_events (investigation_id,kind,timestamp,title,source,classification,payload) VALUES (?,?,?,?,?,?,?)",
                    (case_id, entry["kind"], entry["timestamp"], entry["title"], entry.get("source"),
                     entry.get("classification"), encode(entry)))

    @staticmethod
    def _finding_evidence_id(finding, evidence_ids):
        """Point a finding at the evidence record its source step produced."""
        kinds = {reference.get("kind") for reference in finding.get("evidence_references", [])}
        if "execution_event" in kinds or "telemetry_source" in kinds:
            return evidence_ids.get("EXECUTION HISTORY")
        if "artifact" in kinds:
            return evidence_ids.get("ARTIFACTS")
        if "process" in kinds:
            return evidence_ids.get("PROCESSES")
        return None

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
            self.casework.audit("collection.finished", object_type="investigation",
                                object_id=case_id, investigation_id=case_id,
                                outcome=status, detail={"report_id": report["report_id"],
                                                        "limitation": limitation}, db=db)

    def _collect(self, case_id, paths, options=None):
        options = options or {"window_hours": None, "max_processes": DEFAULT_MAX_PROCESSES,
                              "include_command_lines": False}
        event = self.cancel_events[case_id]
        failures, incomplete = 0, False
        try:
            self._record_program(case_id, options.get("program"))
            if event.is_set():
                self._finalize(case_id, "cancelled", "Collection cancelled before observations started")
                return
            state, device, _ = self._step(case_id, "SYSTEM INFO", get_system_info, "local operating system")
            failures += state == "failed"
            with self.store.transaction() as db:
                db.execute("UPDATE investigations SET device=? WHERE id=?", (encode(device), case_id))

            steps = [
                ("PROCESSES",
                 lambda: process_snapshot(event, max_processes=options["max_processes"],
                                          include_command_lines=options["include_command_lines"]),
                 "psutil current process snapshot"),
                # Historical evidence is collected in its own step so a source
                # that fails cannot take the rest of the investigation with it.
                ("EXECUTION HISTORY",
                 lambda: collect_execution_history(window_hours=options["window_hours"],
                                                   include_command_lines=options["include_command_lines"],
                                                   cancel=event),
                 "documented operating system execution telemetry"),
            ]
            for path in paths:
                def observe(path=path):
                    if os.path.isdir(path):
                        return list_files(path)
                    if os.stat(path).st_size > 128 * 1024 * 1024:
                        return {"status": "success", "target": path, "complete": False, "skipped": True, "warnings": ["File exceeds the 128 MiB collection limit; hash and integrity checks skipped."]}
                    return hashing.hash_file(path)
                steps.append(("FILES", observe, path))

            results, processes, execution, selected = [], {}, {}, []
            for action, collector, source in steps:
                if event.is_set():
                    break
                state, result, evidence_id = self._step(case_id, action, collector, source)
                failures += state == "failed"
                incomplete |= result.get("complete") is False or bool(result.get("truncated"))
                results.append((action, result, evidence_id))
                if action == "PROCESSES":
                    processes = result
                elif action == "EXECUTION HISTORY":
                    execution = result
                elif action == "FILES" and result.get("hash"):
                    selected.append(artifact_from_hash_result(result, source="investigator-selected path"))

            # Artifacts named by the historical evidence. Explicitly selected
            # files are already hashed above and are merged in rather than read
            # a second time.
            referenced = {}
            if not event.is_set():
                state, referenced, artifact_evidence = self._step(
                    case_id, "ARTIFACTS",
                    lambda: collect_artifacts(events=execution.get("events", []), cancel=event),
                    "files referenced by historical execution evidence")
                failures += state == "failed"
                incomplete |= referenced.get("complete") is False
                results.append(("ARTIFACTS", referenced, artifact_evidence))
            artifacts = merge_artifacts(
                {"artifacts": selected, "statistics": {"selected_path_count": len(selected)}, "warnings": []},
                referenced)

            # Sources the investigation program asked for beyond the baseline.
            # Each runs as its own evidence step, so one unavailable source is a
            # named gap in the report rather than a failed investigation.
            supplementary = {}
            for entry in plan_runner.runnable_tasks((options.get("program") or {}).get("plan") or {}):
                if event.is_set():
                    break
                state, result, evidence_id = self._step(
                    case_id, entry["action"],
                    lambda entry=entry: plan_runner.call(entry, options=options, cancel=event),
                    entry["source_description"])
                failures += state == "failed"
                incomplete |= result.get("complete") is False
                results.append((entry["action"], result, evidence_id))
                supplementary[entry["action"]] = result

            self.transition(case_id, "analyzing")
            evidence_ids = {action: evidence_id for action, _result, evidence_id in results}
            # Short, stable identifiers first: findings cite them, the report
            # prints them, and an investigator uses them to find the record.
            assign_references(execution.get("events", []) or [],
                              artifacts=artifacts.get("artifacts", []) or [])
            # Recognition before triage: what the machine can account for is
            # context the classifier needs, and computing it once here is what
            # keeps it off the investigator's screen-render path.
            index = SoftwareIndex()
            recognition = recognize_artifacts(artifacts.get("artifacts", []) or [], index=index)
            recognition.update(recognize_events(execution.get("events", []) or [], index=index))
            self._record_recognition_sources(case_id, recognition.get("sources") or [])
            correlation = correlate(execution=execution, artifacts=artifacts, processes=processes)
            correlation["findings"].extend(
                detect(drivers=supplementary.get("DRIVERS"), memory=supplementary.get("MEMORY")))
            correlation["findings"].extend(correlate_sources(
                execution=execution, artifacts=artifacts, browser=supplementary.get("BROWSER"),
                usb=supplementary.get("USB")))
            activity = build_activity(execution.get("events", []) or [],
                                      artifacts=artifacts.get("artifacts", []) or [])
            self._persist_analysis(case_id, execution, artifacts, correlation, processes,
                                   evidence_ids, activity, recognition=recognition)

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

    def _record_program(self, case_id, program):
        """Store the program, IR and plan that drove this collection.

        This is what makes a collection repeatable by someone else: the exact
        text, the compiled intermediate form, the platform plan and the version
        of every component that produced them.
        """
        if not program:
            return
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO investigation_programs"
                " (id,investigation_id,created_at,source,ir_version,ir,plan_version,plan,platform,versions)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (identifier(), case_id, now(), program["source"], IR_VERSION,
                 encode(program["ir"]), PLAN_VERSION, encode(program["plan"]),
                 program["plan"]["platform"], encode(versions())))

    def case_summary(self, case_id, *, persist=False):
        """The generated conclusion, with the evidence behind each sentence.

        Persisting it writes one row per statement, so the narrative in a report
        can be audited against the records it was assembled from rather than
        taken on trust.
        """
        report = self._latest_report(case_id)
        summary = build_case_summary(report)
        if persist:
            with self.store.transaction() as db:
                db.execute("DELETE FROM report_narrative WHERE investigation_id=? AND report_id=?",
                           (case_id, report.get("report_id")))
                for statement in summary["statements"]:
                    db.execute(
                        "INSERT INTO report_narrative (investigation_id,report_id,section,"
                        " statement,evidence_ids,created_at) VALUES (?,?,?,?,?,?)",
                        (case_id, report.get("report_id"), statement["section"],
                         statement["statement"], encode(statement["evidence_ids"]), now()))
        return summary

    def narrative(self, case_id):
        rows = self.store.rows(
            "SELECT * FROM report_narrative WHERE investigation_id=? ORDER BY id", (case_id,))
        for row in rows:
            row["evidence_ids"] = json.loads(row["evidence_ids"]) if row["evidence_ids"] else []
        return rows

    def search(self, case_id, term, *, kinds=None):
        return search_investigation(self._latest_report(case_id), term, kinds=kinds)

    # --- investigator assessments -------------------------------------------
    ASSESSMENTS = {"ACCEPT_AS_ROUTINE", "KEEP_FOR_REVIEW", "MARK_AS_RELEVANT"}

    def assess(self, case_id, data):
        """Record an investigator's judgement beside the machine's, never over it.

        The machine classification and priority as they stood when the
        assessment was made are copied in, so a later re-analysis cannot make it
        look as though the investigator disagreed with something they never saw.
        """
        self.get_case(case_id)
        assessment = (data.get("assessment") or "").strip().upper()
        if assessment not in self.ASSESSMENTS:
            raise ServiceError(
                f"assessment must be one of {', '.join(sorted(self.ASSESSMENTS))}")
        subject_type = (data.get("subject_type") or "").strip().lower()
        subject_id = (data.get("subject_id") or "").strip()
        if not subject_type or not subject_id:
            raise ServiceError("subject_type and subject_id are required")

        machine = self._machine_classification(case_id, subject_type, subject_id)
        assessment_id = f"ASSESS-{identifier()[:8].upper()}"
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO investigator_assessments (id,investigation_id,case_id,subject_type,"
                " subject_id,machine_classification,machine_priority,assessment,note,author,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (assessment_id, case_id, data.get("case_id"), subject_type, subject_id,
                 machine.get("classification"), machine.get("priority"), assessment,
                 str(data.get("note", ""))[:10000] or None,
                 data.get("author") or local_actor(), now()))
            self.casework.audit("assessment.recorded", object_type=subject_type,
                                object_id=subject_id, investigation_id=case_id,
                                detail={"assessment": assessment,
                                        "machine_classification": machine.get("classification")},
                                db=db)
        return self.assessments(case_id, subject_id=subject_id)[0]

    def _machine_classification(self, case_id, subject_type, subject_id):
        """What JOCKY concluded about this subject, as stored."""
        if subject_type in {"activity", "execution_event", "command"}:
            rows = self.store.rows(
                "SELECT triage, investigator_priority FROM execution_events"
                " WHERE investigation_id=? AND reference=?", (case_id, subject_id))
            if rows:
                return {"classification": rows[0]["triage"],
                        "priority": rows[0]["investigator_priority"]}
        if subject_type == "finding":
            rows = self.store.rows(
                "SELECT triage, investigator_priority FROM findings"
                " WHERE investigation_id=? AND reference=?", (case_id, subject_id))
            if rows:
                return {"classification": rows[0]["triage"],
                        "priority": rows[0]["investigator_priority"]}
        if subject_type == "artifact":
            rows = self.store.rows(
                "SELECT recognized_name, recognition_confidence FROM artifact_observations"
                " WHERE investigation_id=? AND reference=?", (case_id, subject_id))
            if rows:
                return {"classification": rows[0]["recognized_name"],
                        "priority": rows[0]["recognition_confidence"]}
        return {"classification": None, "priority": None}

    def assessments(self, case_id, *, subject_id=None, limit=500):
        query = "SELECT * FROM investigator_assessments WHERE investigation_id=?"
        args = [case_id]
        if subject_id:
            query += " AND subject_id=?"
            args.append(subject_id)
        return self.store.rows(query + " ORDER BY created_at DESC LIMIT ?",
                               tuple(args) + (int(limit),))

    def _record_recognition_sources(self, case_id, sources):
        """Keep which recognition sources were readable, alongside the result.

        A collection that recognized nothing because there was no package
        database to read is a different statement from one that read the
        database and found nothing in it. Windows is always the first, and a
        report that did not say so would leave an investigator to assume the
        second.
        """
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                       (f"recognition_sources:{case_id}", encode(sources)))

    def _recognition_summary(self, case_id):
        """What the machine could account for, read back from stored rows."""
        rows = self.store.rows(
            "SELECT recognized_name, recognition_confidence, count(*) AS occurrences"
            " FROM artifact_observations WHERE investigation_id=? AND recognized_name IS NOT NULL"
            " GROUP BY recognized_name, recognition_confidence ORDER BY occurrences DESC, recognized_name",
            (case_id,))
        total = self.store.rows(
            "SELECT count(*) AS n FROM artifact_observations WHERE investigation_id=?",
            (case_id,))[0]["n"]
        events = self.store.rows(
            "SELECT count(*) AS n FROM execution_events WHERE investigation_id=?"
            " AND recognized_name IS NOT NULL", (case_id,))[0]["n"]
        stored = self.store.rows("SELECT value FROM metadata WHERE key=?",
                                 (f"recognition_sources:{case_id}",))
        return {
            "recognition_version": RECOGNITION_VERSION,
            "sources": json.loads(stored[0]["value"]) if stored else [],
            "artifacts_examined": total,
            "artifacts_recognized": sum(row["occurrences"] for row in rows),
            "events_recognized": events,
            "software": [{"name": row["recognized_name"], "count": row["occurrences"],
                          "confidence": row["recognition_confidence"]} for row in rows],
            "note": ("Recognition states what a file is, on the evidence of package metadata and "
                     "installation layout. It is not a statement that the file is safe."),
        }

    def _evidence_payload(self, case_id, action):
        """The payload of the most recent evidence record for one step."""
        for record in reversed(self.related(case_id, "evidence")):
            if record["type"] == action and isinstance(record["payload"], dict):
                return record["payload"]
        return {}

    def report_payload(self, case_id, status=None):
        case = self.get_case(case_id)
        execution = self._evidence_payload(case_id, "EXECUTION HISTORY")
        processes = self._evidence_payload(case_id, "PROCESSES")
        artifacts = [dict(row["payload"]) if isinstance(row["payload"], dict) else {}
                     for row in self.related(case_id, "artifact_observations")]
        findings = self.related(case_id, "findings")
        # The evidence each finding cites, joined back on: a finding that cannot
        # name its evidence is the one thing this report must never contain, and
        # the rows are stored separately.
        citations = {}
        for row in self.related(case_id, "finding_evidence"):
            citations.setdefault(row["finding_id"], []).append(
                {"kind": row["kind"], "id": row["reference"], "detail": row.get("detail")})
        for finding in findings:
            finding["evidence_references"] = citations.get(finding["id"], [])
        limitations = self.related(case_id, "collection_limitations")
        timeline = self.related(case_id, "timeline_events")
        sources = execution.get("sources", []) or []
        available = [source for source in sources if source["status"] == "AVAILABLE"]

        # Events come from the normalized table, not the evidence blob: the blob
        # was written before stable references were assigned, so reading it
        # would produce a report whose entries cite no identifiers.
        transitions = self.related(case_id, "transitions")
        events = [dict(row["payload"], reference=row.get("reference"))
                  for row in self.related(case_id, "execution_events")
                  if isinstance(row.get("payload"), dict)] or (execution.get("events", []) or [])
        # Recognition is read back from storage, not recomputed: the package
        # database is not re-read every time a report is rendered.
        for record in artifacts:
            record.setdefault("recognition", None)
        recognition = self._recognition_summary(case_id)
        # The program-selected sources, so a brief can cite a browser download
        # or a socket record rather than inferring one from timing.
        supplementary = {action: self._evidence_payload(case_id, action)
                         for action in plan_runner.selectable_sources()}
        supplementary = {action: payload for action, payload in supplementary.items() if payload}
        activity = build_activity(events, artifacts=artifacts)
        counts = activity["counts_by_kind"]
        threads = build_threads(activity["groups"])
        significant = build_significant_events(
            activity=activity, findings=findings,
            artifacts={"artifacts": artifacts}, transitions=transitions)

        return {"report_id": identifier(), "schema_version": REPORT_SCHEMA_VERSION, "created_at": now(),
                "investigation_id": case_id, "investigation": case, "status": status or case["status"],
                "versions": versions(), "device": case["device"],
                "summary": self._summary(case, execution, processes, artifacts, findings,
                                         limitations, available, sources, counts, activity),
                "collection_window": execution.get("window"),
                "recognition": recognition,
                "supplementary": supplementary,
                "evidence_sources": self.casework.list_evidence(case_id=case.get("case_id")),
                # Separately named totals. One blurred "events" number invited
                # the reader to treat typed commands as confirmed execution.
                "record_counts": {
                    **counts,
                    "distinct_activity": activity["group_count"],
                    "current_processes": (processes.get("statistics", {}) or {}).get("processes_recorded", 0),
                    "artifacts": len(artifacts),
                    "findings": len(findings),
                    "collection_limitations": len(limitations),
                    "execution_confirmed_records": sum(
                        group["occurrences"] for group in activity["groups"] if group["execution_confirmed"]),
                    "priority_1": activity["triage"]["priorities"].get("PRIORITY_1", 0),
                    "priority_2": activity["triage"]["priorities"].get("PRIORITY_2", 0),
                    "priority_3": activity["triage"]["priorities"].get("PRIORITY_3", 0),
                    "leads": activity["lead_count"],
                    "threads": len(threads),
                    "significant_events": significant["entry_count"],
                },
                "triage": activity["triage"],
                # The investigator's first actionable view, before any listing.
                "leads": activity["leads"],
                "lead_count": activity["lead_count"],
                # Related activity read as one story, and the short timeline.
                "threads": threads,
                "thread_count": len(threads),
                "significant_events": significant,
                "conclusion": self._conclusion(activity, threads, sources, available, limitations),
                "review_reasons": activity["review_reasons"],
                "routine_summary": activity["routine_summary"],
                "activity": activity,
                "historical_execution": {
                    "telemetry_available": bool(available),
                    "platform": execution.get("platform"),
                    "sources": sources,
                    "event_count": execution.get("event_count", 0),
                    "undated_event_count": execution.get("undated_event_count", 0),
                    "truncated": execution.get("truncated", False),
                    "events": events,
                    "limits": execution.get("limits", {}),
                    "statistics": execution.get("statistics", {}),
                },
                "artifacts": artifacts,
                "event_timeline": timeline,
                "findings": findings,
                "collection_limitations": limitations,
                "evidence": self.related(case_id, "evidence"), "executions": self.related(case_id, "executions"),
                "timeline": self.related(case_id, "transitions"),
                "current_process_snapshot": {
                    "collected_at": processes.get("collected_at"),
                    "statistics": processes.get("statistics", {}),
                    "limits": processes.get("limits", {}),
                    "truncated": processes.get("truncated", False),
                },
                # The full per-process listing is bulky and rarely the point of
                # the report, so it sits in an appendix. Nothing is dropped.
                "appendix_process_listing": processes.get("processes", []),
                "unavailable_telemetry": [
                    {"source": source["name"], "status": source["status"], "detail": source["detail"],
                     "location": source.get("location")}
                    for source in sources if source["status"] != "AVAILABLE"
                ],
                "limitations": self._limitations(execution, processes, artifacts, available, sources),
                "provenance": {"collector": "JOCKY local Python service", "classification": "OBSERVED",
                               "offline": True, "telemetry_sources": [source["name"] for source in available],
                               "correlation": "JOCKY rule-based correlation; every finding names its evidence"}}

    @staticmethod
    def _summary(case, execution, processes, artifacts, findings, limitations, available, sources,
                 counts, activity):
        """A short account an investigator can act on, in accurate terms.

        Each figure is named for what it actually is. Calling typed commands and
        execution records one number would invite exactly the confusion this
        report exists to prevent.
        """
        triage = activity["triage"]["counts"]
        priorities = activity["triage"]["priorities"]
        basis = (("Historical execution evidence was collected from "
                  + ", ".join(source["name"] for source in available) + ".")
                 if available else
                 ("No historical execution telemetry was available on this host, so this "
                  "investigation rests on current observation only and cannot establish what ran "
                  "before collection started."))
        confirmed = sum(group["occurrences"] for group in activity["groups"]
                        if group["execution_confirmed"])
        return (
            f"Authorized local defensive collection for '{case['title']}'. {basis} "
            f"The evidence holds {counts['execution_source_records']} execution-source records, "
            f"{counts['command_history_records']} command-history records and "
            f"{counts['session_records']} session records, covering "
            f"{activity['group_count']} distinct activities. "
            f"{confirmed} records come from a source that establishes execution; the remainder "
            "record what was entered or who was logged in, which is not the same thing. "
            f"{priorities.get('PRIORITY_1', 0)} records are ranked investigate-first and "
            f"{priorities.get('PRIORITY_2', 0)} merit review; the remaining "
            f"{priorities.get('PRIORITY_3', 0)} are informational, largely ordinary system "
            "activity and commands recognised as routine. "
            f"By what the evidence supports rather than urgency, {triage.get('POTENTIALLY_HARMFUL', 0)} "
            f"records carry a concern signal, {triage.get('NEEDS_REVIEW', 0)} are uncertain and "
            f"{triage.get('NOT_HARMFUL_ON_AVAILABLE_EVIDENCE', 0)} show nothing of concern in what "
            "was collected. "
            f"{len(findings)} findings were raised against "
            f"{(processes.get('statistics', {}) or {}).get('processes_recorded', 0)} current processes "
            f"and {len(artifacts)} artifacts. "
            f"{len(limitations)} collection limitations are recorded separately, including "
            f"{len([s for s in sources if s['status'] != 'AVAILABLE'])} telemetry sources that could "
            "not be read. "
            "Triage categories are not verdicts: 'not harmful based on available evidence' means "
            "nothing in what was collected stood out, not that the activity was safe. Missing "
            "command-line arguments are recorded as a collection limitation, not as a reason for "
            "suspicion."
        )

    @staticmethod
    def _conclusion(activity, threads, sources, available, limitations):
        """A plain reading of the numbers, not the numbers again.

        Written from what was collected, in the order an investigator asks: is
        anything urgent, what deserves a look, what is the rest, and what could
        not be seen. It never reaches for a reassuring phrase the evidence does
        not support.
        """
        priorities = activity["triage"]["priorities"]
        first = priorities.get("PRIORITY_1", 0)
        second = priorities.get("PRIORITY_2", 0)
        third = priorities.get("PRIORITY_3", 0)
        leads = activity["lead_count"]

        sentences = []
        if first:
            sentences.append(
                f"{first} records are ranked investigate-first: several independent signals "
                "combine on each. They are listed first below and should be read before anything "
                "else.")
        else:
            sentences.append(
                "No activity in this collection combined enough signals to rank "
                "investigate-first. That reflects what was collected, not a clean bill of health.")
        if second:
            sentences.append(
                f"{second} records across {leads} distinct pattern"
                f"{'s' if leads != 1 else ''} warrant review: each has a concrete reason for "
                "attention, with evidence that is incomplete or uncorroborated.")
        if threads:
            sentences.append(
                f"{len(threads)} groups of related activity were identified and are summarised as "
                "investigation threads, so a sequence of related commands reads as one story "
                "rather than as separate records.")
        sentences.append(
            f"The remaining {third} records are informational: ordinary operating-system and "
            "desktop service activity, commands recognised as routine, and records whose only gap "
            "is that the source did not capture their arguments.")
        unavailable = [source["name"] for source in sources if source["status"] != "AVAILABLE"]
        if unavailable:
            sentences.append(
                f"{', '.join(unavailable)} could not be read, so any activity only those sources "
                "would have recorded is outside this investigation's evidence.")
        if not available:
            sentences.append(
                "No historical execution source was available at all, so this collection cannot "
                "establish what ran before it started.")
        return " ".join(sentences)

    @staticmethod
    def _limitations(execution, processes, artifacts, available, sources):
        limitations = [
            "CURRENT OBSERVATION: a process snapshot records the present. It does not establish historical execution.",
            "HISTORICAL EVIDENCE: each source records something different, and each event states what its source proves.",
            "A hash compares bytes; it does not prove authenticity or acquisition-chain integrity.",
            "Only explicitly selected file sources and files named by execution evidence were inspected. "
            "No whole-disk acquisition was performed.",
            "Live collection changes host activity and cannot provide an atomic snapshot of the device.",
            "Unavailable, skipped and truncated fields remain explicit in each evidence payload.",
            "Findings are rule-based triage, not malware verdicts. A name, extension or directory is a reason "
            "to look, never a conclusion.",
        ]
        if not available:
            limitations.append(
                "No historical execution source was collected on this host. Absence of execution evidence "
                "here reflects absent telemetry, not absent activity.")
        else:
            limitations.append(
                "Absence of an execution event is not evidence that a program did not run: every source has "
                "a retention limit and records only what it was configured to record.")
        if execution.get("truncated"):
            limitations.append("Historical execution collection reached its bounds; older events were not read.")
        if execution.get("undated_event_count"):
            limitations.append(
                f"{execution['undated_event_count']} execution records carry no timestamp because their "
                "source does not record one; they cannot be placed on the timeline.")
        if processes.get("truncated"):
            limitations.append(
                f"The process snapshot was truncated at {processes.get('limits', {}).get('max_processes')} "
                "processes; higher process identifiers were not recorded.")
        if not (execution.get("limits", {}) or {}).get("command_lines_collected", False):
            limitations.append(
                "Command-line arguments were not collected. They frequently carry credentials and are "
                "opt-in per investigation; when enabled they are redacted, which is a mitigation and not a "
                "guarantee.")
        missing = sum(1 for record in artifacts if record.get("collection_status") == "MISSING")
        if missing:
            limitations.append(
                f"{missing} artifacts named by execution evidence were absent at collection time; their "
                "contents could not be examined.")
        return limitations

    # --- review briefs and the routine report --------------------------------
    def _latest_report(self, case_id):
        """The stored report for an investigation, or a freshly assembled one.

        A brief reads stored evidence rather than re-running collection. When a
        collection has finished its report is on record; when it has not, the
        payload is assembled from the same stored rows.
        """
        reports = self.related(case_id, "reports")
        if reports and isinstance(reports[-1].get("payload"), dict):
            return reports[-1]["payload"]
        return self.report_payload(case_id)

    def brief(self, case_id, *, subject_type, subject_id, persist=True):
        """Generate a review brief for one subject and record that it was made."""
        report = self._latest_report(case_id)
        try:
            payload = build_brief(report, subject_type=subject_type, subject_id=subject_id)
        except BriefError as error:
            raise ServiceError(str(error), "not_found", 404) from error
        if not persist:
            return payload

        brief_id = f"BRIEF-{identifier()[:8].upper()}"
        payload["brief_id"] = brief_id
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO review_briefs (id,investigation_id,case_id,subject_type,subject_id,"
                " created_at,author,payload,evidence_ids,versions) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (brief_id, case_id, payload.get("case_id"), payload["subject"]["type"],
                 payload["subject"]["id"], now(), local_actor(), encode(payload),
                 encode(payload["evidence_ids"]), encode(versions())))
            self.casework.audit("brief.generated", object_type=payload["subject"]["type"],
                                object_id=payload["subject"]["id"], investigation_id=case_id,
                                case_id=payload.get("case_id"),
                                detail={"brief_id": brief_id,
                                        "evidence_count": len(payload["evidence_ids"])}, db=db)
        return payload

    def briefs(self, case_id, limit=200):
        rows = self.store.rows(
            "SELECT * FROM review_briefs WHERE investigation_id=? ORDER BY created_at DESC LIMIT ?",
            (case_id, int(limit)))
        for row in rows:
            for key in ("payload", "evidence_ids", "versions"):
                row[key] = json.loads(row[key]) if row[key] else None
        return rows

    def routine_activity(self, case_id):
        """The grouped routine/recognized activity, for the separate report."""
        report = self._latest_report(case_id)
        return report, build_routine(report.get("activity") or {})

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
