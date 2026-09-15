"""
The JOCKY investigation language: source to validated, versioned IR.

A program states investigation *intent* — which case, which endpoints, what to
collect, under what conditions, how to correlate it, what to report. It has no
way to express an arbitrary command or a path to execute, so there is nothing
here for a platform adapter to turn into a shell. Every program compiles to a
bounded, read-only collection plan.

    source -> AST -> semantic validation -> IR -> platform execution plan

The IR is deliberately platform-neutral. Deciding *how* to collect processes on
a given operating system belongs to the adapter in `compiler/plan.py`, not to
the parser and not to the language.

Every node is read out of the parse tree by its *type*, never by its position.
The grammar names its keywords as terminals so none of them can be swallowed by
NAME, which means the keyword tokens stay in the tree; indexing past them by
hand is how a grammar change silently turns `CASE "x"` into a case called
"CASE". Walking by type costs nothing and cannot drift when the grammar does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lark import Lark, Token, Tree, UnexpectedInput

#: Bumped when the IR's meaning changes, so a stored investigation can always be
#: read back by the version of JOCKY that produced it.
#:
#: 2 added playbooks (DEFINE/RUN), conditional composition (WHEN), boolean
#: filter predicates, list values and named reports. Filters and reports changed
#: shape, so a version-1 IR cannot be read as a version-2 one.
IR_VERSION = 2

BASE_DIR = Path(__file__).resolve().parent
_parser = Lark((BASE_DIR / "investigation.lark").read_text(encoding="utf-8"), start="program",
               propagate_positions=True)

COLLECTION_SOURCES = {
    "SYSTEM", "PROCESSES", "EXECUTION", "NETWORK", "BROWSER", "USB", "DRIVERS",
    "FILES", "MEMORY", "SERVICES", "LOGS",
}
#: Sources that need at least one argument to mean anything.
REQUIRES_ARGUMENT = {"FILES": "one or more absolute paths", "MEMORY": "FROM <image path>"}
#: Operators whose right-hand side is a set rather than a single value.
LIST_OPERATORS = {"ONEOF"}
MAX_TARGETS = 64
MAX_COLLECTIONS = 32
MAX_FILTERS = 32
MAX_WINDOW_HOURS = 24 * 90
MAX_PLAYBOOK_DEPTH = 8

#: Parse-tree nodes that stand for one value.
VALUE_NODES = {"string_value", "number_value", "variable_value", "name_value", "list_value"}


class ProgramError(ValueError):
    """A program that cannot be parsed or cannot mean anything."""

    def __init__(self, message, line=None, column=None):
        super().__init__(message)
        self.line, self.column = line, column


# --- reading the parse tree ------------------------------------------------
# Small helpers so no statement handler ever counts children.

def _token(node, *types):
    """The first token of one of `types` among a node's children, or None."""
    for child in node.children:
        if isinstance(child, Token) and child.type in types:
            return child
    return None


def _tokens(node, *types):
    return [child for child in node.children
            if isinstance(child, Token) and child.type in types]


def _tree(node, *names):
    for child in node.children:
        if isinstance(child, Tree) and child.data in names:
            return child
    return None


def _trees(node, *names):
    return [child for child in node.children
            if isinstance(child, Tree) and child.data in names]


def _value_trees(node):
    return [child for child in node.children
            if isinstance(child, Tree) and child.data in VALUE_NODES]


def _text(token):
    value = str(token)
    return value[1:-1] if value.startswith('"') else value


def _value(node, variables):
    """Resolve one value node, substituting a LET binding when referenced."""
    if not isinstance(node, Tree):
        return _text(node)
    kind, token = node.data, node.children[0] if node.children else None
    if kind == "string_value":
        return _text(token)
    if kind == "number_value":
        return int(token)
    if kind == "variable_value":
        name = str(token)[1:]
        if name not in variables:
            raise ProgramError(f"Undefined variable ${name}", token.line, token.column)
        value = variables[name]
        return list(value) if isinstance(value, list) else value
    if kind == "list_value":
        return [_value(item, variables) for item in _value_trees(node)]
    return str(token)


# --- predicates ------------------------------------------------------------
# A filter is a boolean expression. It is lowered into a normalized tree of
# plain dictionaries so it survives JSON round-tripping and so anything reading
# the IR can walk it without importing lark.

def _predicate(node, variables):
    if not isinstance(node, Tree):
        raise ProgramError("A FILTER needs a comparison")
    if node.data == "or_expr":
        return {"type": "or",
                "operands": [_predicate(child, variables) for child in _trees(
                    node, "or_expr", "and_expr", "negation", "comparison")]}
    if node.data == "and_expr":
        return {"type": "and",
                "operands": [_predicate(child, variables) for child in _trees(
                    node, "or_expr", "and_expr", "negation", "comparison")]}
    if node.data == "negation":
        operands = _trees(node, "or_expr", "and_expr", "negation", "comparison")
        return {"type": "not", "operand": _predicate(operands[0], variables)}
    if node.data == "comparison":
        field = _token(node, "FIELD", "SOURCE_KW")
        operator = _token(node, "OPERATOR")
        value_node = _value_trees(node)
        return {"type": "comparison", "field": str(field).upper(),
                "operator": str(operator).upper(),
                "value": _value(value_node[0], variables)}
    raise ProgramError(f"Unsupported predicate '{node.data}'")


def walk_predicate(predicate):
    """Every comparison in a predicate, in source order."""
    kind = predicate.get("type")
    if kind == "comparison":
        yield predicate
    elif kind == "not":
        yield from walk_predicate(predicate["operand"])
    else:
        for operand in predicate.get("operands", []):
            yield from walk_predicate(operand)


def describe_predicate(predicate):
    """Round-trippable text for a predicate, for reports and for `describe`."""
    kind = predicate["type"]
    if kind == "comparison":
        value = predicate["value"]
        rendered = ("[" + ", ".join(str(item) for item in value) + "]"
                    if isinstance(value, list) else str(value))
        return f"{predicate['field']} {predicate['operator']} {rendered}"
    if kind == "not":
        return f"NOT {describe_predicate(predicate['operand'])}"
    joiner = " AND " if kind == "and" else " OR "
    return "(" + joiner.join(describe_predicate(operand)
                             for operand in predicate["operands"]) + ")"


# --- conditions ------------------------------------------------------------
# A WHEN guard is never resolved here. It is carried into the IR so the IR stays
# platform-neutral, and `compiler/plan.py` resolves it when it builds a plan for
# one platform. That is what lets one program produce a different plan per
# platform while still saying, in each plan, what it left out and why.

def _condition(guard):
    if guard.data == "platform_guard":
        return {"kind": "platform_is", "platform": str(_token(guard, "PLATFORM")).lower()}
    if guard.data == "source_guard":
        return {"kind": "source_supported", "source": str(_token(guard, "SOURCE")).upper()}
    raise ProgramError(f"Unsupported condition '{guard.data}'")


def describe_condition(condition):
    if condition["kind"] == "platform_is":
        return f"PLATFORM IS {condition['platform']}"
    return f"SOURCE {condition['source']} IS SUPPORTED"


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

    ast = {"case": None, "targets": [], "window": None, "variables": {}, "definitions": {},
           "collections": [], "filters": [], "correlations": [], "timeline": None,
           "reports": []}
    _statements(tree.children, ast, conditions=(), stack=())
    return ast


def _statements(nodes, ast, *, conditions, stack):
    """Read a run of statements, carrying any enclosing WHEN conditions.

    `conditions` accumulates down through nested WHEN blocks and `stack` records
    the playbooks currently being expanded, so a playbook that runs itself is a
    named error rather than a hang.
    """
    variables = ast["variables"]
    for statement in nodes:
        kind = statement.data

        if kind == "case_stmt":
            if conditions:
                raise ProgramError("CASE cannot appear inside a WHEN or DEFINE block")
            fields = {}
            block = _tree(statement, "case_block")
            if block is not None:
                for field in _trees(block, "case_field"):
                    key = _token(field, "CASE_KEY")
                    fields[str(key).lower()] = _text(_token(field, "STRING"))
            ast["case"] = {"id": _text(_token(statement, "STRING")), **fields}

        elif kind == "target_stmt":
            clause = _tree(statement, "platform_clause")
            platform = str(_token(clause, "PLATFORM")).lower() if clause is not None else "any"
            ast["targets"].append({"name": _text(_token(statement, "STRING")),
                                   "platform": platform})

        elif kind == "window_stmt":
            amount = int(_token(statement, "NUMBER"))
            unit = str(_token(statement, "UNIT")).upper()
            ast["window"] = {"hours": amount * (24 if unit == "DAYS" else 1),
                             "requested": f"{amount} {unit}"}

        elif kind == "let_stmt":
            name = _token(statement, "NAME")
            variables[str(name)] = _value(_value_trees(statement)[0], variables)

        elif kind == "define_stmt":
            name = str(_token(statement, "NAME"))
            if name in ast["definitions"]:
                raise ProgramError(f"Playbook '{name}' is defined more than once")
            ast["definitions"][name] = _tree(statement, "playbook_block").children

        elif kind == "run_stmt":
            token = _token(statement, "NAME")
            name = str(token)
            if name not in ast["definitions"]:
                raise ProgramError(
                    f"RUN names playbook '{name}', which this program does not DEFINE. "
                    "A playbook must be defined before it is run.", token.line, token.column)
            if name in stack:
                raise ProgramError(
                    f"Playbook '{name}' runs itself, directly or through "
                    f"{' -> '.join(stack)}", token.line, token.column)
            if len(stack) >= MAX_PLAYBOOK_DEPTH:
                raise ProgramError(
                    f"Playbooks are nested more than {MAX_PLAYBOOK_DEPTH} deep")
            _statements(ast["definitions"][name], ast,
                        conditions=conditions, stack=stack + (name,))

        elif kind == "when_stmt":
            guard = _tree(statement, "platform_guard", "source_guard")
            block = _tree(statement, "playbook_block")
            _statements(block.children, ast,
                        conditions=conditions + (_condition(guard),), stack=stack)

        elif kind == "collect_stmt":
            arguments, options = [], {}
            for argument in _trees(statement, "collect_arg"):
                arguments.append(_value(_value_trees(argument)[0], variables))
            for option in _trees(statement, "collect_option"):
                key = _token(option, "OPTION_KEY", "LIMIT_KW")
                options[str(key).upper()] = _value(_value_trees(option)[0], variables)
            ast["collections"].append({
                "source": str(_token(statement, "SOURCE")).upper(),
                "arguments": arguments, "options": options,
                "conditions": list(conditions)})

        elif kind == "filter_stmt":
            predicate_node = _tree(statement, "or_expr", "and_expr", "negation", "comparison")
            ast["filters"].append({"predicate": _predicate(predicate_node, variables),
                                   "conditions": list(conditions)})

        elif kind == "correlate_stmt":
            left, right = _tokens(statement, "SUBJECT")
            ast["correlations"].append({"left": str(left).upper(), "right": str(right).upper(),
                                        "conditions": list(conditions)})

        elif kind == "timeline_stmt":
            limit = None
            for option in _trees(statement, "timeline_option"):
                limit = int(_token(option, "NUMBER"))
            ast["timeline"] = {"kind": str(_token(statement, "TIMELINE_KIND")).upper(),
                               "limit": limit}

        elif kind == "report_stmt":
            named = _tree(statement, "output_name")
            ast["reports"].append({
                "kind": str(_token(statement, "REPORT_KIND")).upper(),
                "name": _text(_token(named, "STRING")) if named is not None else None})


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
        # Two collections of the same source are only a duplicate when they are
        # reached under the same conditions. The same COLLECT under two
        # different platform guards is how one program serves two platforms.
        signature = (source, tuple(str(argument) for argument in collection["arguments"]),
                     _condition_key(collection["conditions"]))
        if signature in seen:
            raise ProgramError(
                f"COLLECT {source} is requested more than once with the same arguments")
        seen.add(signature)
        if source in REQUIRES_ARGUMENT and not (collection["arguments"] or collection["options"]):
            raise ProgramError(f"COLLECT {source} requires {REQUIRES_ARGUMENT[source]}")
        if source == "FILES":
            for argument in collection["arguments"]:
                for path in (argument if isinstance(argument, list) else [argument]):
                    if not str(path).startswith(("/", "~")) and ":" not in str(path):
                        raise ProgramError(
                            f"COLLECT FILES takes absolute paths; '{path}' is relative")
        limit = collection["options"].get("LIMIT")
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise ProgramError(f"LIMIT for COLLECT {source} must be a positive number")

    requested = {collection["source"] for collection in ast["collections"]}
    for correlation in ast["correlations"]:
        for side in (correlation["left"], correlation["right"]):
            needed = {"ARTIFACTS": "FILES", "EXECUTION": "EXECUTION", "BROWSER": "BROWSER",
                      "USB": "USB", "NETWORK": "NETWORK", "MEMORY": "MEMORY",
                      "DRIVERS": "DRIVERS", "PROCESSES": "PROCESSES"}[side]
            if needed not in requested:
                raise ProgramError(
                    f"CORRELATE {correlation['left']} WITH {correlation['right']} needs "
                    f"COLLECT {needed}, which this program does not request")
        if correlation["left"] == correlation["right"]:
            raise ProgramError("CORRELATE needs two different subjects")

    for filter_clause in ast["filters"]:
        for comparison in walk_predicate(filter_clause["predicate"]):
            _validate_comparison(comparison)
    return ast


def _validate_comparison(comparison):
    operator, value = comparison["operator"], comparison["value"]
    if operator in LIST_OPERATORS:
        if not isinstance(value, list):
            raise ProgramError(
                f"FILTER {comparison['field']} {operator} needs a list of values, "
                f"for example [\"/usr/bin/curl\", \"/usr/bin/wget\"]")
        if not value:
            raise ProgramError(f"FILTER {comparison['field']} {operator} needs a non-empty list")
    elif isinstance(value, list):
        raise ProgramError(
            f"FILTER {comparison['field']} {operator} takes a single value, not a list. "
            f"Use ONEOF to test membership.")
    if operator == "MATCHES":
        try:
            re.compile(str(value))
        except re.error as error:
            raise ProgramError(
                f"FILTER MATCHES pattern is not a valid expression: {error}") from error


def _condition_key(conditions):
    return tuple(sorted(describe_condition(condition) for condition in conditions))


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
            "conditions": list(collection["conditions"]),
        })

    capabilities = sorted({f"collect.{collection['source'].lower()}" for collection in collections})
    return {
        "ir_version": IR_VERSION,
        "case": {"id": case["id"], "title": case.get("title"), "examiner": case.get("examiner"),
                 "reference": case.get("reference"), "notes": case.get("notes")},
        "targets": targets,
        "window_hours": window_hours,
        "collections": collections,
        "filters": [dict(clause) for clause in ast["filters"]],
        "correlations": [dict(correlation) for correlation in ast["correlations"]],
        "timeline": ast.get("timeline") or {"kind": "SIGNIFICANT", "limit": None},
        "reports": ast["reports"] or [{"kind": "SUMMARY", "name": None}],
        "playbooks": sorted(ast["definitions"]),
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
        for condition in collection.get("conditions", []):
            if condition.get("kind") not in ("platform_is", "source_supported"):
                raise ProgramError(f"IR carries unknown condition {condition.get('kind')}")
    for clause in ir.get("filters", []):
        for comparison in walk_predicate(clause["predicate"]):
            _validate_comparison(comparison)
    return ir


def describe(ir: dict) -> str:
    """Human-readable IR, for debugging and for the reproducibility record."""
    lines = [f"JOCKY IR v{ir['ir_version']}",
             f"  case      {ir['case']['id']}  {ir['case'].get('title') or ''}".rstrip(),
             f"  targets   {', '.join(target['name'] for target in ir['targets'])}",
             f"  window    {ir.get('window_hours') or 'default'} hours"]
    if ir.get("playbooks"):
        lines.append(f"  playbooks {', '.join(ir['playbooks'])}")
    for collection in ir["collections"]:
        arguments = " ".join(str(argument) for argument in collection["arguments"])
        options = " ".join(f"{key}={value}" for key, value in sorted(collection["options"].items()))
        lines.append(f"  collect   {collection['id']} {collection['source']} "
                     f"{arguments} {options}".rstrip() + _when(collection))
    for clause in ir["filters"]:
        lines.append(f"  filter    {describe_predicate(clause['predicate'])}" + _when(clause))
    for correlation in ir["correlations"]:
        lines.append(f"  correlate {correlation['left']} with {correlation['right']}"
                     + _when(correlation))
    lines.append(f"  timeline  {ir['timeline']['kind']} limit={ir['timeline'].get('limit')}")
    lines.append(f"  reports   {', '.join(_report_name(report) for report in ir['reports'])}")
    return "\n".join(lines)


def _when(entry):
    conditions = entry.get("conditions") or []
    if not conditions:
        return ""
    return "  [WHEN " + " AND ".join(
        describe_condition(condition) for condition in conditions) + "]"


def _report_name(report):
    return f"{report['kind']} AS \"{report['name']}\"" if report.get("name") else report["kind"]
