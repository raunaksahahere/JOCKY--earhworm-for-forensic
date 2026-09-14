"""The investigation language: parse, validate, compile, plan.

The properties that matter here are that an invalid program is refused with a
reason, that the IR round-trips, and that a plan can never name code JOCKY did
not choose to expose.
"""
import json

import pytest

from compiler.investigation import (
    IR_VERSION, ProgramError, compile_program, deserialize, describe, parse, serialize, validate,
    validate_ir,
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
