"""Evaluating FILTER predicates against records.

A predicate selects; it never reduces evidence. These tests pin the matching
semantics, because a filter that quietly matches nothing is indistinguishable
from an investigation that found nothing.
"""
import pytest

from compiler.investigation import ProgramError, compile_program
from compiler.predicate import evaluate, explain, select

CURL = {"executable": "/usr/bin/curl", "full_command_line": "curl -s http://example.test/a.sh",
        "user": "analyst", "process_name": "curl"}
APT = {"executable": "/usr/bin/apt", "full_command_line": "apt install nginx", "user": "root",
       "process_name": "apt"}


def _filters(program):
    return compile_program('CASE "c"\nCOLLECT PROCESSES\n' + program + "\n")["filters"]


def _predicate(program):
    return _filters(program)[0]["predicate"]


@pytest.mark.parametrize("program, expected", [
    ('FILTER COMMAND CONTAINS "curl"', True),
    ('FILTER COMMAND CONTAINS "CURL"', True),
    ('FILTER COMMAND CONTAINS "nginx"', False),
    ('FILTER PATH EQUALS "/usr/bin/curl"', True),
    ('FILTER PATH EQUALS "/usr/bin"', False),
    ('FILTER PATH STARTS "/usr"', True),
    ('FILTER PATH ENDS "curl"', True),
    ('FILTER PATH ENDS "wget"', False),
    ('FILTER COMMAND MATCHES "http://[a-z.]+/"', True),
    ('FILTER COMMAND MATCHES "^apt"', False),
    ('FILTER PATH ONEOF ["/usr/bin/curl", "/usr/bin/wget"]', True),
    ('FILTER PATH ONEOF ["/usr/bin/apt"]', False),
    ('FILTER USER EQUALS "analyst"', True),
    ('FILTER PROCESS EQUALS "curl"', True),
])
def test_one_comparison_against_one_record(program, expected):
    assert evaluate(_predicate(program), CURL) is expected


def test_and_requires_both_sides():
    predicate = _predicate('FILTER COMMAND CONTAINS "curl" AND USER EQUALS "analyst"')
    assert evaluate(predicate, CURL) is True
    assert evaluate(predicate, APT) is False


def test_or_requires_either_side():
    predicate = _predicate('FILTER USER EQUALS "root" OR USER EQUALS "analyst"')
    assert evaluate(predicate, CURL) is True
    assert evaluate(predicate, APT) is True


def test_not_inverts():
    predicate = _predicate('FILTER NOT USER EQUALS "root"')
    assert evaluate(predicate, CURL) is True
    assert evaluate(predicate, APT) is False


def test_the_compound_question_a_filter_exists_to_ask():
    """"A download tool, not run by root."""
    predicate = _predicate(
        'FILTER PATH ONEOF ["/usr/bin/curl", "/usr/bin/wget"] AND NOT USER EQUALS "root"')
    assert evaluate(predicate, CURL) is True
    assert evaluate(predicate, APT) is False
    assert evaluate(predicate, {**CURL, "user": "root"}) is False


def test_precedence_is_respected_when_evaluated():
    predicate = _predicate('FILTER USER EQUALS "root" OR USER EQUALS "x" AND PATH ENDS "zzz"')
    # root OR (x AND zzz) -> APT is root, so true regardless of the second arm.
    assert evaluate(predicate, APT) is True


def test_a_field_the_record_does_not_carry_simply_does_not_match():
    """A URL predicate must not reject every process record with an exception."""
    assert evaluate(_predicate('FILTER URL CONTAINS "example"'), CURL) is False
    assert evaluate(_predicate('FILTER NOT URL CONTAINS "example"'), CURL) is True


def test_a_list_valued_record_field_matches_any_member():
    record = {"sources": ["BROWSER", "EXECUTION"]}
    assert evaluate(_predicate('FILTER SOURCE EQUALS "browser"'), record) is True


def test_a_group_matches_on_its_nested_records():
    """An activity group carries its user on the records underneath it."""
    group = {"full_command_line": "curl -s http://example.test",
             "records": [{"user": "analyst", "reference": "E-1"}]}
    assert evaluate(_predicate('FILTER USER EQUALS "analyst"'), group) is True


def test_select_narrows_across_several_filters():
    filters = _filters('FILTER COMMAND CONTAINS "curl"\nFILTER NOT USER EQUALS "root"')
    assert select(filters, [CURL, APT, {**CURL, "user": "root"}]) == [CURL]


def test_select_with_no_filters_keeps_everything():
    assert select([], [CURL, APT]) == [CURL, APT]


def test_explain_renders_one_line_per_filter():
    filters = _filters('FILTER COMMAND CONTAINS "curl"\nFILTER NOT USER EQUALS "root"')
    assert explain(filters) == ["COMMAND CONTAINS curl", "NOT USER EQUALS root"]


def test_an_unknown_field_is_refused_rather_than_silently_false():
    with pytest.raises(ProgramError):
        evaluate({"type": "comparison", "field": "NOPE", "operator": "EQUALS", "value": "x"}, CURL)


def test_an_unknown_operator_is_refused():
    with pytest.raises(ProgramError):
        evaluate({"type": "comparison", "field": "USER", "operator": "NOPE", "value": "x"}, CURL)


def test_evaluation_never_mutates_the_record():
    before = dict(CURL)
    evaluate(_predicate('FILTER COMMAND CONTAINS "curl"'), CURL)
    assert CURL == before
