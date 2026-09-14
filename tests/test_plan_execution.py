"""Plan execution, the endpoint agent, detections and the synthetic scenarios.

The central property: a plan can only cause things the registry already lists.
A program is not a way to run code.
"""
import threading

import pytest

from analysis.detections import DETECTION_RULESET_VERSION, RULES, detect
from backend import plan_runner
from compiler.investigation import compile_program
from compiler.plan import build_plan
from endpoint.agent import Agent, ControlPlaneClient
from scenarios import SCENARIOS, SYNTHETIC_BANNER, build_scenario, run_scenario


def plan_for(program):
    return build_plan(compile_program(program), platform_name="linux")


# --- the registry boundary ----------------------------------------------------
def test_every_registry_entry_names_the_function_it_holds():
    import importlib

    for source, (function, dotted, _action) in plan_runner.REGISTRY.items():
        module_name, _, attribute = dotted.rpartition(".")
        assert getattr(importlib.import_module(module_name), attribute) is function, (
            f"{source} names {dotted} but holds something else")


def test_a_plan_naming_unknown_code_is_refused(caplog):
    """The dotted path is checked against the registry, never imported from it."""
    plan = plan_for('CASE "c"\nCOLLECT NETWORK\n')
    plan["tasks"][0]["collector"] = "os.system"
    assert plan_runner.runnable_tasks(plan) == []


def test_a_source_outside_the_registry_is_ignored():
    plan = plan_for('CASE "c"\nCOLLECT NETWORK\n')
    plan["tasks"][0]["source"] = "ANYTHING"
    assert plan_runner.runnable_tasks(plan) == []


def test_the_local_collector_skips_the_baseline_it_already_owns():
    plan = plan_for('CASE "c"\nCOLLECT PROCESSES\nCOLLECT NETWORK\n')
    local = {entry["task"]["source"] for entry in plan_runner.runnable_tasks(plan)}
    endpoint = {entry["task"]["source"]
                for entry in plan_runner.runnable_tasks(plan, skip_baseline=False)}
    assert local == {"NETWORK"}
    assert endpoint == {"PROCESSES", "NETWORK"}


def test_selectable_sources_exclude_the_baseline():
    assert set(plan_runner.selectable_sources()).isdisjoint(plan_runner.BASELINE)
    assert set(plan_runner.BASELINE) <= set(plan_runner.endpoint_sources())


def test_memory_without_an_image_collects_nothing_and_claims_nothing():
    entry = {"task": {"source": "MEMORY", "arguments": [], "options": {}},
             "function": lambda **kwargs: pytest.fail("the collector must not run"),
             "action": "MEMORY", "source_description": "x"}
    result = plan_runner.call(entry, options={})
    assert result["classification"] == "UNAVAILABLE"
    assert result["source_status"] == "NOT_COLLECTED"


def test_collectors_receive_only_named_arguments():
    """The option dictionary is never handed to a collector wholesale."""
    received = {}

    def collector(**kwargs):
        received.update(kwargs)
        return {"status": "success"}

    entry = {"task": {"source": "BROWSER", "arguments": [], "options": {}},
             "function": collector, "action": "BROWSER", "source_description": "x"}
    plan_runner.call(entry, options={"window_hours": 12, "secret": "must not arrive"})
    assert "secret" not in received
    assert received["window_hours"] == 12


# --- the endpoint agent -------------------------------------------------------
def test_the_agent_refuses_a_source_it_has_no_collector_for():
    agent = Agent(ControlPlaneClient("http://unused"))
    outcome = agent.run_task({"source": "ANYTHING", "arguments": [], "options": {}})
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == "source_unsupported"
    assert "nothing is claimed" in outcome["error"]["message"]


def test_the_agent_refuses_a_task_whose_collector_disagrees_with_its_build():
    agent = Agent(ControlPlaneClient("http://unused"))
    outcome = agent.run_task({"source": "NETWORK", "collector": "os.system",
                              "arguments": [], "options": {}})
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == "collector_mismatch"


def test_the_agent_reports_a_collector_failure_rather_than_swallowing_it(monkeypatch):
    def explode(**_kwargs):
        raise RuntimeError("collector broke")

    monkeypatch.setitem(plan_runner.REGISTRY, "NETWORK",
                        (explode, "analysis.network.collect_network", "NETWORK"))
    agent = Agent(ControlPlaneClient("http://unused"))
    outcome = agent.run_task({"source": "NETWORK", "collector": "analysis.network.collect_network",
                              "arguments": [], "options": {}})
    assert outcome["ok"] is False and "collector broke" in outcome["error"]["message"]


def test_a_task_that_overruns_is_stopped_and_reported(monkeypatch):
    started = threading.Event()

    def hang(cancel=None, **_kwargs):
        started.set()
        cancel.wait(10)
        return {"status": "success"}

    monkeypatch.setattr("endpoint.agent.TASK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setitem(plan_runner.REGISTRY, "NETWORK",
                        (hang, "analysis.network.collect_network", "NETWORK"))
    agent = Agent(ControlPlaneClient("http://unused"))
    outcome = agent.run_task({"source": "NETWORK", "collector": "analysis.network.collect_network",
                              "arguments": [], "options": {}})
    assert started.is_set()
    assert outcome["ok"] is False and outcome["error"]["code"] == "timeout"


def test_the_agent_stores_its_credential_privately(tmp_path):
    identity = tmp_path / "endpoint.json"
    agent = Agent(ControlPlaneClient("http://unused"), identity_path=identity)
    agent.save_identity({"endpoint_id": "EP-1", "endpoint_token": "secret"})
    assert identity.stat().st_mode & 0o077 == 0, "the credential must not be world-readable"
    assert agent.load_identity() is True


# --- detections ---------------------------------------------------------------
def test_a_hash_match_is_reported_more_strongly_than_a_name_match():
    by_hash = detect(drivers={"classification": "CURRENT_OBSERVATION",
                              "reference": {"available": True},
                              "drivers": [{"name": "x.sys", "sha256": "a" * 64, "verification": {
                                  "risk_status": "MATCHED", "confidence": "high"}}]})[0]
    by_name = detect(drivers={"classification": "CURRENT_OBSERVATION",
                              "reference": {"available": True},
                              "drivers": [{"name": "x.sys", "verification": {
                                  "risk_status": "MATCHED", "confidence": "low"}}]})[0]
    assert by_hash["severity"] == "high" and by_name["severity"] == "medium"
    assert by_hash["priority_rank"] < by_name["priority_rank"]


def test_a_driver_finding_never_claims_the_driver_was_abused_here():
    finding = detect(drivers={"classification": "CURRENT_OBSERVATION",
                              "reference": {"available": True},
                              "drivers": [{"name": "x.sys", "sha256": "a" * 64, "verification": {
                                  "risk_status": "MATCHED", "confidence": "high"}}]})[0]
    assert "not that it was abused on this host" in finding["explanation"]


def test_an_unreadable_reference_says_nothing_was_checked():
    finding = detect(drivers={"classification": "CURRENT_OBSERVATION",
                              "reference": {"available": False}, "drivers": []})[0]
    assert finding["classification"] == "UNAVAILABLE"
    assert "nothing was checked" in finding["explanation"]


def test_an_expected_orphan_is_not_reported():
    """A Windows kernel root with no parent is the normal case, not a lead."""
    findings = detect(memory={"provenance": "REAL", "processes": [
        {"pid": 4, "parent_pid": 999, "process_name": "System"}]})
    assert findings == []


def test_a_memory_finding_from_a_fixture_is_labelled():
    findings = detect(memory={"provenance": "FIXTURE", "processes": [
        {"pid": 100, "parent_pid": 999, "process_name": "thing.exe"}]})
    assert any("fixture" in finding["title"].lower() for finding in findings)
    orphan = [f for f in findings if f["category"] == "memory_orphan_process"][0]
    assert orphan["classification"] == "INFERRED", (
        "a fixture-derived finding must not be classified as evidence about a host")


def test_every_detection_names_the_rule_that_fired():
    findings = detect(
        drivers={"classification": "CURRENT_OBSERVATION", "reference": {"available": True},
                 "drivers": [{"name": "x.sys", "sha256": "a" * 64,
                              "verification": {"risk_status": "MATCHED", "confidence": "high"}}]},
        memory={"provenance": "FIXTURE",
                "processes": [{"pid": 100, "parent_pid": 999, "process_name": "thing.exe"}]})
    assert findings
    for finding in findings:
        rules = [ref for ref in finding["evidence_references"] if ref["kind"] == "detection_rule"]
        assert rules, f"{finding['category']} cites no rule"
        assert rules[0]["id"] in RULES
        assert rules[0]["ruleset_version"] == DETECTION_RULESET_VERSION


# --- scenarios ----------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_is_labelled_synthetic(name):
    scenario = build_scenario(name)
    assert scenario["synthetic"] is True
    assert scenario["banner"] == SYNTHETIC_BANNER
    for event in scenario["execution"]["events"]:
        assert event["synthetic"] is True
        assert event["source"].startswith("SYNTHETIC")
    for artifact in scenario["artifacts"]["artifacts"]:
        assert artifact["synthetic"] is True


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_is_deterministic(name):
    first, second = run_scenario(name), run_scenario(name)
    assert [f["title"] for f in first["findings"]] == [f["title"] for f in second["findings"]]
    assert first["event_count"] == second["event_count"]


def test_scenario_a_produces_a_priority_one_lead():
    result = run_scenario("A")
    assert result["highest_lead_priority"] == "Priority 1 — investigate first"


def test_scenario_b_links_the_archive_the_copy_and_the_device():
    result = run_scenario("B")
    media = [f for f in result["findings"] if f["category"] == "removable_media_activity"]
    assert media, "removable media activity was not correlated"
    assert "share a hash" in media[0]["explanation"]
    assert result["threads"], "the related commands should form one thread"


def test_scenario_c_links_a_download_to_its_execution():
    result = run_scenario("C")
    linked = [f for f in result["findings"] if f["category"] == "download_executed"]
    assert linked
    kinds = {ref["kind"] for ref in linked[0]["evidence_references"]}
    assert {"browser_download", "artifact", "execution_event"} <= kinds


def test_scenario_d_correlates_two_hosts_on_a_shared_observable():
    result = run_scenario("D")
    fleet = result["fleet_correlation"]
    assert fleet["endpoint_count"] == 2
    kinds = {match["kind"] for match in fleet["correlations"]}
    assert "file_hash" in kinds and "remote_address" in kinds


def test_scenario_e_normalizes_memory_evidence():
    result = run_scenario("E")
    processes = result["source"]["memory"]["processes"]
    assert processes[0]["process_name"] == "System"
    assert result["source"]["memory"]["provenance"] == "FIXTURE"
    assert any(f["category"] == "memory_orphan_process" for f in result["findings"])


def test_scenario_f_produces_an_explainable_driver_finding():
    result = run_scenario("F")
    finding = [f for f in result["findings"] if f["category"] == "known_abused_driver_present"][0]
    assert finding["severity"] == "high"
    assert finding["recommended_action"]
    assert finding["unknowns"]


def test_an_unknown_scenario_is_refused():
    with pytest.raises(KeyError):
        build_scenario("Z")


# --- boundaries that must not drift ------------------------------------------
def test_no_adapter_offers_a_source_the_registry_cannot_run():
    """A READY task nothing can execute is a promise the build cannot keep."""
    from compiler.plan import LinuxAdapter, WindowsAdapter

    for adapter in (LinuxAdapter, WindowsAdapter):
        for source in adapter.supported:
            assert source in plan_runner.REGISTRY, (
                f"the {adapter.name} adapter offers {source}, which no collector backs")


def test_a_source_this_build_cannot_run_is_named_rather_than_dropped(caplog):
    plan = plan_for('CASE "c"\nCOLLECT PROCESSES\nCOLLECT LOGS\n')
    skipped = {item["source"] for item in plan["unsupported"]}
    assert "LOGS" in skipped
    detail = [item for item in plan["unsupported"] if item["source"] == "LOGS"][0]["detail"]
    assert "EXECUTION" in detail, "a skipped source should say where that evidence does come from"


def test_a_ready_task_with_no_collector_warns_rather_than_vanishing(caplog):
    plan = plan_for('CASE "c"\nCOLLECT NETWORK\n')
    plan["tasks"][0]["source"] = "UNKNOWN_SOURCE"
    with caplog.at_level("WARNING"):
        assert plan_runner.runnable_tasks(plan) == []
    assert "UNKNOWN_SOURCE" in caplog.text
    assert "nothing is claimed" in caplog.text


def test_the_endpoint_task_queue_has_no_column_a_command_could_live_in():
    from backend.storage import MIGRATIONS

    ddl = " ".join(statement for group in MIGRATIONS.values() for statement in group)
    table = ddl[ddl.index("CREATE TABLE endpoint_tasks"):]
    table = table[:table.index(")")].lower()
    for word in ("command", "script", "shell", "exec", "payload"):
        assert word not in table, f"endpoint_tasks has a {word} column"


def test_the_agent_contains_no_way_to_execute_anything():
    import pathlib
    import re

    import endpoint.agent

    source = pathlib.Path(endpoint.agent.__file__).read_text()
    forbidden = re.compile(r"(subprocess|os\.system|eval\(|exec\(|popen)")
    offending = [line.strip() for line in source.splitlines() if forbidden.search(line)]
    assert not offending, f"the agent must not be able to execute anything: {offending}"
