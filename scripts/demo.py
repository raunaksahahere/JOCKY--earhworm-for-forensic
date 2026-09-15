#!/usr/bin/env python3
"""
The JOCKY demonstration: one case, end to end, from a clean checkout.

    python3 scripts/demo.py [--output DIR] [--keep]

It runs the whole chain in one process and prints each stage as it completes:

    case -> investigation program -> AST -> IR -> Linux execution plan
         -> authorized endpoints -> evidence -> normalization -> correlation
         -> activity threads -> timeline -> findings -> investigator report
         -> evidence package

Two kinds of evidence appear, and they are never mixed. The endpoints collect
from *this* machine, so that evidence is real. The scenarios are synthetic and
every record they produce is labelled SYNTHETIC, because a demonstration that
quietly presents fabricated data as host evidence is the one thing a forensic
tool must never do.

Nothing is written outside the output directory, and the demo's own workspace
is removed at the end unless --keep is given.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.fleet_correlation import correlate_fleet  # noqa: E402
from backend.api import create_app  # noqa: E402
from backend.paths import Paths  # noqa: E402
from backend.pdf_report import page_count, render_investigator_pdf, render_pdf  # noqa: E402
from backend.service import Workstation  # noqa: E402
from backend.storage import Store  # noqa: E402
from compiler.investigation import compile_program, describe, parse  # noqa: E402
from compiler.plan import build_plan, describe_plan  # noqa: E402
from endpoint.agent import Agent, ControlPlaneClient  # noqa: E402
from scenarios import SCENARIOS, run_scenario  # noqa: E402

PROGRAM = '''CASE "Suspected data staging on the lab workstation" {
    TITLE "Unexplained archive activity reported by the lab owner"
    EXAMINER "JOCKY demonstration"
}
TARGET "localhost"
WINDOW LAST 24 HOURS

# Named once, so the program reads as the question rather than as a list.
LET download_tools = ["/usr/bin/curl", "/usr/bin/wget"]

# A playbook: the evidence every host must yield for results to be comparable.
DEFINE host_triage {
    COLLECT PROCESSES
    COLLECT EXECUTION
    COLLECT NETWORK
}

RUN host_triage

# Removable media and loaded kernel modules are Linux-only in this build. The
# guard travels into the IR and is resolved by the platform adapter, so on
# Windows these become named skips rather than silent omissions.
WHEN PLATFORM IS linux {
    COLLECT USB
    COLLECT DRIVERS
    CORRELATE EXECUTION WITH USB
}

COLLECT BROWSER
COLLECT SERVICES

FILTER PATH ONEOF $download_tools OR COMMAND CONTAINS "curl"

TIMELINE FULL
REPORT SUMMARY AS "lab-workstation-summary"
'''

STEP = 0


def step(title):
    global STEP
    STEP += 1
    print(f"\n{'=' * 78}\n  STEP {STEP}. {title}\n{'=' * 78}")


class LoopbackOpener:
    """Routes the endpoint agent's HTTP at the in-process control plane.

    The demo runs the server and the agents in one process, so there is no
    socket to bind and no port to collide with another demo run. The agent code
    exercised here is the same code that speaks to a real server.
    """

    def __init__(self, client):
        self.client = client

    def __call__(self, request, timeout=None):
        response = self.client.open(
            request.full_url.replace("http://control-plane", ""), method=request.method,
            headers=dict(request.headers), data=request.data)
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "error", None,
                                         io.BytesIO(response.data))
        payload = response.data

        class Reply:
            def __enter__(inner):
                return inner

            def __exit__(inner, *exception):
                return False

            def read(inner):
                return payload
        return Reply()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="demo-output", help="Where to write the package")
    parser.add_argument("--keep", action="store_true", help="Keep the demo database")
    parser.add_argument("--endpoints", type=int, default=2, help="Synthetic endpoints to enroll")
    arguments = parser.parse_args(argv)

    output = Path(arguments.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="jocky-demo-"))
    service = Workstation(Store(Paths.resolve(str(workspace))))
    app = create_app(service, token="demo-session", instance_id="demo-instance")
    client = app.test_client()
    headers = {"Authorization": "Bearer demo-session", "X-Jocky-Instance": "demo-instance"}

    def call(method, url, payload=None, **kwargs):
        response = getattr(client, method)(url, headers=headers, json=payload, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{url} failed: {response.status_code} {response.get_data(as_text=True)}")
        return response

    try:
        # ------------------------------------------------------------------
        step("Open a case")
        case = call("post", "/api/v1/cases", {
            "title": "Suspected data staging on the lab workstation",
            "examiner": "demo examiner",
            "reference": "SIH-DEMO-2026",
        }).get_json()
        print(f"  {case['id']}  {case['title']}\n  opened {case['created_at']} by {case['examiner']}")

        # ------------------------------------------------------------------
        step("Write an investigation program")
        print("\n".join(f"  | {line}" for line in PROGRAM.strip().splitlines()))

        step("Parse it to an AST")
        ast = parse(PROGRAM)
        print(f"  case      {ast['case']['id']}")
        print(f"  targets   {', '.join(target['name'] for target in ast['targets'])}")
        print(f"  window    {ast['window']}")
        print(f"  collect   {', '.join(item['source'] for item in ast['collections'])}")
        print(f"  correlate {len(ast['correlations'])}   timeline {bool(ast['timeline'])}   "
              f"report {', '.join(report['kind'] for report in ast['reports'])}")

        step("Compile the AST to platform-neutral IR")
        ir = compile_program(PROGRAM)
        print(f"  IR version {ir['ir_version']}, {len(ir['collections'])} collections, "
              f"window {ir['window_hours']}h")
        print("\n".join(f"  {line}" for line in describe(ir).splitlines()))

        step("Build the execution plan for this platform")
        plan = build_plan(ir)
        print("\n".join(f"  {line}" for line in describe_plan(plan).splitlines()))
        print(f"\n  {plan['note']}")

        # ------------------------------------------------------------------
        step(f"Authorize and enroll {arguments.endpoints} endpoint(s)")
        agents = {}
        for index in range(1, arguments.endpoints + 1):
            name = f"demo-endpoint-{index}"
            issued = call("post", "/api/v1/endpoints/authorize", {
                "endpoint_name": name,
                "authorization_reference": "SIH-DEMO-2026 / written consent of the machine owner",
                "issued_by": "demo examiner"}).get_json()
            print(f"  authorized {name}: token {issued['token_id']}, expires {issued['expires_at']}")
            agent = Agent(ControlPlaneClient("http://control-plane", opener=LoopbackOpener(client)),
                          identity_path=workspace / f"{name}.json")
            identity = agent.enroll(issued["enrollment_token"], name)
            agents[name] = agent
            print(f"  enrolled  {name}: {identity['endpoint_id']}")
        endpoints = call("get", "/api/v1/endpoints").get_json()["items"]
        for record in endpoints:
            print(f"  {record['id']}  {record['name']:18s} {record['health']['state']:8s} "
                  f"{len(record['capabilities'])} collectors")

        # ------------------------------------------------------------------
        step("Dispatch the plan to every endpoint and collect")
        dispatch = call("post", "/api/v1/collections/dispatch", {
            "program": PROGRAM, "case_id": case["id"],
            "endpoints": [record["id"] for record in endpoints]}).get_json()
        print(f"  {dispatch['tasks_per_endpoint']} task(s) queued on each of "
              f"{dispatch['endpoint_count']} endpoint(s)")
        for skipped in dispatch["unsupported"]:
            print(f"  not collected: {skipped['source']} -- {skipped['detail']}")
        started = time.monotonic()
        for name, agent in agents.items():
            handled = agent.poll_once()
            print(f"  {name}: collected {handled} source(s)")
        print(f"  endpoint collection took {time.monotonic() - started:.1f}s")

        tasks = call("get", "/api/v1/endpoint-tasks").get_json()["items"]
        for task in tasks:
            marker = "ok " if task["status"] == "succeeded" else "-- "
            print(f"  {marker}{task['endpoint_id']}  {task['source']:9s} {task['status']:10s} "
                  f"sha256 {(task['result_sha256'] or '')[:16]}")

        # ------------------------------------------------------------------
        step("Run the same program against this workstation")
        investigation = call("post", "/api/v1/investigations", {
            "title": "Local collection for the demo case", "case_id": case["id"]}).get_json()
        # Driven by the program itself, not by a list of ticked sources. The UI
        # path compiles its selection into exactly this shape, so both routes
        # reach the engine through the same compiler.
        call("post", f"/api/v1/investigations/{investigation['id']}/collect",
             {"paths": [], "window_hours": 24, "program": PROGRAM})
        for _ in range(900):
            investigation = call("get", f"/api/v1/investigations/{investigation['id']}").get_json()
            if investigation["status"] in ("completed", "partially_completed", "failed", "cancelled"):
                break
            time.sleep(1)
        print(f"  {investigation['id']}  status {investigation['status']}  "
              f"{investigation['evidence_count']} evidence records  "
              f"{investigation['finding_count']} findings")

        # ------------------------------------------------------------------
        step("Normalization, correlation, threads, timeline and findings")
        report = call("get", f"/api/v1/investigations/{investigation['id']}/reports").get_json()
        payload = report["items"][-1]["payload"]
        summary = payload.get("investigator_summary") or {}
        execution = payload.get("historical_execution", {})
        counts = payload.get("record_counts", {})
        available = [source for source in execution.get("sources", [])
                     if source.get("status") == "AVAILABLE"]
        print(f"  telemetry sources read  {len(available)} of {len(execution.get('sources', []))}")
        print(f"  normalized events       {execution.get('event_count', 0)}")
        print(f"  distinct activity       {counts.get('distinct_activity', 0)}")
        print(f"  activity threads        {counts.get('threads', 0)}")
        print(f"  artifacts hashed        {counts.get('artifacts', 0)}")
        print(f"  timeline entries        {len(payload.get('event_timeline', []))}")
        print(f"  significant events      {counts.get('significant_events', 0)}")
        print(f"  findings                {counts.get('findings', 0)}")
        print(f"  leads                   {counts.get('leads', 0)}  "
              f"(priority 1: {counts.get('priority_1', 0)}, "
              f"priority 2: {counts.get('priority_2', 0)})")
        print(f"  collection limitations  {counts.get('collection_limitations', 0)}")
        for lead in payload.get("leads", [])[:3]:
            print(f"    {lead['priority_label']:30s} {lead['title'][:44]}")
        print("\n  The report states what could not be read as plainly as what could:")
        for limitation in payload.get("limitations", [])[:3]:
            text = limitation if isinstance(limitation, str) else limitation.get("detail", "")
            print(f"    - {text[:88]}")

        # ------------------------------------------------------------------
        step("Answer the program's FILTER against the collected evidence")
        selection = call(
            "get", f"/api/v1/investigations/{investigation['id']}/selection").get_json()
        for line in selection.get("filters", []):
            print(f"  filter    {line}")
        if selection.get("applied"):
            print(f"  selected  {selection['total']} record(s) "
                  f"({', '.join(f'{kind} {count}' for kind, count in
                                sorted(selection['counts'].items())) or 'none'})")
            for result in selection["results"][:5]:
                print(f"    {result['kind']:18s} {str(result['id'] or '-'):12s} "
                      f"{str(result['label'])[:44]}")
            if not selection["results"]:
                print("    Nothing on this host answers that question. The evidence is still")
                print("    complete and hashed; the selection is empty, not missing.")
        print(f"\n  {selection.get('note', '')}")

        step("Correlate across hosts")
        fleet = correlate_fleet(tasks, endpoints=endpoints)
        print(f"  {fleet['endpoint_count']} endpoint(s) compared on "
              f"{', '.join(fleet['sources_compared']) or 'nothing'}")
        print(f"  {fleet['correlation_count']} shared observable(s); "
              f"{sum(fleet['suppressed'].values())} fleet-wide driver(s) counted and not listed")
        for match in fleet["correlations"][:5]:
            print(f"    {match['kind']:15s} {match['value'][:44]:46s} on {len(match['endpoints'])}")
        print("\n  Read these with the demo's own limitation in mind: both endpoints are agents\n"
              "  running on this one machine, so every observable is trivially shared. What is\n"
              "  being shown is the mechanism, not a finding. Scenario D is the multi-host case\n"
              "  with genuinely separate evidence.")

        # ------------------------------------------------------------------
        step("Run the synthetic lab scenarios")
        scenario_results = {}
        for key in SCENARIOS:
            result = run_scenario(key)
            scenario_results[key] = result
            print(f"  {key}  {result['title'][:46]:48s} findings {len(result['findings']):2d}  "
                  f"leads {len(result['leads']):2d}  "
                  f"top {result['highest_lead_priority'] or result['highest_finding_priority']}")
        print("\n  Every record above is fabricated and labelled SYNTHETIC. None of it is "
              "evidence\n  about this machine or any other.")

        # ------------------------------------------------------------------
        step("Write the evidence package")
        report_pdf = output / "investigator-report.pdf"
        investigator = render_investigator_pdf(payload)
        report_pdf.write_bytes(investigator)
        # The long document too, so the demo shows the difference rather than
        # asserting it: the same evidence, presented two ways.
        full = render_pdf(payload)
        (output / "full-report.pdf").write_bytes(full)
        print(f"  investigator report  {page_count(investigator)} pages")
        print(f"  full report          {page_count(full)} pages "
              f"(the same evidence, every appendix appended)")
        (output / "report.json").write_text(json.dumps(payload, indent=2, default=str))
        (output / "program.x").write_text(PROGRAM)
        (output / "ir.json").write_text(json.dumps(ir, indent=2))
        (output / "execution-plan.json").write_text(json.dumps(plan, indent=2))
        (output / "endpoint-tasks.json").write_text(json.dumps(tasks, indent=2, default=str))
        (output / "cross-host-correlation.json").write_text(json.dumps(fleet, indent=2, default=str))
        (output / "audit-trail.json").write_text(json.dumps(
            call("get", f"/api/v1/audit?case_id={case['id']}").get_json(), indent=2, default=str))
        scenarios_directory = output / "synthetic-scenarios"
        scenarios_directory.mkdir(exist_ok=True)
        for key, result in scenario_results.items():
            (scenarios_directory / f"scenario-{key}.json").write_text(
                json.dumps(result, indent=2, default=str))
        for file in sorted(output.rglob("*")):
            if file.is_file():
                print(f"  {file.relative_to(output)}  ({file.stat().st_size:,} bytes)")

        step("What the demo established")
        print(f"  Case {case['id']} holds one local investigation and {len(tasks)} endpoint tasks.")
        print(f"  The report at {report_pdf} was produced from evidence collected on this host.")
        print(f"  The report is {page_count(investigator)} pages because that is how much there "
              "is to say;")
        print(f"  the same evidence appended runs to {page_count(full)}, and none of it was "
              "discarded.")
        print("  The synthetic scenarios are labelled throughout and are not host evidence.")
        print("  The audit trail records every action taken, separately from the evidence.")
        return 0
    finally:
        service.close()
        if arguments.keep:
            print(f"\n  Demo database kept at {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
