"""
Evaluating a JOCKY FILTER predicate against a record.

A FILTER states what the investigation is interested in. It deliberately does
*not* reduce the evidence: evidence is registered and hashed complete, and a
program that could delete records before they were written down would be a
forensic tool that loses the thing it was pointed at. So a predicate selects --
it marks which records answer the question the program asked, and the evidence
underneath stays whole and verifiable either way.

The field names are the language's, not any collector's. `COMMAND` means the
command however the record spells it, which is why each field lists several
places to look rather than one key: an activity group and an artifact record
describe the same investigation in different shapes.
"""

from __future__ import annotations

import re

from .investigation import ProgramError

#: Language field -> the places a record may carry it.
#:
#: Every candidate is tried and any match counts. A field that a record simply
#: does not have contributes nothing, so a predicate over browser URLs does not
#: silently reject every process record; it just does not select one.
FIELDS = {
    "PATH": ("path", "executable", "full_path"),
    "COMMAND": ("full_command_line", "normalized_command", "command", "command_line"),
    "USER": ("user", "username", "owner"),
    "HOST": ("host", "hostname", "endpoint"),
    "ENDPOINT": ("endpoint", "endpoint_id"),
    "SOURCE": ("source", "sources", "evidence_kind"),
    "HASH": ("hash", "sha256", "digest"),
    "PROCESS": ("process_name", "name", "executable"),
    "URL": ("url", "target_url", "download_url"),
    "ADDRESS": ("address", "remote_address", "remote_ip", "ip"),
}


def _candidates(record, field):
    """Every string a record offers for one language field."""
    values = []
    for key in FIELDS[field]:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item is not None)
        else:
            values.append(str(value))
    # Activity groups hold their per-record detail one level down; a predicate
    # about a user means the user on any of the records in the group.
    for nested in record.get("records") or ():
        if isinstance(nested, dict):
            values.extend(_candidates(nested, field))
    return values


def _matches(operator, candidate, value):
    subject = candidate.casefold()
    if operator == "CONTAINS":
        return str(value).casefold() in subject
    if operator == "EQUALS":
        return subject == str(value).casefold()
    if operator == "STARTS":
        return subject.startswith(str(value).casefold())
    if operator == "ENDS":
        return subject.endswith(str(value).casefold())
    if operator == "ONEOF":
        return subject in {str(item).casefold() for item in value}
    if operator == "MATCHES":
        return re.search(str(value), candidate) is not None
    raise ProgramError(f"Unknown operator {operator}")


def evaluate(predicate, record) -> bool:
    """Is one record selected by one predicate?"""
    kind = predicate["type"]
    if kind == "and":
        return all(evaluate(operand, record) for operand in predicate["operands"])
    if kind == "or":
        return any(evaluate(operand, record) for operand in predicate["operands"])
    if kind == "not":
        return not evaluate(predicate["operand"], record)
    if kind == "comparison":
        field = predicate["field"]
        if field not in FIELDS:
            raise ProgramError(f"Unknown filter field {field}")
        return any(_matches(predicate["operator"], candidate, predicate["value"])
                   for candidate in _candidates(record, field))
    raise ProgramError(f"Unknown predicate node {kind}")


def select(predicates, records) -> list:
    """Records selected by every predicate in a program.

    Several FILTER statements narrow together, the way consecutive statements
    in a program read: each one is a further condition on the same question.
    """
    chosen = []
    for record in records:
        if all(evaluate(clause["predicate"], record) for clause in predicates):
            chosen.append(record)
    return chosen


def explain(predicates) -> list:
    """One readable line per filter, for a report that has to say what it showed."""
    from .investigation import describe_predicate
    return [describe_predicate(clause["predicate"]) for clause in predicates]
