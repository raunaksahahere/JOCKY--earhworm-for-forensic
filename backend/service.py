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
from analysis.activity import assign_references, build_activity
from analysis.artifacts import artifact_from_hash_result, collect_artifacts, merge_artifacts
from analysis.correlation import correlate
from analysis.execution_history import collect_execution_history
from analysis.execution_model import CollectionWindow
from analysis.files import list_files
from analysis.system import get_system_info
from analysis.threads import build_threads
from analysis.timeline import build_significant_events, build_timeline
from backend.collectors import DEFAULT_MAX_PROCESSES, MAX_PROCESSES_CEILING, process_snapshot
from backend.storage import encode, identifier, now
from backend.versions import versions, REPORT_SCHEMA_VERSION
from compiler.parser import parse_validated_command
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
        return {"window_hours": window.requested_hours, "max_processes": maximum,
                "include_command_lines": include}

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
                          activity):
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
                    "  reference,triage,investigator_priority,priority_score)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                     triage_of(event.get("reference"), "score")))
            for record in artifacts.get("artifacts", []) or []:
                db.execute(
                    "INSERT INTO artifact_observations"
                    " (id,investigation_id,evidence_id,path,filename,extension,size_bytes,modified,"
                    "  hash,collection_status,source,payload,reference)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier(), case_id, artifact_evidence, record["path"], record["filename"],
                     record.get("extension"), record.get("size_bytes"), record.get("modified"),
                     record.get("hash"), record["collection_status"], record.get("source", "unknown"),
                     encode(record), record.get("reference")))
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

    def _collect(self, case_id, paths, options=None):
        options = options or {"window_hours": None, "max_processes": DEFAULT_MAX_PROCESSES,
                              "include_command_lines": False}
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

            self.transition(case_id, "analyzing")
            evidence_ids = {action: evidence_id for action, _result, evidence_id in results}
            # Short, stable identifiers first: findings cite them, the report
            # prints them, and an investigator uses them to find the record.
            assign_references(execution.get("events", []) or [],
                              artifacts=artifacts.get("artifacts", []) or [])
            correlation = correlate(execution=execution, artifacts=artifacts, processes=processes)
            activity = build_activity(execution.get("events", []) or [],
                                      artifacts=artifacts.get("artifacts", []) or [])
            self._persist_analysis(case_id, execution, artifacts, correlation, processes,
                                   evidence_ids, activity)

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
