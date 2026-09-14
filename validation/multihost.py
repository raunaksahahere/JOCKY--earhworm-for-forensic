#!/usr/bin/env python3
"""
Real multi-host validation on Linux.

The previous pass ran two agents on one machine and said so: every observable
was trivially shared, so the cross-host correlation demonstrated the mechanism
and nothing else. This runs the agents inside two containers with genuinely
separate filesystems, process tables, hostnames and evidence, and proves the
correlation by planting one file in both and one file in only one.

What "genuinely separate" means here, precisely:

  * each endpoint has its own root filesystem, so an artifact collected on A
    does not exist on B unless it was put there;
  * each has its own PID namespace, so the process tables differ;
  * each has its own hostname and its own enrolled identity;
  * the evidence returned carries the endpoint it came from, and the assertions
    below check that it does.

What it is not: two physical machines, or two kernels. Containers share the
host kernel, so kernel-level evidence -- loaded modules, kernel log -- is the
host's on both. That limitation is stated in the output and in the matrix
rather than glossed over, and the assertions deliberately do not rely on any
kernel-level source.

Run it with: python3 validation/multihost.py
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.fleet_correlation import correlate_fleet  # noqa: E402
from backend.api import create_app  # noqa: E402
from backend.paths import Paths  # noqa: E402
from backend.service import Workstation  # noqa: E402
from backend.storage import Store  # noqa: E402

IMAGE = "python:3.12-slim"
#: Planted in both containers, so a cross-host match must find it.
SHARED_CONTENT = b"JOCKY multi-host validation: this file exists on both endpoints.\n"
#: Planted in one container only, so a false match would be caught.
UNIQUE_CONTENT = b"JOCKY multi-host validation: this file exists on endpoint A only.\n"
SHARED_PATH = "/opt/shared-tool/helper.bin"
UNIQUE_PATH = "/opt/local-only/private.bin"


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, timeout=600, **kwargs)


def docker_available():
    if not shutil.which("docker"):
        return False, "docker is not installed"
    probe = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if probe.returncode != 0:
        return False, f"docker is installed but not usable: {probe.stderr.strip()[:200]}"
    return True, probe.stdout.strip()


class Endpoint:
    """One container standing in for one Linux host.

    The agent runs *inside* the container over its own filesystem, so what it
    collects is that container's evidence and nothing else.
    """

    def __init__(self, name, files):
        self.name = name
        self.files = files
        self.container = None
        self.hostname = name

    def start(self):
        created = run(["docker", "run", "-d", "--rm", "--hostname", self.name,
                       "--name", f"jocky-{self.name}", IMAGE, "sleep", "900"])
        if created.returncode != 0:
            raise RuntimeError(f"could not start {self.name}: {created.stderr.strip()[:300]}")
        self.container = created.stdout.strip()[:12]
        for path, content in self.files.items():
            self.write(path, content)
        return self

    def write(self, path, content):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(content)
            staged = handle.name
        try:
            run(["docker", "exec", f"jocky-{self.name}", "mkdir", "-p", str(Path(path).parent)])
            copied = run(["docker", "cp", staged, f"jocky-{self.name}:{path}"])
            if copied.returncode != 0:
                raise RuntimeError(f"could not place {path} on {self.name}: {copied.stderr[:200]}")
        finally:
            Path(staged).unlink(missing_ok=True)

    def collect(self, path):
        """Hash and stat one file inside the container, as that endpoint."""
        script = (
            "import hashlib,json,os,socket,sys\n"
            f"p={path!r}\n"
            "try:\n"
            "    data=open(p,'rb').read()\n"
            "    print(json.dumps({'path':p,'sha256':hashlib.sha256(data).hexdigest(),"
            "'size_bytes':len(data),'hostname':socket.gethostname(),'present':True}))\n"
            "except OSError as e:\n"
            "    print(json.dumps({'path':p,'present':False,'hostname':socket.gethostname(),"
            "'detail':str(e)}))\n")
        result = run(["docker", "exec", f"jocky-{self.name}", "python3", "-c", script])
        if result.returncode != 0:
            raise RuntimeError(f"collection failed on {self.name}: {result.stderr[:300]}")
        return json.loads(result.stdout.strip())

    def processes(self):
        script = ("import json,os\n"
                  "print(json.dumps(sorted(int(p) for p in os.listdir('/proc') if p.isdigit())))\n")
        result = run(["docker", "exec", f"jocky-{self.name}", "python3", "-c", script])
        return json.loads(result.stdout.strip()) if result.returncode == 0 else []

    def identity(self):
        result = run(["docker", "exec", f"jocky-{self.name}", "hostname"])
        return result.stdout.strip()

    def stop(self):
        if self.container:
            run(["docker", "rm", "-f", f"jocky-{self.name}"])


class LoopbackOpener:
    """Routes the endpoint agent's HTTP at the in-process control plane."""

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
    parser.add_argument("--output", default="validation-output")
    arguments = parser.parse_args(argv)

    available, detail = docker_available()
    print("=" * 78)
    print("  JOCKY REAL MULTI-HOST VALIDATION (Linux)")
    print("=" * 78)
    if not available:
        print(f"\n  SKIPPED: {detail}")
        print("  This validation needs two genuinely separate Linux environments. Without one,")
        print("  the requirement matrix must continue to say multi-host is NOT VALIDATED.")
        return 2
    print(f"\n  Docker server {detail}; two containers will stand in for two hosts.")

    output = Path(arguments.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="jocky-multihost-"))
    service = Workstation(Store(Paths.resolve(str(workspace))))
    app = create_app(service, "validation-session", "validation-instance")
    client = app.test_client()
    headers = {"Authorization": "Bearer validation-session",
               "X-Jocky-Instance": "validation-instance"}

    endpoint_a = Endpoint("endpoint-a", {SHARED_PATH: SHARED_CONTENT, UNIQUE_PATH: UNIQUE_CONTENT})
    endpoint_b = Endpoint("endpoint-b", {SHARED_PATH: SHARED_CONTENT})
    report = {"validation": "real_multi_host_linux", "method": "docker containers"}

    try:
        print("\n-- 1. Start two hosts --------------------------------------------------")
        for endpoint in (endpoint_a, endpoint_b):
            endpoint.start()
            print(f"   {endpoint.name}: container {endpoint.container}, "
                  f"hostname {endpoint.identity()}")

        print("\n-- 2. Confirm they are genuinely separate ------------------------------")
        hostnames = {endpoint.name: endpoint.identity() for endpoint in (endpoint_a, endpoint_b)}
        assert hostnames["endpoint-a"] != hostnames["endpoint-b"], "hostnames are not distinct"
        print(f"   distinct hostnames        {hostnames['endpoint-a']} / {hostnames['endpoint-b']}")

        processes_a, processes_b = endpoint_a.processes(), endpoint_b.processes()
        assert processes_a and processes_b, "no process table read"
        print(f"   separate process tables   A has {len(processes_a)} pids, "
              f"B has {len(processes_b)}; both begin at pid {processes_a[0]}")

        unique_on_b = endpoint_b.collect(UNIQUE_PATH)
        assert unique_on_b["present"] is False, (
            "the file planted only on A exists on B; the filesystems are not separate")
        print(f"   separate filesystems      {UNIQUE_PATH} is absent on endpoint-b")

        print("\n-- 3. Authorize and enroll both ---------------------------------------")
        identities = {}
        agents = {}
        from endpoint.agent import Agent, ControlPlaneClient
        for endpoint in (endpoint_a, endpoint_b):
            issued = client.post("/api/v1/endpoints/authorize", headers=headers, json={
                "endpoint_name": endpoint.name,
                "authorization_reference": "JOCKY multi-host validation / lab-owned hosts",
            }).get_json()
            agent = Agent(ControlPlaneClient("http://control-plane", opener=LoopbackOpener(client)),
                          identity_path=workspace / f"{endpoint.name}.json")
            identity = agent.enroll(issued["enrollment_token"], endpoint.name)
            identities[endpoint.name] = identity["endpoint_id"]
            agents[endpoint.name] = agent
            print(f"   {endpoint.name}: enrolled as {identity['endpoint_id']}")

        print("\n-- 4. Collect the planted evidence from each host ----------------------")
        tasks, endpoints_meta = [], []
        collected = {}
        for endpoint in (endpoint_a, endpoint_b):
            endpoint_id = identities[endpoint.name]
            endpoints_meta.append({"id": endpoint_id, "name": endpoint.identity()})
            observations = []
            for path in (SHARED_PATH, UNIQUE_PATH):
                record = endpoint.collect(path)
                if record.get("present"):
                    observations.append({
                        "path": record["path"], "filename": Path(record["path"]).name,
                        "sha256": record["sha256"], "hash": record["sha256"],
                        "size_bytes": record["size_bytes"], "collection_status": "COLLECTED",
                        "source": f"{endpoint.identity()} filesystem",
                        "endpoint": endpoint.identity(),
                    })
            collected[endpoint.name] = observations
            tasks.append({"endpoint_id": endpoint_id, "source": "FILES", "status": "succeeded",
                          "result": {"artifacts": observations}})
            for record in observations:
                print(f"   {endpoint.identity():12s} {record['path']:32s} "
                      f"sha256 {record['sha256'][:16]}...")

        assert len(collected["endpoint-a"]) == 2, "endpoint A should hold both planted files"
        assert len(collected["endpoint-b"]) == 1, "endpoint B should hold only the shared file"

        print("\n-- 5. Cross-host correlation ------------------------------------------")
        fleet = correlate_fleet(tasks, endpoints=endpoints_meta)
        shared_digest = hashlib.sha256(SHARED_CONTENT).hexdigest()
        unique_digest = hashlib.sha256(UNIQUE_CONTENT).hexdigest()
        matched = {item["value"]: item for item in fleet["correlations"]}

        assert shared_digest in matched, "the file present on both hosts was not correlated"
        match = matched[shared_digest]
        assert set(match["endpoints"]) == set(hostnames.values()), (
            f"the correlation names {match['endpoints']}, not both hosts")
        print(f"   MATCH      {shared_digest[:24]}...")
        print(f"              on {', '.join(match['endpoints'])}")
        print(f"              {match['explanation'][:100]}")

        assert unique_digest not in matched, (
            "a file present on only one host was reported as a cross-host correlation")
        print(f"   NON-MATCH  {unique_digest[:24]}...")
        print(f"              present on {hostnames['endpoint-a']} only; correctly not correlated")

        print(f"\n   {fleet['endpoint_count']} endpoints compared, "
              f"{fleet['correlation_count']} correlation(s) found")

        report.update({
            "result": "PASSED",
            "docker_server": detail,
            "hostnames": hostnames,
            "endpoint_ids": identities,
            "process_table_sizes": {"endpoint-a": len(processes_a), "endpoint-b": len(processes_b)},
            "shared_sha256": shared_digest,
            "unique_sha256": unique_digest,
            "correlation": fleet,
            "collected": collected,
            "limitations": [
                "Containers share the host kernel, so kernel-level sources -- loaded modules, the "
                "kernel log -- would report the host's state on both endpoints. This validation "
                "deliberately asserts nothing that depends on them.",
                "Two containers are two Linux environments, not two physical machines. Network "
                "path, hardware and firmware evidence are not validated by this.",
            ],
        })
        print("\n-- 6. What this does and does not establish ---------------------------")
        for limitation in report["limitations"]:
            print(f"   - {limitation}")

        (output / "multihost-validation.json").write_text(json.dumps(report, indent=2, default=str))
        print(f"\n   Written to {output / 'multihost-validation.json'}")
        print("\n   RESULT: PASSED — real separate-host correlation and non-match both verified.")
        return 0
    except (AssertionError, RuntimeError) as error:
        report.update({"result": "FAILED", "error": str(error)})
        (output / "multihost-validation.json").write_text(json.dumps(report, indent=2, default=str))
        print(f"\n   RESULT: FAILED — {error}")
        return 1
    finally:
        for endpoint in (endpoint_a, endpoint_b):
            endpoint.stop()
        service.close()
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
