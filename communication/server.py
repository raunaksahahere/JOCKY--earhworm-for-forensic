import os
import time

import psutil
from flask import Flask, request
from flask_cors import CORS

from communication.dispatcher import execute_command
from compiler.Language_meta import LANGUAGE_REFERENCE
from compiler.commands import CommandError, CommandValidationError, SCHEMA_VERSION
from compiler.parser import parse_validated_command
from analysis.ledger import LedgerError
from reports.report import create_report

app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "JOCKY API is running",
        "engine": "online",
    }


@app.route("/commands", methods=["GET"])
def commands():
    """Expose the supported command reference so the frontend never has
    to hardcode syntax that could drift from the grammar."""
    return {"status": "success", "schema_version": SCHEMA_VERSION, "commands": LANGUAGE_REFERENCE}


def _error_details(error: Exception) -> tuple[str, str, int]:
    if isinstance(error, CommandError):
        return error.code, error.kind, 400
    for error_type, code in (
        (FileNotFoundError, "not_found"), (PermissionError, "permission_denied"),
        (NotADirectoryError, "not_a_directory"), (LedgerError, "ledger_unavailable"),
        (psutil.AccessDenied, "permission_denied"), (psutil.Error, "collection_failed"),
        (ValueError, "invalid_argument"), (OSError, "io_error"),
        (RuntimeError, "execution_failed"),
    ):
        if isinstance(error, error_type):
            return code, "execution", 400
    return "internal_error", "internal", 500


@app.route("/command", methods=["POST"])
def command():
    start = time.perf_counter()
    command_text = ""
    parsed = None
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise CommandValidationError("Request body must be a JSON object")
        value = data.get("command")
        if not isinstance(value, str):
            raise CommandValidationError("command must be a string")
        command_text = value.strip(" \t")
        parsed = parse_validated_command(command_text)
        result = execute_command(parsed.to_dispatch_dict())
        report = create_report(
            command=command_text, action=parsed.action, target=parsed.path,
            result=result, execution_time_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        report["normalized_command"] = parsed.to_dict()
        return {
            "status": "success", "command": command_text, "result": result,
            "report": report, "error": None, "error_code": None, "error_kind": None,
            "normalized_command": parsed.to_dict(),
        }
    except Exception as error:
        code, kind, http_status = _error_details(error)
        if http_status == 500:
            app.logger.exception("Unexpected command execution failure")
        message = "Internal command execution error" if http_status == 500 else str(error)
        report = create_report(
            command=command_text, action=parsed.action if parsed else None,
            target=parsed.path if parsed else None, status="failed", result=None,
            execution_time_ms=round((time.perf_counter() - start) * 1000, 2), errors=[message],
        )
        normalized = parsed.to_dict() if parsed else None
        report.update(normalized_command=normalized, error_code=code, error_kind=kind)
        return {
            "status": "error", "command": command_text, "result": None,
            "report": report, "error": message, "error_code": code, "error_kind": kind,
            "normalized_command": normalized,
        }, http_status


if __name__ == "__main__":
    app.run(
        host=os.environ.get("JOCKY_HOST", "127.0.0.1"),
        port=int(os.environ.get("JOCKY_PORT", "5000")),
        debug=True,
    )
