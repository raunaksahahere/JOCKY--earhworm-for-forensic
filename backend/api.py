"""Authenticated API v1. Handlers delegate collection and persistence to services."""
import hmac
import io
import json
import secrets
import shutil
import sqlite3

from flask import Flask, request, send_file
from werkzeug.exceptions import HTTPException

from backend.pdf_report import render_pdf
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
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, SESSION_TOKEN=token or secrets.token_urlsafe(32), INSTANCE_ID=instance_id or secrets.token_hex(16))

    @app.before_request
    def authenticate():
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
        if isinstance(error, ServiceError):
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
        return send_file(io.BytesIO(render_pdf(report)), mimetype="application/pdf", as_attachment=True, download_name=f"jocky-{case_id}.pdf")

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

    @app.post("/api/v1/shutdown")
    def stop():
        if shutdown is None:
            raise ServiceError("Shutdown is unavailable in this host", "unavailable", 503)
        shutdown.set()
        return {"state": "stopping", "instance_id": app.config["INSTANCE_ID"]}, 202

    return app
