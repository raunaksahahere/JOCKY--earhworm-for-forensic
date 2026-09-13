"""
The JOCKY investigation language: source to validated, versioned IR.

A program states investigation *intent* — which case, which endpoints, what to
collect, how to correlate it, what to report. It has no way to express an
arbitrary command or a path to execute, so there is nothing here for a platform
adapter to turn into a shell. Every program compiles to a bounded, read-only
collection plan.

    source -> AST -> semantic validation -> IR -> platform execution plan

The IR is deliberately platform-neutral. Deciding *how* to collect processes on
a given operating system belongs to the adapter in `compiler/plan.py`, not to
the parser and not to the language.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lark import Lark, Token, Tree, UnexpectedInput

#: Bumped when the IR's meaning changes, so a stored investigation can always be
#: read back by the version of JOCKY that produced it.
IR_VERSION = 1

BASE_DIR = Path(__file__).resolve().parent
_parser = Lark((BASE_DIR / "investigation.lark").read_text(encoding="utf-8"), start="program",
               propagate_positions=True)

COLLECTION_SOURCES = {
    "SYSTEM", "PROCESSES", "EXECUTION", "NETWORK", "BROWSER", "USB", "DRIVERS",
    "FILES", "MEMORY", "SERVICES", "LOGS",
}
#: Sources that need at least one argument to mean anything.
REQUIRES_ARGUMENT = {"FILES": "one or more absolute paths", "MEMORY": "FROM <image path>"}
MAX_TARGETS = 64
MAX_COLLECTIONS = 32
MAX_FILTERS = 32
MAX_WINDOW_HOURS = 24 * 90


class ProgramError(ValueError):
    """A program that cannot be parsed or cannot mean anything."""

    def __init__(self, message, line=None, column=None):
        super().__init__(message)
        self.line, self.column = line, column


def _text(token):
    value = str(token)
    return value[1:-1] if value.startswith('"') else value


def _value(node, variables):
    """Resolve one argument, substituting a LET binding when referenced."""
    if isinstance(node, Tree):
        kind = node.data
        token = node.children[0]
        if kind == "string_value":
            return _text(token)
        if kind == "number_value":
            return int(token)
        if kind == "variable_value":
            name = str(token)[1:]
            if name not in variables:
                raise ProgramError(f"Undefined variable ${name}", token.line, token.column)
            return variables[name]
        return str(token)
    return _text(node)


def parse(source: str) -> dict:
    """Parse a program into an AST dictionary."""
    if not isinstance(source, str) or not source.strip():
        raise ProgramError("An investigation program cannot be empty")
    try:
        tree = _parser.parse(source if source.endswith("\n") else source + "\n")
    except UnexpectedInput as error:
        raise ProgramError(
            f"Invalid program syntax at line {error.line}, column {error.column}.",
            error.line, error.column) from error

    ast = {"case": None, "targets": [], "window": None, "variables": {}, "collections": [],
           "filters": [], "correlations": [], "timeline": None, "reports": []}
    variables = ast["variables"]

    for statement in tree.children:
        kind = statement.data
        children = statement.children
        if kind == "case_stmt":
            fields = {}
            if len(children) > 1:
                for field in children[1].children:
                    fields[str(field.children[0]).lower()] = _text(field.children[1])
            ast["case"] = {"id": _text(children[0]), **fields}
        elif kind == "target_stmt":
            platform = "any"
            if len(children) > 1:
                platform = str(children[1].children[0]).lower()
            ast["targets"].append({"name": _text(children[0]), "platform": platform})
        elif kind == "window_stmt":
            amount, unit = int(children[0]), str(children[1]).upper()
            ast["window"] = {"hours": amount * (24 if unit == "DAYS" else 1),
                             "requested": f"{amount} {unit}"}
        elif kind == "let_stmt":
            variables[str(children[0])] = _value(children[1], variables)
        elif kind == "collect_stmt":
            source_name = str(children[0]).upper()
            arguments, options = [], {}
            for child in children[1:]:
                if child.data == "collect_arg":
                    arguments.append(_value(child.children[0], variables))
                else:
                    options[str(child.children[0]).upper()] = _value(child.children[1], variables)
            ast["collections"].append({"source": source_name, "arguments": arguments,
                                       "options": options})
        elif kind == "filter_stmt":
            ast["filters"].append({
                "field": str(children[0]).upper(), "operator": str(children[1]).upper(),
                "value": _value(children[2], variables)})
        elif kind == "correlate_stmt":
            ast["correlations"].append({"left": str(children[0]).upper(),
                                        "right": str(children[1]).upper()})
        elif kind == "timeline_stmt":
            limit = None
            for child in children[1:]:
                limit = int(child.children[0])
            ast["timeline"] = {"kind": str(children[0]).upper(), "limit": limit}
        elif kind == "report_stmt":
            ast["reports"].append(str(children[0]).upper())
    return ast


def validate(ast: dict) -> dict:
    """Reject a program that parses but cannot mean anything.

    Every rule here exists because the alternative is a plan that fails halfway
    through a collection, which on a forensic workstation means a half-answered
    investigation rather than a clear error.
    """
    if not ast.get("case"):
        raise ProgramError("A program must open with a CASE statement")
    if not ast["collections"]:
        raise ProgramError("A program must request at least one COLLECT")
    if len(ast["targets"]) > MAX_TARGETS:
        raise ProgramError(f"A program may name at most {MAX_TARGETS} targets")
    if len(ast["collections"]) > MAX_COLLECTIONS:
        raise ProgramError(f"A program may request at most {MAX_COLLECTIONS} collections")
    if len(ast["filters"]) > MAX_FILTERS:
        raise ProgramError(f"A program may declare at most {MAX_FILTERS} filters")

    window = ast.get("window")
    if window and not 0 < window["hours"] <= MAX_WINDOW_HOURS:
        raise ProgramError(f"WINDOW must be between 1 hour and {MAX_WINDOW_HOURS} hours")

    seen = set()
    for collection in ast["collections"]:
        source = collection["source"]
        if source not in COLLECTION_SOURCES:
            raise ProgramError(f"Unknown collection source {source}")
        signature = (source, tuple(str(argument) for argument in collection["arguments"]))
        if signature in seen:
            raise ProgramError(f"COLLECT {source} is requested more than once with the same arguments")
        seen.add(signature)
        if source in REQUIRES_ARGUMENT and not (collection["arguments"] or collection["options"]):
            raise ProgramError(f"COLLECT {source} requires {REQUIRES_ARGUMENT[source]}")
        if source == "FILES":
            for argument in collection["arguments"]:
                if not str(argument).startswith(("/", "~")) and ":" not in str(argument):
                    raise ProgramError(
                        f"COLLECT FILES takes absolute paths; '{argument}' is relative")
        limit = collection["options"].get("LIMIT")
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise ProgramError(f"LIMIT for COLLECT {source} must be a positive number")

    requested = {collection["source"] for collection in ast["collections"]}
    for correlation in ast["correlations"]:
        for side in (correlation["left"], correlation["right"]):
            needed = {"ARTIFACTS": "FILES", "EXECUTION": "EXECUTION", "BROWSER": "BROWSER",
                      "USB": "USB", "NETWORK": "NETWORK", "MEMORY": "MEMORY",
                      "DRIVERS": "DRIVERS"}[side]
            if needed not in requested and not (side == "ARTIFACTS" and "FILES" in requested):
                raise ProgramError(
                    f"CORRELATE {correlation['left']} WITH {correlation['right']} needs "
                    f"COLLECT {needed}, which this program does not request")
        if correlation["left"] == correlation["right"]:
            raise ProgramError("CORRELATE needs two different subjects")

    for filter_clause in ast["filters"]:
        if filter_clause["operator"] == "MATCHES":
            try:
                re.compile(str(filter_clause["value"]))
            except re.error as error:
                raise ProgramError(f"FILTER MATCHES pattern is not a valid expression: {error}") from error
    return ast


def to_ir(ast: dict) -> dict:
    """Lower a validated AST into the platform-neutral IR.

    The IR names *what* the investigation needs, never how any operating system
    provides it. That separation is what lets one program produce a Linux plan
    today and a Windows plan later without the program changing.
    """
    case = ast["case"]
    targets = ast["targets"] or [{"name": "localhost", "platform": "any"}]
    window_hours = (ast.get("window") or {}).get("hours")

    collections = []
    for index, collection in enumerate(ast["collections"], start=1):
        collections.append({
            "id": f"COL-{index:03d}",
            "source": collection["source"],
            "arguments": list(collection["arguments"]),
            "options": dict(collection["options"]),
        })

    capabilities = sorted({f"collect.{collection['source'].lower()}" for collection in collections})
    return {
        "ir_version": IR_VERSION,
        "case": {"id": case["id"], "title": case.get("title"), "examiner": case.get("examiner"),
                 "reference": case.get("reference"), "notes": case.get("notes")},
        "targets": targets,
        "window_hours": window_hours,
        "collections": collections,
        "filters": list(ast["filters"]),
        "correlations": list(ast["correlations"]),
        "timeline": ast.get("timeline") or {"kind": "SIGNIFICANT", "limit": None},
        "reports": ast["reports"] or ["SUMMARY"],
        "required_capabilities": capabilities,
        "platform_constraints": sorted({target["platform"] for target in targets}),
    }


def compile_program(source: str) -> dict:
    """Source to validated IR, in one call."""
    return to_ir(validate(parse(source)))


def serialize(ir: dict) -> str:
    """Stable text for storage and comparison: the same program always emits the same bytes."""
    return json.dumps(ir, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)


def deserialize(payload: str) -> dict:
    ir = json.loads(payload)
    validate_ir(ir)
    return ir


def validate_ir(ir: dict) -> dict:
    """Check a deserialized IR before anything is allowed to act on it."""
    if not isinstance(ir, dict):
        raise ProgramError("IR must be an object")
    version = ir.get("ir_version")
    if version != IR_VERSION:
        raise ProgramError(
            f"IR version {version} cannot be read by this build, which speaks version {IR_VERSION}")
    for key in ("case", "targets", "collections", "reports"):
        if key not in ir:
            raise ProgramError(f"IR is missing '{key}'")
    if not ir["collections"]:
        raise ProgramError("IR requests no collection")
    for collection in ir["collections"]:
        if collection.get("source") not in COLLECTION_SOURCES:
            raise ProgramError(f"IR requests unknown source {collection.get('source')}")
    return ir


def describe(ir: dict) -> str:
    """Human-readable IR, for debugging and for the reproducibility record."""
    lines = [f"JOCKY IR v{ir['ir_version']}",
             f"  case      {ir['case']['id']}  {ir['case'].get('title') or ''}".rstrip(),
             f"  targets   {', '.join(target['name'] for target in ir['targets'])}",
             f"  window    {ir.get('window_hours') or 'default'} hours"]
    for collection in ir["collections"]:
        arguments = " ".join(str(argument) for argument in collection["arguments"])
        options = " ".join(f"{key}={value}" for key, value in sorted(collection["options"].items()))
        lines.append(f"  collect   {collection['id']} {collection['source']} "
                     f"{arguments} {options}".rstrip())
    for filter_clause in ir["filters"]:
        lines.append(f"  filter    {filter_clause['field']} {filter_clause['operator']} "
                     f"{filter_clause['value']}")
    for correlation in ir["correlations"]:
        lines.append(f"  correlate {correlation['left']} with {correlation['right']}")
    lines.append(f"  timeline  {ir['timeline']['kind']} limit={ir['timeline'].get('limit')}")
    lines.append(f"  reports   {', '.join(ir['reports'])}")
    return "\n".join(lines)
