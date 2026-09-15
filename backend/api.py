"""Authenticated API v1. Handlers delegate collection and persistence to services."""
import hmac
import io
import json
import secrets
import shutil
import sqlite3

from flask import Flask, request, send_file
from werkzeug.exceptions import HTTPException

from backend.pdf_report import page_count, render_investigator_pdf, render_pdf
from backend.casework import CaseworkError
from backend.service import ServiceError
from backend.storage import StorageError
from backend.versions import versions
from compiler.Language_meta import LANGUAGE_REFERENCE


# Sources each platform collector attempts. Availability is decided per run.
SOURCE_NAMES = {
    "Linux": ["systemd journal", "shell history", "kernel audit log", "process accounting",
              "login sessions (wtmp)"],
    "Windows": ["Windows Security 4688", "Sysmon Event 1", "PowerShell operational log",
                "Windows Prefetch", "UserAssist"],
}


def create_app(service, token=None, instance_id=None, shutdown=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32 * 1024 * 1024, SESSION_TOKEN=token or secrets.token_urlsafe(32), INSTANCE_ID=instance_id or secrets.token_hex(16))

    #: Routes an enrolled endpoint calls. They authenticate with the endpoint's
    #: own credential rather than the local UI session, and they are the only
    #: routes reachable from off this machine.
    ENDPOINT_ROUTES = ("/api/v1/endpoints/enroll", "/api/v1/endpoints/heartbeat",
                       "/api/v1/endpoints/tasks/claim")

    def is_endpoint_route():
        path = request.path
        return path in ENDPOINT_ROUTES or (
            path.startswith("/api/v1/endpoints/tasks/") and path.endswith("/result"))

    @app.before_request
    def authenticate():
        if is_endpoint_route():
            # An endpoint agent runs on another machine by design, so the
            # loopback rule cannot apply to it. It presents its own credential
            # instead, and the routes it can reach ask for forensic collection
            # and nothing else.
            if request.path == "/api/v1/endpoints/enroll":
                return None
            credential = request.headers.get("Authorization", "")
            token = credential[7:] if credential.startswith("Bearer ") else ""
            request.endpoint_identity = service.fleet.authenticate(
                request.headers.get("X-Jocky-Endpoint", ""), token)
            return None
        if request.remote_addr not in ("127.0.0.1", None):
            raise ServiceError("Loopback connections only", "authentication_error", 401)
        if request.headers.get("Origin"):
            raise ServiceError("Browser origins are not permitted", "authentication_error", 403)
        credential = request.headers.get("Authorization", "")
        instance = request.headers.get("X-Jocky-Instance", "")
        if not hmac.compare_digest(credential, "Bearer " + app.config["SESSION_TOKEN"]) or not hmac.compare_digest(instance, app.config["INSTANCE_ID"]):
            raise ServiceError("Invalid local session", "authentication_error", 401)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(Exception)
    def failure(error):
        if isinstance(error, (ServiceError, CaseworkError)):
            status, code, message = error.status, error.code, str(error)
        elif isinstance(error, (sqlite3.Error, StorageError, OSError)):
            status, code, message = 503, "storage_unavailable", "Storage operation failed; committed records were preserved. Check available space and permissions."
        elif isinstance(error, HTTPException):
            status, code, message = error.code, "request_error", error.description
        else:
            app.logger.exception("Unhandled application request")
            status, code, message = 500, "internal_error", "Internal application error"
        return {"error": {"code": code, "message": message}, "api_version": 1}, status

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ServiceError("Request body must be a JSON object")
        return value

    @app.get("/health")
    @app.get("/api/v1/health")
    @app.get("/api/v1/status")
    def health():
        return {"status": "JOCKY local service ready", "engine": "online", "ready": not service.stopping.is_set() and not service.storage_failure,
                "instance_id": app.config["INSTANCE_ID"], "versions": versions(),
                "storage": {"mode": "portable" if service.store.paths.portable else "system", "path": str(service.store.paths.data),
                            "free_bytes": shutil.disk_usage(service.store.paths.data).free, "error": service.storage_failure}}

    @app.get("/commands")
    @app.get("/api/v1/commands")
    def commands():
        return {"status": "success", "schema_version": 1, "commands": LANGUAGE_REFERENCE}

    @app.get("/api/v1/capabilities")
    def capabilities():
        # Which sources exist for this platform is static; whether each one is
        # readable is decided per collection and reported in the report, so this
        # advertises the attempt rather than a result it has not established.
        from analysis.execution_history import collector_for
        from analysis.execution_model import CollectionWindow
        from analysis.artifacts import MAX_ARTIFACTS
        from backend.collectors import DEFAULT_MAX_PROCESSES, MAX_PROCESSES_CEILING
        collector = collector_for()
        return {"versions": versions(), "current_process_snapshot": True,
                "historical_execution_telemetry": collector.platform_name in {"Linux", "Windows"},
                "historical_execution_platform": collector.platform_name,
                "historical_execution_sources": SOURCE_NAMES.get(collector.platform_name, []),
                "historical_execution_availability": (
                    "Each source is probed at collection time and reported as AVAILABLE, NOT_AVAILABLE, "
                    "NOT_ENABLED or PERMISSION_DENIED. JOCKY never enables a disabled source."),
                "collection_window_default_hours": CollectionWindow.DEFAULT_HOURS,
                "collection_window_max_hours": CollectionWindow.MAX_HOURS,
                "command_line_collection": "opt-in per investigation; redacted when enabled",
                "max_processes_default": DEFAULT_MAX_PROCESSES, "max_processes_ceiling": MAX_PROCESSES_CEILING,
                "max_artifacts": MAX_ARTIFACTS,
                "offline_pdf": True, "max_sources": 20, "max_hash_bytes": 134217728,
                "encryption": "explicit passphrase export only", "collection_cancellation": "between bounded steps"}

    @app.post("/command")
    @app.post("/api/v1/command")
    def command():
        data = body()
        return service.command(data.get("command"), data.get("investigation_id"))

    @app.route("/api/v1/investigations", methods=["GET", "POST"])
    def investigations():
        if request.method == "POST":
            return service.create_case(body()), 201
        return {"items": service.list_cases(request.args.get("search", ""), request.args.get("status")), "limit": 1000}

    @app.get("/api/v1/investigations/<case_id>")
    def investigation(case_id):
        return service.get_case(case_id)

    @app.post("/api/v1/investigations/<case_id>/collect")
    def collect(case_id):
        return service.collect(case_id, body()), 202

    @app.post("/api/v1/investigations/<case_id>/cancel")
    def cancel(case_id):
        return service.cancel(case_id), 202

    # Readable URL names for the stored collections. The service validates the
    # resolved table name, so an unknown alias falls through to that check.
    COLLECTIONS = {"timeline": "transitions", "artifacts": "artifact_observations",
                   "execution-events": "execution_events", "event-timeline": "timeline_events",
                   "finding-evidence": "finding_evidence",
                   "collection-limitations": "collection_limitations"}

    @app.get("/api/v1/investigations/<case_id>/<collection>")
    def related(case_id, collection):
        return {"items": service.related(case_id, COLLECTIONS.get(collection, collection))}

    @app.get("/api/v1/reports/<report_id>")
    def report(report_id):
        return service.get_report(report_id)

    @app.post("/api/v1/reports/<report_id>/export")
    def export_command_report(report_id):
        body()
        return send_file(io.BytesIO(render_pdf(service.get_report(report_id))), mimetype="application/pdf", as_attachment=True, download_name=f"jocky-{report_id}.pdf")

    @app.get("/api/v1/history")
    def history():
        rows = service.store.rows("SELECT * FROM executions ORDER BY created_at DESC LIMIT 1000")
        for row in rows:
            for key in ("result", "error", "normalized_command", "versions"):
                row[key] = json.loads(row[key]) if row[key] else None
        return {"items": rows, "limit": 1000}

    @app.post("/api/v1/investigations/<case_id>/report/export")
    def export(case_id):
        data = body()
        reports = service.related(case_id, "reports")
        if not reports:
            raise ServiceError("No completed report is available", "conflict", 409)
        report = reports[-1]["payload"]
        if data.get("format", "pdf") == "json":
            return send_file(io.BytesIO(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode()), mimetype="application/json", as_attachment=True, download_name=f"jocky-{case_id}.json")
        if data.get("format", "pdf") != "pdf":
            raise ServiceError("format must be pdf or json")
        # The investigator report by default. `detailed` appends every appendix,
        # which is the seventy-page document -- available to anyone who asks for
        # it, and never what an investigator gets by accident.
        detailed = bool(data.get("detailed"))
        pdf = render_pdf(report, detailed=detailed)
        name = ("JOCKY_Full_Report_" if detailed else "JOCKY_Investigator_Report_") + case_id
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                         download_name=f"{name}.pdf")

    @app.post("/api/v1/storage/backup")
    def backup():
        return {"path": str(service.store.backup())}, 201

    @app.post("/api/v1/storage/import-workstation")
    def import_workstation():
        from backend.workstation_view import import_legacy
        path = body().get("path")
        if not isinstance(path, str) or not path:
            raise ServiceError("path is required")
        return import_legacy(service, path)

    @app.post("/api/v1/storage/import-ledger")
    def import_ledger():
        path = body().get("path")
        if not isinstance(path, str) or not path:
            raise ServiceError("path is required")
        return service.store.migrate_ledger(path)

    @app.post("/api/v1/history/clear")
    def clear_history():
        body()
        from backend.workstation_view import clear_history as clear
        return clear(service)

    @app.route("/api/v1/workstation", methods=["GET", "POST"])
    def workstation():
        from backend.workstation_view import view, save_metadata
        return view(service) if request.method == "GET" else save_metadata(service, body())

    @app.post("/api/v1/evidence/export-encrypted")
    def encrypt_export():
        from crypto.crypto import encrypt_file
        data = body()
        for key in ("path", "destination", "passphrase"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ServiceError(f"{key} is required")
        try:
            return encrypt_file(data["path"], data["destination"], passphrase=data["passphrase"]), 201
        except ValueError as error:
            raise ServiceError(str(error)) from error


    # --- cases, evidence sources, audit and notes --------------------------
    # Kept separate from /investigations on purpose: an investigation is one
    # collection run, a case is the enquiry that may contain several of them.

    @app.route("/api/v1/cases", methods=["GET", "POST"])
    def cases():
        if request.method == "POST":
            return service.casework.create_case(body()), 201
        return {"items": service.casework.list_cases(status=request.args.get("status"))}

    @app.get("/api/v1/cases/<case_id>")
    def case_detail(case_id):
        return service.casework.get_case(case_id)

    @app.post("/api/v1/cases/<case_id>/close")
    def case_close(case_id):
        return service.casework.close_case(case_id, reopen=bool(body().get("reopen")))

    @app.get("/api/v1/cases/<case_id>/investigations")
    def case_investigations(case_id):
        service.casework.get_case(case_id)
        rows = service.store.rows(
            "SELECT id FROM investigations WHERE case_id=? ORDER BY created_at DESC", (case_id,))
        return {"items": [service.get_case(row["id"]) for row in rows]}

    @app.route("/api/v1/evidence-sources", methods=["GET", "POST"])
    def evidence_sources():
        if request.method == "POST":
            return service.casework.register_evidence(body()), 201
        return {"items": service.casework.list_evidence(case_id=request.args.get("case_id"))}

    @app.get("/api/v1/evidence-sources/<evidence_id>")
    def evidence_source(evidence_id):
        return service.casework.get_evidence(evidence_id)

    @app.post("/api/v1/evidence-sources/<evidence_id>/verify")
    def evidence_verify(evidence_id):
        body()
        return service.casework.verify_evidence(evidence_id)

    @app.get("/api/v1/audit")
    def audit():
        return {"items": service.casework.audit_trail(case_id=request.args.get("case_id"),
                                                      limit=int(request.args.get("limit", 1000))),
                "note": ("The audit trail records what JOCKY and the investigator did. It is not "
                         "evidence about the examined host.")}

    @app.route("/api/v1/notes", methods=["GET", "POST"])
    def notes():
        if request.method == "POST":
            return service.casework.add_note(body()), 201
        return {"items": service.casework.list_notes(
            case_id=request.args.get("case_id"), subject_type=request.args.get("subject_type"),
            subject_id=request.args.get("subject_id"))}

    @app.get("/api/v1/collection-sources")
    def collection_sources():
        from backend import plan_runner
        return {"baseline": ["SYSTEM", "PROCESSES", "EXECUTION", "FILES"],
                "selectable": [{"source": name,
                                "description": plan_runner.SOURCE_DESCRIPTIONS[name],
                                "needs_argument": name in plan_runner.NEEDS_ARGUMENT}
                               for name in plan_runner.selectable_sources()]}

    @app.get("/api/v1/investigations/<case_id>/program")
    def investigation_program(case_id):
        service.get_case(case_id)
        rows = service.store.rows(
            "SELECT * FROM investigation_programs WHERE investigation_id=? ORDER BY created_at",
            (case_id,))
        for row in rows:
            for key in ("ir", "plan", "versions"):
                row[key] = json.loads(row[key]) if row[key] else None
        return {"items": rows}

    @app.post("/api/v1/programs/compile")
    def compile_investigation_program():
        """Check a program and show its plan without collecting anything."""
        from compiler.investigation import ProgramError, compile_program, describe
        from compiler.plan import build_plan, describe_plan
        data = body()
        text = data.get("program")
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("program is required")
        try:
            ir = compile_program(text)
            plan = build_plan(ir, platform_name=data.get("platform"))
        except ProgramError as error:
            raise ServiceError(str(error), "program_error") from error
        return {"ir": ir, "plan": plan, "explanation": describe(ir),
                "plan_explanation": describe_plan(plan)}


    # --- authorized endpoints --------------------------------------------
    # An endpoint receives named forensic collection requests. There is no
    # route here that carries a command, and adding one would defeat the reason
    # an agent can be deployed at all.

    @app.get("/api/v1/endpoints")
    def endpoints():
        return {"items": service.fleet.list_endpoints(),
                "stale_after_seconds": service.fleet.STALE_AFTER_SECONDS}

    @app.get("/api/v1/endpoints/<endpoint_id>")
    def endpoint_detail(endpoint_id):
        return service.fleet.get_endpoint(endpoint_id)

    @app.post("/api/v1/endpoints/authorize")
    def authorize_endpoint():
        return service.fleet.issue_enrollment_token(body()), 201

    @app.post("/api/v1/endpoints/<endpoint_id>/revoke")
    def revoke_endpoint(endpoint_id):
        body()
        return service.fleet.revoke(endpoint_id)

    @app.get("/api/v1/endpoints/<endpoint_id>/events")
    def endpoint_events(endpoint_id):
        service.fleet.get_endpoint(endpoint_id)
        return {"items": service.fleet.events(endpoint_id)}

    @app.get("/api/v1/endpoint-tasks")
    def endpoint_tasks():
        return {"items": service.fleet.tasks(
            endpoint_id=request.args.get("endpoint_id"),
            investigation_id=request.args.get("investigation_id"))}

    @app.post("/api/v1/endpoint-tasks/sweep")
    def sweep_endpoint_tasks():
        body()
        return service.fleet.sweep()

    @app.post("/api/v1/collections/dispatch")
    def dispatch_collection():
        """Queue a compiled plan on one or more authorized endpoints."""
        from compiler.investigation import ProgramError, compile_program
        from compiler.plan import build_plan
        data = body()
        text = data.get("program")
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("program is required")
        try:
            plan = build_plan(compile_program(text), platform_name=data.get("platform"))
        except ProgramError as error:
            raise ServiceError(str(error), "program_error") from error
        endpoint_ids = data.get("endpoints")
        if not isinstance(endpoint_ids, list) or not endpoint_ids:
            raise ServiceError("endpoints must be a non-empty list of endpoint ids")
        return service.fleet.dispatch_plan(
            plan=plan, endpoint_ids=endpoint_ids,
            investigation_id=data.get("investigation_id"), case_id=data.get("case_id")), 202

    @app.get("/api/v1/fleet/correlation")
    def fleet_correlation():
        from analysis.fleet_correlation import correlate_fleet
        return correlate_fleet(service.fleet.tasks(
            investigation_id=request.args.get("investigation_id")),
            endpoints=service.fleet.list_endpoints())

    # --- endpoint-facing routes -------------------------------------------

    @app.post("/api/v1/endpoints/enroll")
    def endpoint_enroll():
        return service.fleet.enroll(body()), 201

    @app.post("/api/v1/endpoints/heartbeat")
    def endpoint_heartbeat():
        return service.fleet.heartbeat(request.endpoint_identity, body())

    @app.post("/api/v1/endpoints/tasks/claim")
    def endpoint_claim():
        return service.fleet.claim_tasks(request.endpoint_identity, body().get("limit", 4))

    @app.post("/api/v1/endpoints/tasks/<task_id>/result")
    def endpoint_result(task_id):
        return service.fleet.submit_result(request.endpoint_identity, task_id, body()), 201


    # --- review briefs and the routine activity report ---------------------
    # A brief answers "what is this and do I care" about one subject, from
    # evidence already stored. It never re-runs collection.

    @app.post("/api/v1/investigations/<case_id>/briefs")
    def create_brief(case_id):
        data = body()
        return service.brief(case_id, subject_type=data.get("subject_type"),
                             subject_id=data.get("subject_id")), 201

    @app.get("/api/v1/investigations/<case_id>/briefs")
    def list_briefs(case_id):
        service.get_case(case_id)
        return {"items": service.briefs(case_id)}

    @app.post("/api/v1/investigations/<case_id>/briefs/export")
    def export_brief(case_id):
        """The same brief as a one or two page PDF, ready to attach to a case."""
        from backend.brief_pdf import render_brief_pdf
        data = body()
        brief = service.brief(case_id, subject_type=data.get("subject_type"),
                              subject_id=data.get("subject_id"))
        subject = brief["subject"]["id"]
        if data.get("format") == "json":
            return send_file(
                io.BytesIO(json.dumps(brief, indent=2, default=str).encode()),
                mimetype="application/json", as_attachment=True,
                download_name=f"JOCKY_ReviewBrief_{subject}.json")
        return send_file(io.BytesIO(render_brief_pdf(brief)), mimetype="application/pdf",
                         as_attachment=True,
                         download_name=f"JOCKY_ReviewBrief_{subject}.pdf")

    @app.get("/api/v1/investigations/<case_id>/routine")
    def routine_activity(case_id):
        _report, routine = service.routine_activity(case_id)
        return routine

    @app.post("/api/v1/investigations/<case_id>/routine/export")
    def export_routine(case_id):
        """Deliberately a separate document, never the primary report."""
        from backend.brief_pdf import render_routine_pdf
        data = body()
        report, routine = service.routine_activity(case_id)
        if data.get("format") == "json":
            return send_file(
                io.BytesIO(json.dumps(routine, indent=2, default=str).encode()),
                mimetype="application/json", as_attachment=True,
                download_name=f"jocky-routine-{case_id}.json")
        pdf = render_routine_pdf(report, routine, detailed=bool(data.get("detailed")))
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                         download_name=f"jocky-routine-{case_id}.pdf")


    # --- memory analysis ---------------------------------------------------
    # An image is registered and hashed before it is analysed, and re-verified
    # immediately before: attributing findings to bytes that have since changed
    # is the one thing this workflow exists to prevent.

    @app.get("/api/v1/memory/capability")
    def memory_capability():
        return service.memory.capability()

    @app.post("/api/v1/memory/images")
    def register_memory_image():
        return service.memory.register_image(body()), 201

    @app.route("/api/v1/memory/analyses", methods=["GET", "POST"])
    def memory_analyses():
        if request.method == "POST":
            return service.memory.analyse(body()), 201
        return {"items": service.memory.list(
            case_id=request.args.get("case_id"),
            investigation_id=request.args.get("investigation_id"))}

    @app.get("/api/v1/memory/analyses/<analysis_id>")
    def memory_analysis(analysis_id):
        return service.memory.get(analysis_id)


    # --- search, assessments, case summary and the evidence package --------

    @app.get("/api/v1/investigations/<case_id>/search")
    def investigation_search(case_id):
        service.get_case(case_id)
        kinds = request.args.get("kinds")
        return service.search(case_id, request.args.get("q", ""),
                              kinds=kinds.split(",") if kinds else None)

    @app.route("/api/v1/investigations/<case_id>/assessments", methods=["GET", "POST"])
    def assessments(case_id):
        if request.method == "POST":
            return service.assess(case_id, body()), 201
        service.get_case(case_id)
        return {"items": service.assessments(case_id, subject_id=request.args.get("subject_id")),
                "note": ("An investigator assessment is recorded beside the machine's "
                         "classification, never over it. The machine's conclusion is immutable.")}

    @app.get("/api/v1/investigations/<case_id>/summary")
    def case_summary(case_id):
        service.get_case(case_id)
        return service.case_summary(case_id, persist=True)

    @app.get("/api/v1/investigations/<case_id>/narrative")
    def narrative(case_id):
        service.get_case(case_id)
        return {"items": service.narrative(case_id),
                "note": "Each generated statement, with the evidence identifiers behind it."}

    @app.post("/api/v1/investigations/<case_id>/package")
    def evidence_package(case_id):
        """The complete, self-describing evidence package."""
        from backend.brief_pdf import render_routine_pdf
        from backend.evidence_package import build_package
        body()
        report, routine = service.routine_activity(case_id)
        case = None
        if report.get("investigation", {}).get("case_id"):
            case = service.casework.get_case(report["investigation"]["case_id"])
        payload = build_package(
            report=report, pdf=render_investigator_pdf(report), full_pdf=render_pdf(report),
            case=case,
            endpoints=service.fleet.list_endpoints(),
            evidence_sources=service.casework.list_evidence(
                case_id=(case or {}).get("id")),
            programs=service.store.rows(
                "SELECT * FROM investigation_programs WHERE investigation_id=?", (case_id,)),
            audit_events=service.casework.audit_trail(case_id=(case or {}).get("id")),
            routine=routine, case_summary=service.case_summary(case_id, persist=True),
            narrative=service.narrative(case_id), briefs=service.briefs(case_id))
        return send_file(io.BytesIO(payload), mimetype="application/zip", as_attachment=True,
                         download_name=f"JOCKY_Evidence_Package_{case_id}.zip")


    @app.get("/api/v1/investigations/<case_id>/artifacts-available")
    def report_artifacts_available(case_id):
        """What this investigation can produce, and how large each one is.

        Rendered here rather than guessed by the client, so the page counts it
        shows are the ones in the documents. A client that estimated them would
        eventually be wrong, and a wrong page count on a forensic report is the
        kind of small dishonesty that costs trust in the rest.
        """
        from backend.brief_pdf import render_routine_pdf
        report, routine = service.routine_activity(case_id)
        investigator = render_investigator_pdf(report)
        routine_pdf = render_routine_pdf(report, routine)
        counts = report.get("record_counts") or {}
        return {
            "investigator_report": {
                "name": f"JOCKY_Investigator_Report_{case_id}.pdf",
                "pages": page_count(investigator), "bytes": len(investigator),
                "description": "The investigator-facing narrative. No raw evidence.",
            },
            "routine_activity": {
                "name": f"jocky-routine-{case_id}.pdf",
                "pages": page_count(routine_pdf), "bytes": len(routine_pdf),
                "groups": routine.get("group_count", 0),
                "records": (routine.get("totals") or {}).get("records", 0),
                "description": ("Activity the machine's own records account for, grouped. "
                                "Optional, and never the primary report."),
            },
            "evidence_package": {
                "name": f"JOCKY_Evidence_Package_{case_id}.zip",
                "records": sum(value for key, value in counts.items()
                               if key in ("execution_source_records", "command_history_records",
                                          "session_records", "artifacts", "findings")),
                "record_counts": counts,
                "description": ("Everything collected, with a manifest and a digest for every "
                                "file. Nothing was removed from it to shorten the report."),
            },
            "review_briefs": {
                "generated": len(service.briefs(case_id)),
                "description": ("One or two pages about a single artifact, finding, activity, "
                                "lead or thread. Generated on request."),
            },
            "note": ("Three documents, each answering a different question: what do I need to "
                     "know, tell me about this one thing, show me everything."),
        }

    @app.post("/api/v1/shutdown")
    def stop():
        if shutdown is None:
            raise ServiceError("Shutdown is unavailable in this host", "unavailable", 503)
        shutdown.set()
        return {"state": "stopping", "instance_id": app.config["INSTANCE_ID"]}, 202

    return app
