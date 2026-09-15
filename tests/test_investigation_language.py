"""The investigation language: parse, validate, compile, plan.

The properties that matter here are that an invalid program is refused with a
reason, that the IR round-trips, and that a plan can never name code JOCKY did
not choose to expose.
"""
import json

import pytest

from compiler.investigation import (
    IR_VERSION, ProgramError, compile_program, deserialize, describe, describe_predicate, parse,
    serialize, validate, validate_ir,
)
from compiler.plan import PLAN_VERSION, READY, UNSUPPORTED, adapter_for, build_plan, describe_plan

MINIMAL = 'CASE "c"\nTARGET "host"\nCOLLECT PROCESSES\nREPORT SUMMARY\n'

FULL = '''CASE "Suspected staging"
TARGET "workstation-1" PLATFORM linux
WINDOW LAST 48 HOURS
LET threshold = 5
COLLECT PROCESSES
COLLECT EXECUTION
COLLECT NETWORK
COLLECT USB
COLLECT BROWSER
COLLECT FILES "/etc/passwd"
COLLECT MEMORY FROM "/evidence/image.raw"
FILTER COMMAND CONTAINS "curl"
CORRELATE EXECUTION WITH USB
TIMELINE FULL
REPORT SUMMARY
'''


def test_a_program_parses_every_statement():
    ast = parse(FULL)
    assert ast["case"]["id"] == "Suspected staging"
    assert [target["name"] for target in ast["targets"]] == ["workstation-1"]
    assert len(ast["collections"]) == 7
    assert len(ast["filters"]) == 1
    assert len(ast["correlations"]) == 1


def test_statements_do_not_swallow_the_keyword_that_follows():
    """A NAME must not absorb the next statement's keyword.

    This was a real defect: with whitespace ignored globally, eighteen
    statements parsed as five because each name ate the following keyword.
    """
    ast = parse(FULL)
    sources = [collection["source"] for collection in ast["collections"]]
    assert sources == ["PROCESSES", "EXECUTION", "NETWORK", "USB", "BROWSER", "FILES", "MEMORY"]


@pytest.mark.parametrize("program, expected", [
    ("COLLECT PROCESSES\n", "CASE"),
    ('CASE "c"\nTARGET "h"\nREPORT SUMMARY\n', "COLLECT"),
    ('CASE "c"\nCOLLECT PROCESSES\nCOLLECT PROCESSES\n', "more than once"),
    ('CASE "c"\nCOLLECT FILES "relative/path"\n', "absolute"),
    ('CASE "c"\nCOLLECT PROCESSES\nCORRELATE EXECUTION WITH USB\n', "does not request"),
    ('CASE "c"\nCOLLECT PROCESSES\nFILTER COMMAND MATCHES "["\n', "not a valid expression"),
    ('CASE "c"\nCOLLECT MEMORY\n', "FROM"),
    ('CASE "c"\nWINDOW LAST 9000 DAYS\nCOLLECT PROCESSES\n', "window"),
])
def test_an_invalid_program_is_refused_with_a_reason(program, expected):
    with pytest.raises(ProgramError) as error:
        compile_program(program)
    assert expected.lower() in str(error.value).lower()


def test_an_empty_program_is_refused():
    with pytest.raises(ProgramError):
        compile_program("   \n\n  ")


def test_ir_round_trips_unchanged():
    ir = compile_program(FULL)
    assert deserialize(serialize(ir)) == ir
    assert ir["ir_version"] == IR_VERSION
    validate_ir(ir)


def test_ir_is_json_serializable():
    json.dumps(compile_program(FULL))


def test_describe_names_every_collection():
    text = describe(compile_program(FULL))
    for source in ("PROCESSES", "EXECUTION", "NETWORK", "USB", "BROWSER", "MEMORY"):
        assert source in text


def test_the_same_ir_builds_a_plan_for_each_platform():
    ir = compile_program(MINIMAL)
    linux, windows = build_plan(ir, platform_name="linux"), build_plan(ir, platform_name="windows")
    assert linux["platform"] == "linux" and linux["platform_validated"] is True
    assert windows["platform"] == "windows"
    assert windows["platform_validated"] is False, (
        "Windows has never been run against a real host; the plan must say so")


def test_an_unsupported_source_is_a_named_skip_not_an_error():
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\nCOLLECT USB\nCOLLECT SERVICES\n')
    plan = build_plan(ir, platform_name="windows")
    skipped = {item["source"] for item in plan["unsupported"]}
    assert {"USB", "SERVICES"} <= skipped
    assert plan["ready_task_count"] >= 1
    for item in plan["unsupported"]:
        assert item["detail"], "a skipped source must say why"


def test_a_platform_constraint_is_enforced():
    ir = compile_program('CASE "c"\nTARGET "h" PLATFORM linux\nCOLLECT PROCESSES\n')
    with pytest.raises(ProgramError):
        build_plan(ir, platform_name="windows")


def test_no_plan_task_carries_a_command():
    plan = build_plan(compile_program(FULL), platform_name="linux")
    for task in plan["tasks"]:
        assert "command" not in task
        assert "shell" not in json.dumps(task).lower()
    assert "never carries a command" in plan["note"]


def test_every_collector_a_linux_plan_names_actually_exists():
    """A plan may only name collectors this build implements."""
    import importlib

    for source, (dotted, _capability) in adapter_for("linux").supported.items():
        module_name, _, attribute = dotted.rpartition(".")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attribute)), f"{source} names a missing collector"


def test_plan_description_flags_an_unvalidated_platform():
    text = describe_plan(build_plan(compile_program(MINIMAL), platform_name="windows"))
    assert "NOT VALIDATED" in text


def test_plan_version_is_recorded():
    assert build_plan(compile_program(MINIMAL))["plan_version"] == PLAN_VERSION


def test_bounds_are_enforced():
    many = 'CASE "c"\n' + "".join(f'TARGET "host-{index}"\n' for index in range(200))
    with pytest.raises(ProgramError):
        compile_program(many + "COLLECT PROCESSES\n")


# --- boolean predicates ----------------------------------------------------
# A filter is an expression, not a single comparison. These tests pin the shape
# the predicate lowers to, because everything downstream walks that shape.

def _only_filter(program):
    return compile_program(program)["filters"][0]["predicate"]


def test_a_filter_lowers_to_a_single_comparison():
    predicate = _only_filter('CASE "c"\nCOLLECT PROCESSES\nFILTER COMMAND CONTAINS "curl"\n')
    assert predicate == {"type": "comparison", "field": "COMMAND",
                         "operator": "CONTAINS", "value": "curl"}


def test_and_or_and_not_build_a_tree():
    predicate = _only_filter(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'FILTER COMMAND CONTAINS "curl" AND NOT USER EQUALS "root"\n')
    assert predicate["type"] == "and"
    left, right = predicate["operands"]
    assert left["field"] == "COMMAND"
    assert right == {"type": "not", "operand": {
        "type": "comparison", "field": "USER", "operator": "EQUALS", "value": "root"}}


def test_or_binds_looser_than_and():
    """`a OR b AND c` must mean `a OR (b AND c)`, not `(a OR b) AND c`."""
    predicate = _only_filter(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'FILTER USER EQUALS "a" OR USER EQUALS "b" AND COMMAND CONTAINS "c"\n')
    assert predicate["type"] == "or"
    assert [operand["type"] for operand in predicate["operands"]] == ["comparison", "and"]


def test_parentheses_override_precedence():
    predicate = _only_filter(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'FILTER (USER EQUALS "a" OR USER EQUALS "b") AND COMMAND CONTAINS "c"\n')
    assert predicate["type"] == "and"
    assert predicate["operands"][0]["type"] == "or"


def test_a_predicate_survives_serialization():
    ir = compile_program(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'FILTER (PATH STARTS "/tmp" OR PATH ENDS ".sh") AND NOT USER EQUALS "root"\n')
    assert deserialize(serialize(ir)) == ir


def test_a_predicate_renders_back_to_readable_text():
    ir = compile_program(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'FILTER COMMAND CONTAINS "curl" AND NOT USER EQUALS "root"\n')
    assert describe_predicate(ir["filters"][0]["predicate"]) == (
        '(COMMAND CONTAINS curl AND NOT USER EQUALS root)')


def test_a_bad_regex_is_caught_anywhere_in_the_expression():
    """The old validator only checked a top-level comparison."""
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nCOLLECT PROCESSES\n'
                        'FILTER USER EQUALS "root" AND COMMAND MATCHES "["\n')
    assert "not a valid expression" in str(error.value)


# --- list values and membership --------------------------------------------

def test_a_list_binding_is_substituted_into_a_membership_test():
    ir = compile_program(
        'CASE "c"\nLET tools = ["/usr/bin/curl", "/usr/bin/wget"]\n'
        'COLLECT PROCESSES\nFILTER PATH ONEOF $tools\n')
    assert ir["filters"][0]["predicate"]["value"] == ["/usr/bin/curl", "/usr/bin/wget"]


def test_a_list_may_be_written_inline_and_span_lines():
    ir = compile_program(
        'CASE "c"\nCOLLECT PROCESSES\nFILTER PATH ONEOF [\n  "/a",\n  "/b"\n]\n')
    assert ir["filters"][0]["predicate"]["value"] == ["/a", "/b"]


def test_oneof_without_a_list_is_refused():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nCOLLECT PROCESSES\nFILTER PATH ONEOF "/usr/bin/curl"\n')
    assert "needs a list" in str(error.value)


def test_a_single_value_operator_refuses_a_list():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nCOLLECT PROCESSES\nFILTER PATH EQUALS ["/a", "/b"]\n')
    assert "ONEOF" in str(error.value)


def test_an_undefined_variable_is_refused():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nCOLLECT PROCESSES\nFILTER PATH CONTAINS $missing\n')
    assert "$missing" in str(error.value)


# --- playbooks -------------------------------------------------------------

PLAYBOOK = '''CASE "c"
DEFINE triage {
COLLECT PROCESSES
COLLECT NETWORK
}
RUN triage
'''


def test_a_playbook_expands_into_real_collections():
    """DEFINE/RUN must lower, not merely parse and disappear."""
    ir = compile_program(PLAYBOOK)
    assert [collection["source"] for collection in ir["collections"]] == ["PROCESSES", "NETWORK"]
    assert ir["playbooks"] == ["triage"]


def test_a_playbook_can_be_run_more_than_once_under_different_guards():
    ir = compile_program(
        'CASE "c"\nDEFINE triage {\nCOLLECT PROCESSES\n}\n'
        'WHEN PLATFORM IS linux {\nRUN triage\n}\n'
        'WHEN PLATFORM IS windows {\nRUN triage\n}\n')
    assert len(ir["collections"]) == 2
    assert ir["collections"][0]["conditions"][0]["platform"] == "linux"
    assert ir["collections"][1]["conditions"][0]["platform"] == "windows"


def test_a_playbook_may_run_another_playbook():
    ir = compile_program(
        'CASE "c"\nDEFINE inner {\nCOLLECT NETWORK\n}\n'
        'DEFINE outer {\nCOLLECT PROCESSES\nRUN inner\n}\nRUN outer\n')
    assert [collection["source"] for collection in ir["collections"]] == ["PROCESSES", "NETWORK"]


def test_running_an_undefined_playbook_is_refused():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nCOLLECT PROCESSES\nRUN nothing\n')
    assert "does not DEFINE" in str(error.value)


def test_a_playbook_that_runs_itself_is_refused_rather_than_hanging():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nDEFINE loop {\nCOLLECT PROCESSES\nRUN loop\n}\nRUN loop\n')
    assert "runs itself" in str(error.value)


def test_running_the_same_playbook_from_two_places_is_not_a_cycle():
    """Cycle detection must key on the path currently being expanded, not on
    having seen a name before, or a shared sub-playbook is a false positive."""
    ir = compile_program('CASE "c"\nDEFINE inner {\nCOLLECT PROCESSES\n}\n'
                         'DEFINE outer {\nRUN inner\n}\nRUN outer\n'
                         'WHEN PLATFORM IS linux {\nRUN inner\n}\n')
    assert len(ir["collections"]) == 2


def test_defining_the_same_playbook_twice_is_refused():
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nDEFINE t {\nCOLLECT PROCESSES\n}\n'
                        'DEFINE t {\nCOLLECT NETWORK\n}\nRUN t\n')
    assert "more than once" in str(error.value)


# --- conditional composition ----------------------------------------------

def test_a_platform_guard_is_carried_into_the_ir_not_resolved_at_parse_time():
    """The IR must stay platform-neutral; the guard is the adapter's business."""
    ir = compile_program('CASE "c"\nWHEN PLATFORM IS linux {\nCOLLECT USB\n}\n')
    assert ir["collections"][0]["conditions"] == [{"kind": "platform_is", "platform": "linux"}]


def test_a_guarded_collection_runs_on_the_named_platform():
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\n'
                         'WHEN PLATFORM IS linux {\nCOLLECT USB\n}\n')
    linux = build_plan(ir, platform_name="linux")
    assert {task["source"] for task in linux["tasks"] if task["status"] == READY} == {
        "PROCESSES", "USB"}
    assert linux["conditional_skips"] == []


def test_a_guarded_collection_is_a_named_skip_on_another_platform():
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\n'
                         'WHEN PLATFORM IS linux {\nCOLLECT USB\n}\n')
    windows = build_plan(ir, platform_name="windows")
    skips = windows["conditional_skips"]
    assert [skip["source"] for skip in skips] == ["USB"]
    assert "PLATFORM IS linux" in skips[0]["detail"]
    assert skips[0]["source"] not in {task["source"] for task in windows["tasks"]
                                      if task["status"] == READY}


def test_a_source_support_guard_resolves_per_platform():
    program = ('CASE "c"\nCOLLECT PROCESSES\n'
               'WHEN SOURCE BROWSER IS SUPPORTED {\nCOLLECT BROWSER\n}\n')
    ir = compile_program(program)
    assert build_plan(ir, platform_name="linux")["conditional_skips"] == []
    windows = build_plan(ir, platform_name="windows")
    assert [skip["source"] for skip in windows["conditional_skips"]] == ["BROWSER"]


def test_nested_guards_both_have_to_hold():
    ir = compile_program(
        'CASE "c"\nWHEN PLATFORM IS linux {\n'
        'WHEN SOURCE BROWSER IS SUPPORTED {\nCOLLECT BROWSER\n}\n}\n')
    assert len(ir["collections"][0]["conditions"]) == 2
    assert build_plan(ir, platform_name="linux")["ready_task_count"] == 1


def test_a_guarded_filter_is_dropped_from_a_plan_that_will_not_run_it():
    ir = compile_program(
        'CASE "c"\nCOLLECT PROCESSES\n'
        'WHEN PLATFORM IS linux {\nCOLLECT USB\nFILTER PATH CONTAINS "/media"\n}\n')
    assert len(build_plan(ir, platform_name="linux")["filters"]) == 1
    assert build_plan(ir, platform_name="windows")["filters"] == []


def test_the_same_collect_under_two_guards_is_not_a_duplicate():
    ir = compile_program('CASE "c"\nWHEN PLATFORM IS linux {\nCOLLECT PROCESSES\n}\n'
                         'WHEN PLATFORM IS windows {\nCOLLECT PROCESSES\n}\n')
    assert len(ir["collections"]) == 2


def test_an_unguarded_duplicate_is_still_refused():
    with pytest.raises(ProgramError):
        compile_program('CASE "c"\nCOLLECT PROCESSES\nCOLLECT PROCESSES\n')


def test_a_case_cannot_be_declared_inside_a_block():
    """A block holds investigation steps, not case metadata.

    The grammar refuses this before semantics get a look in, because
    `playbook_statement` does not admit `case_stmt`; the check in `parse` is a
    second line of defence should that ever change.
    """
    with pytest.raises(ProgramError) as error:
        compile_program('CASE "c"\nWHEN PLATFORM IS linux {\nCASE "d"\nCOLLECT PROCESSES\n}\n')
    assert "line 3" in str(error.value)


# --- named reports ---------------------------------------------------------

def test_a_report_can_be_named():
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\nREPORT SUMMARY AS "final-report"\n')
    assert ir["reports"] == [{"kind": "SUMMARY", "name": "final-report"}]


def test_an_unnamed_report_still_compiles():
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\nREPORT BOTH\n')
    assert ir["reports"] == [{"kind": "BOTH", "name": None}]


def test_a_program_with_no_report_defaults_to_summary():
    assert compile_program('CASE "c"\nCOLLECT PROCESSES\n')["reports"] == [
        {"kind": "SUMMARY", "name": None}]


# --- the grammar's keywords stay keywords ----------------------------------

def test_a_field_named_like_a_keyword_still_parses():
    """SOURCE is both a FILTER field and the WHEN guard keyword."""
    ir = compile_program('CASE "c"\nCOLLECT PROCESSES\nFILTER SOURCE EQUALS "browser"\n')
    assert ir["filters"][0]["predicate"]["field"] == "SOURCE"


def test_limit_is_both_a_collect_option_and_a_timeline_option():
    ir = compile_program('CASE "c"\nCOLLECT FILES "/etc/passwd" LIMIT 5\nTIMELINE FULL LIMIT 10\n')
    assert ir["collections"][0]["options"]["LIMIT"] == 5
    assert ir["timeline"]["limit"] == 10


def test_an_old_ir_version_is_refused_rather_than_misread():
    ir = compile_program(MINIMAL)
    ir["ir_version"] = 1
    with pytest.raises(ProgramError) as error:
        validate_ir(ir)
    assert "cannot be read by this build" in str(error.value)
