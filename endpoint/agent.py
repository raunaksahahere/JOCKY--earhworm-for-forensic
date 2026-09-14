"""
The JOCKY endpoint agent.

This process runs on a machine an investigator has been authorized to collect
from. It enrolls once with a token an operator issued, then asks the control
plane whether there is forensic collection to do.

The agent's own safety property is that it does not trust the control plane.
A task names a *source*; the agent looks that source up in its own local
registry and runs the collector it finds there, or reports that it has no
collector for it. It never evaluates anything the server sends. If the control
plane were replaced by an attacker, the worst it could ask for is forensic
collection the agent already knows how to perform -- not code execution.

There is no remote shell here, and adding one would defeat the reason this
agent can be deployed at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend import plan_runner
from backend.versions import APPLICATION_VERSION

HEARTBEAT_SECONDS = 60
POLL_SECONDS = 15
#: A task that runs longer than this is reported as timed out rather than left
#: to hold the agent forever.
TASK_TIMEOUT_SECONDS = 900
REQUEST_TIMEOUT = 30
MAX_BACKOFF = 300

log = logging.getLogger("jocky.endpoint")


class AgentError(RuntimeError):
    pass


def capabilities() -> list:
    """The sources this agent can actually collect on this host."""
    return plan_runner.endpoint_sources()


def describe_host() -> dict:
    return {"hostname": socket.gethostname(), "platform": platform.system(),
            "platform_release": platform.release(), "agent_version": APPLICATION_VERSION,
            "capabilities": capabilities()}


class ControlPlaneClient:
    """HTTP to one control plane, with the endpoint credential attached."""

    def __init__(self, base_url, *, endpoint_id=None, token=None, opener=None):
        self.base_url = base_url.rstrip("/")
        self.endpoint_id, self.token = endpoint_id, token
        self._opener = opener or urllib.request.urlopen

    def post(self, path, payload, *, authenticated=True):
        data = json.dumps(payload).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        if authenticated:
            if not self.endpoint_id or not self.token:
                raise AgentError("The agent is not enrolled")
            request.add_header("Authorization", f"Bearer {self.token}")
            request.add_header("X-Jocky-Endpoint", self.endpoint_id)
        try:
            with self._opener(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            raise AgentError(f"{path} failed with HTTP {error.code}: {body[:400]}") from error
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise AgentError(f"{path} could not be reached: {error}") from error


class Agent:
    def __init__(self, client, *, identity_path=None, stop=None):
        self.client = client
        self.identity_path = Path(identity_path) if identity_path else None
        self.stop = stop or threading.Event()

    # --- identity --------------------------------------------------------
    def load_identity(self) -> bool:
        if not self.identity_path or not self.identity_path.is_file():
            return False
        identity = json.loads(self.identity_path.read_text())
        self.client.endpoint_id = identity.get("endpoint_id")
        self.client.token = identity.get("endpoint_token")
        return bool(self.client.endpoint_id and self.client.token)

    def save_identity(self, identity: dict):
        if not self.identity_path:
            return
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity_path.write_text(json.dumps(identity, indent=2))
        # The credential is readable only by the account running the agent.
        self.identity_path.chmod(0o600)

    def enroll(self, enrollment_token: str, endpoint_name: str) -> dict:
        payload = dict(describe_host(), enrollment_token=enrollment_token,
                       endpoint_name=endpoint_name)
        identity = self.client.post("/api/v1/endpoints/enroll", payload, authenticated=False)
        self.client.endpoint_id = identity["endpoint_id"]
        self.client.token = identity["endpoint_token"]
        self.save_identity({"endpoint_id": identity["endpoint_id"],
                            "endpoint_token": identity["endpoint_token"],
                            "name": endpoint_name, "control_plane": self.client.base_url})
        log.info("Enrolled as %s (%s)", endpoint_name, identity["endpoint_id"])
        return identity

    # --- work ------------------------------------------------------------
    def heartbeat(self) -> dict:
        return self.client.post("/api/v1/endpoints/heartbeat", describe_host())

    def run_task(self, task: dict) -> dict:
        """Execute one named collection locally.

        The server's `collector` field is passed to the registry check, which
        refuses the task unless it agrees with what this build provides. The
        agent runs its own code or nothing.
        """
        source = task.get("source")
        entry = plan_runner.REGISTRY.get(source)
        if entry is None:
            return {"ok": False, "error": {
                "code": "source_unsupported",
                "message": (f"This endpoint has no collector for {source}. Nothing was collected "
                            "and nothing is claimed about it.")}}
        function, dotted, action = entry
        if task.get("collector") and task["collector"] != dotted:
            return {"ok": False, "error": {
                "code": "collector_mismatch",
                "message": (f"The task names {task['collector']} for {source}; this endpoint "
                            f"provides {dotted}. The task was refused.")}}

        cancel = threading.Event()
        outcome = {}

        def collect():
            try:
                outcome["result"] = plan_runner.call(
                    {"task": task, "function": function, "action": action,
                     "source_description": plan_runner.SOURCE_DESCRIPTIONS[source]},
                    options=task.get("options") or {}, cancel=cancel)
            except Exception as error:  # reported, never swallowed
                outcome["error"] = {"code": "collector_failed", "message": str(error)}

        worker = threading.Thread(target=collect, name=f"jocky-collect-{source}", daemon=True)
        worker.start()
        worker.join(timeout=TASK_TIMEOUT_SECONDS)
        if worker.is_alive():
            cancel.set()
            return {"ok": False, "error": {
                "code": "timeout",
                "message": f"{source} collection exceeded {TASK_TIMEOUT_SECONDS}s and was stopped."}}
        if "error" in outcome:
            return {"ok": False, "error": outcome["error"]}
        return {"ok": True, "result": outcome["result"]}

    def poll_once(self, *, max_batches=8) -> int:
        """Claim, run and report everything currently waiting.

        The queue is drained rather than sampled: a collection dispatched as six
        tasks should finish in one visit, not leave two of them sitting until
        the next poll interval. The batch cap stops a misbehaving server from
        holding the agent in an endless loop.
        """
        handled = 0
        for _ in range(max_batches):
            claimed = self.client.post("/api/v1/endpoints/tasks/claim", {"limit": 4})
            tasks = claimed.get("tasks", [])
            if not tasks:
                break
            for task in tasks:
                log.info("Collecting %s for task %s", task.get("source"), task.get("task_id"))
                outcome = self.run_task(task)
                self.client.post(f"/api/v1/endpoints/tasks/{task['task_id']}/result", outcome)
            handled += len(tasks)
        return handled

    def run(self):
        """Heartbeat and poll until stopped."""
        backoff, last_heartbeat = POLL_SECONDS, 0.0
        while not self.stop.is_set():
            try:
                if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                    self.heartbeat()
                    last_heartbeat = time.monotonic()
                handled = self.poll_once()
                backoff = POLL_SECONDS
                if handled:
                    continue
            except AgentError as error:
                # The control plane being unreachable is expected on a laptop
                # that sleeps or moves networks; back off and keep trying rather
                # than exiting and leaving the endpoint silently unmanaged.
                log.warning("Control plane unavailable: %s", error)
                backoff = min(backoff * 2, MAX_BACKOFF)
            self.stop.wait(backoff)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="JOCKY endpoint agent. Performs authorized forensic collection on request. "
                    "It accepts named collection sources only and never remote commands.")
    parser.add_argument("--control-plane", required=True, help="Base URL of the JOCKY server")
    parser.add_argument("--identity", default="~/.config/jocky/endpoint.json",
                        help="Where the endpoint credential is stored")
    parser.add_argument("--enroll", metavar="TOKEN", help="Enrollment token issued by an operator")
    parser.add_argument("--name", help="Endpoint name this token was issued for")
    parser.add_argument("--once", action="store_true", help="Poll a single time and exit")
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    identity_path = Path(arguments.identity).expanduser()
    agent = Agent(ControlPlaneClient(arguments.control_plane), identity_path=identity_path)

    if arguments.enroll:
        if not arguments.name:
            parser.error("--enroll also needs --name, the endpoint name the token was issued for")
        agent.enroll(arguments.enroll, arguments.name)
    elif not agent.load_identity():
        parser.error(f"No endpoint credential at {identity_path}. Enroll first with --enroll.")

    if arguments.once:
        handled = agent.poll_once()
        print(f"Handled {handled} task(s).")
        return 0
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
