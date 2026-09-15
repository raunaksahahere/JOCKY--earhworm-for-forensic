"""The shipped .x example programs.

An example that does not compile is worse than no example: it is documentation
that lies. Every program under `examples/` is compiled here, planned for both
platforms, and checked against the same rules a program typed into the client
would face.
"""
from pathlib import Path

import pytest

from compiler.investigation import compile_program, deserialize, describe, serialize
from compiler.plan import READY, build_plan, describe_plan

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.x"))

#: Named so a missing file is a failure rather than an empty parametrization.
EXPECTED = {"basic.x", "filtering.x", "correlation.x", "multihost.x", "conditional.x"}


def test_every_expected_example_is_present():
    assert {path.name for path in EXAMPLES} >= EXPECTED


def test_examples_use_the_x_extension():
    directory = Path(__file__).resolve().parent.parent / "examples"
    assert not list(directory.glob("*.jky")), ".jky is superseded by .x"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_an_example_compiles_and_round_trips(path):
    ir = compile_program(path.read_text(encoding="utf-8"))
    assert ir["case"]["id"], "every example names its case"
    assert ir["collections"], "every example collects something"
    assert deserialize(serialize(ir)) == ir
    assert describe(ir)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
@pytest.mark.parametrize("platform_name", ["linux", "windows"])
def test_an_example_plans_on_both_platforms(path, platform_name):
    """A plan is built per platform, and may name no code JOCKY does not expose."""
    ir = compile_program(path.read_text(encoding="utf-8"))
    targets = {target["platform"] for target in ir["targets"]}
    if targets - {"any", platform_name}:
        pytest.skip(f"{path.name} is pinned to {', '.join(sorted(targets))}")
    plan = build_plan(ir, platform_name=platform_name)
    assert describe_plan(plan)
    for task in plan["tasks"]:
        assert "command" not in task
        if task["status"] != READY:
            assert task["detail"], "a skipped source must say why"


def test_the_conditional_example_plans_differently_per_platform():
    """The claim the example exists to make: one program, two plans."""
    ir = compile_program((Path(__file__).resolve().parent.parent
                          / "examples" / "conditional.x").read_text(encoding="utf-8"))
    linux = build_plan(ir, platform_name="linux")
    windows = build_plan(ir, platform_name="windows")

    linux_ready = {task["source"] for task in linux["tasks"] if task["status"] == READY}
    windows_ready = {task["source"] for task in windows["tasks"] if task["status"] == READY}
    assert {"USB", "DRIVERS"} <= linux_ready
    assert not ({"USB", "DRIVERS"} & windows_ready)

    # The Linux-only work is skipped on Windows *by the guard*, and says so.
    guarded = {skip["source"]: skip["detail"] for skip in windows["conditional_skips"]}
    assert {"USB", "DRIVERS"} <= set(guarded)
    assert all("PLATFORM IS linux" in guarded[source] for source in ("USB", "DRIVERS"))
    # The SOURCE ... IS SUPPORTED guards are skipped for their own reason, and
    # each says which guard excluded it rather than sharing one vague message.
    assert "SOURCE BROWSER IS SUPPORTED" in guarded["BROWSER"]

    # The guarded correlation and filter go with it.
    assert len(linux["correlations"]) == len(windows["correlations"]) + 1
    assert len(linux["filters"]) == len(windows["filters"]) + 1


def test_the_multihost_example_names_several_targets():
    ir = compile_program((Path(__file__).resolve().parent.parent
                          / "examples" / "multihost.x").read_text(encoding="utf-8"))
    assert len(ir["targets"]) == 3
    # The playbook ran once per program, not once per target: targets are the
    # dispatch dimension, not a loop in the language.
    assert [collection["source"] for collection in ir["collections"]] == [
        "SYSTEM", "PROCESSES", "EXECUTION", "NETWORK"]
    assert ir["playbooks"] == ["host_triage"]


def test_the_filtering_example_builds_a_compound_predicate():
    ir = compile_program((Path(__file__).resolve().parent.parent
                          / "examples" / "filtering.x").read_text(encoding="utf-8"))
    first, second = ir["filters"][0]["predicate"], ir["filters"][1]["predicate"]
    assert first["type"] == "and"
    assert first["operands"][0]["operator"] == "ONEOF"
    assert first["operands"][0]["value"] == ["/usr/bin/curl", "/usr/bin/wget", "/usr/bin/scp"]
    assert second["type"] == "and"
    assert second["operands"][0]["type"] == "or"


def test_the_client_copy_of_the_examples_is_not_stale():
    """The editor ships the examples; they must be the ones in the repository.

    Two copies of the same program text is a drift hazard, so one is generated
    from the other and this fails if they have come apart.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from generate_language_examples import TARGET, render

    assert TARGET.read_text(encoding="utf-8") == render(), (
        "flutter_client example programs are stale; "
        "run scripts/generate_language_examples.py")


def test_every_example_the_client_offers_actually_compiles():
    """An example the editor can load must be one the compiler accepts."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from generate_language_examples import ORDER

    directory = Path(__file__).resolve().parent.parent / "examples"
    for name in ORDER:
        compile_program((directory / f"{name}.x").read_text(encoding="utf-8"))
