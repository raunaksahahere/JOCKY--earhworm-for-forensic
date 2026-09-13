"""
Authorized multi-endpoint collection.

The hard rule of this module is that an endpoint is never sent something to
run. It is sent a *source name* and bounded options -- the same structured plan
task the local collector consumes -- and it decides for itself whether it has a
collector for that source. There is no command field on a task, no shell, and
no path by which the control plane can cause arbitrary code to execute on an
enrolled machine. An operator who compromised this server would gain the
ability to request forensic collection, not the ability to run programs.

Authorization is explicit and happens before anything else. An operator issues
a single-use, expiring enrollment token naming one endpoint and the authority
for collecting from it. The endpoint presents that token once and receives a
long-lived credential, which the server keeps only as a salted digest.

Everything an endpoint returns is evidence about *that* host, and is recorded
with the endpoint's identity so a finding can never drift loose from the
machine it came from.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from backend.casework import CaseworkError
from backend.storage import encode, identifier, now
from backend.versions import versions
from compiler.plan import READY, build_plan

#: How long an unused enrollment token stays valid.
ENROLLMENT_TTL_MINUTES = 60
#: After this long without a heartbeat an endpoint is reported as stale rather
#: than healthy. It is not evidence that the machine is gone -- only that JOCKY
#: has not heard from it.
STALE_AFTER_SECONDS = 300
MAX_ATTEMPTS = 3
#: Backoff before a failed task becomes available again.
RETRY_DELAYS = (30, 120, 600)
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_ENDPOINTS = 500
MAX_QUEUED_PER_ENDPOINT = 64

ENROLLED, ACTIVE, REVOKED = "enrolled", "active", "revoked"
QUEUED, DISPATCHED, SUCCEEDED, FAILED, ABANDONED = (
    "queued", "dispatched", "succeeded", "failed", "abandoned")


def _hash_token(token: str, salt: str) -> str:
    """A salted digest of a credential.

    The database holds this and never the token, so a stolen copy of the
    database yields nothing that can authenticate. Deliberately a single SHA-256
    rather than a stretched hash: these credentials are 40 bytes of generated
    entropy, not passwords, so there is no dictionary to slow down -- and an
    endpoint presents its credential on every poll, where a deliberately slow
    hash would be a self-inflicted denial of service rather than a defence.
    """
    return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()


def _timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _future(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class Fleet:
    """Enrollment, heartbeat, task dispatch and result ingestion."""

    STALE_AFTER_SECONDS = STALE_AFTER_SECONDS
    MAX_ATTEMPTS = MAX_ATTEMPTS

    def __init__(self, store, casework):
        self.store, self.casework = store, casework

    # --- endpoint events -------------------------------------------------
    def _event(self, db, endpoint_id, event, outcome="success", detail=None):
        db.execute(
            "INSERT INTO endpoint_events (endpoint_id,timestamp,event,outcome,detail)"
            " VALUES (?,?,?,?,?)",
            (endpoint_id, now(), event, outcome, encode(detail) if detail is not None else None))

    def events(self, endpoint_id=None, limit=500):
        query, args = "SELECT * FROM endpoint_events", ()
        if endpoint_id:
            query, args = query + " WHERE endpoint_id=?", (endpoint_id,)
        rows = self.store.rows(query + " ORDER BY id DESC LIMIT ?", args + (int(limit),))
        for row in rows:
            if row.get("detail"):
                try:
                    row["detail"] = json.loads(row["detail"])
                except ValueError:
                    pass
        return rows

    # --- authorization ---------------------------------------------------
    def issue_enrollment_token(self, data: dict) -> dict:
        """Authorize one machine to be collected from.

        The returned token is shown once and never stored in recoverable form.
        `authorization_reference` is required: collecting from someone else's
        machine should carry a record of who permitted it.
        """
        name = (data.get("endpoint_name") or "").strip()
        if not name or len(name) > 120:
            raise CaseworkError("endpoint_name must contain 1-120 characters")
        reference = (data.get("authorization_reference") or "").strip()
        if not reference:
            raise CaseworkError(
                "authorization_reference is required: record the warrant, ticket or written "
                "authority under which this endpoint may be collected from.")
        if self.store.rows("SELECT id FROM endpoints WHERE name=?", (name,)):
            raise CaseworkError(f"An endpoint named {name} is already enrolled", "conflict", 409)
        if self.store.rows("SELECT count(*) AS n FROM endpoints")[0]["n"] >= MAX_ENDPOINTS:
            raise CaseworkError(f"This build manages at most {MAX_ENDPOINTS} endpoints")

        token, salt = secrets.token_urlsafe(32), secrets.token_hex(16)
        token_id = f"ENR-{identifier()[:8].upper()}"
        expires = _future(ENROLLMENT_TTL_MINUTES * 60)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO enrollment_tokens"
                " (id,created_at,expires_at,issued_by,endpoint_name,token_salt,token_digest,"
                "  authorization_reference) VALUES (?,?,?,?,?,?,?,?)",
                (token_id, now(), expires, data.get("issued_by") or "local operator", name,
                 salt, _hash_token(token, salt), reference))
            self._event(db, None, "enrollment.token_issued",
                        detail={"endpoint_name": name, "token_id": token_id})
            self.casework.audit("endpoint.enrollment_authorized", object_type="endpoint",
                                object_id=name,
                                detail={"token_id": token_id, "authorization": reference,
                                        "expires_at": expires}, db=db)
        return {"token_id": token_id, "endpoint_name": name, "enrollment_token": token,
                "expires_at": expires, "authorization_reference": reference,
                "note": ("This token is shown once. It authorizes one machine to enroll and "
                         "nothing else.")}

    def enroll(self, data: dict) -> dict:
        """Redeem an enrollment token and issue the endpoint's credential."""
        presented = data.get("enrollment_token")
        name = (data.get("endpoint_name") or "").strip()
        if not isinstance(presented, str) or not presented or not name:
            raise CaseworkError("enrollment_token and endpoint_name are required",
                                "authentication_error", 401)
        rows = self.store.rows(
            "SELECT * FROM enrollment_tokens WHERE endpoint_name=? AND used_at IS NULL", (name,))
        record = None
        for candidate in rows:
            if hmac.compare_digest(_hash_token(presented, candidate["token_salt"]),
                                   candidate["token_digest"]):
                record = candidate
                break
        if record is None:
            with self.store.transaction() as db:
                self._event(db, None, "enrollment.rejected", outcome="failed",
                            detail={"endpoint_name": name, "reason": "no matching unused token"})
            raise CaseworkError("Enrollment token is not valid", "authentication_error", 401)
        if _timestamp(record["expires_at"]) < datetime.now(timezone.utc):
            raise CaseworkError("Enrollment token has expired", "authentication_error", 401)

        token, salt = secrets.token_urlsafe(40), secrets.token_hex(16)
        endpoint_id = f"EP-{identifier()[:8].upper()}"
        capabilities = data.get("capabilities") or []
        if not isinstance(capabilities, list):
            raise CaseworkError("capabilities must be a list of source names")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO endpoints"
                " (id,name,hostname,platform,platform_release,agent_version,address,enrolled_at,"
                "  last_seen_at,status,token_salt,token_digest,capabilities,authorization_reference,"
                "  metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (endpoint_id, name, str(data.get("hostname", ""))[:255] or None,
                 str(data.get("platform", ""))[:64] or None,
                 str(data.get("platform_release", ""))[:120] or None,
                 str(data.get("agent_version", ""))[:64] or None,
                 str(data.get("address", ""))[:120] or None, now(), now(), ENROLLED, salt,
                 _hash_token(token, salt), encode(sorted({str(c).upper() for c in capabilities})),
                 record["authorization_reference"], encode({})))
            db.execute("UPDATE enrollment_tokens SET used_at=?,endpoint_id=? WHERE id=?",
                       (now(), endpoint_id, record["id"]))
            self._event(db, endpoint_id, "enrollment.completed",
                        detail={"capabilities": capabilities,
                                "platform": data.get("platform")})
            self.casework.audit("endpoint.enrolled", object_type="endpoint",
                                object_id=endpoint_id,
                                detail={"name": name, "platform": data.get("platform"),
                                        "authorization": record["authorization_reference"]}, db=db)
        return {"endpoint_id": endpoint_id, "endpoint_token": token, "name": name,
                "server_versions": versions(),
                "note": "This credential authenticates collection requests only."}

    def authenticate(self, endpoint_id: str, token: str):
        """Resolve a presented credential to an enrolled endpoint."""
        rows = self.store.rows("SELECT * FROM endpoints WHERE id=?", (endpoint_id or "",))
        if not rows or not isinstance(token, str) or not token:
            raise CaseworkError("Unknown endpoint credential", "authentication_error", 401)
        endpoint = rows[0]
        if endpoint["status"] == REVOKED:
            raise CaseworkError("This endpoint's authorization was revoked",
                                "authentication_error", 403)
        if not hmac.compare_digest(_hash_token(token, endpoint["token_salt"]),
                                   endpoint["token_digest"]):
            with self.store.transaction() as db:
                self._event(db, endpoint_id, "authentication.failed", outcome="failed")
            raise CaseworkError("Unknown endpoint credential", "authentication_error", 401)
        return endpoint

    def revoke(self, endpoint_id: str) -> dict:
        """Withdraw an endpoint's authorization.

        Queued work for it is abandoned rather than silently left pending, and
        evidence already collected from it is untouched: revoking authority for
        future collection does not retract what was lawfully collected before.
        """
        self.get_endpoint(endpoint_id)
        with self.store.transaction() as db:
            db.execute("UPDATE endpoints SET status=? WHERE id=?", (REVOKED, endpoint_id))
            abandoned = db.execute(
                "UPDATE endpoint_tasks SET status=?,completed_at=?,error=? "
                "WHERE endpoint_id=? AND status IN (?,?)",
                (ABANDONED, now(), encode({"reason": "endpoint authorization revoked"}),
                 endpoint_id, QUEUED, DISPATCHED)).rowcount
            self._event(db, endpoint_id, "authorization.revoked",
                        detail={"abandoned_tasks": abandoned})
            self.casework.audit("endpoint.revoked", object_type="endpoint", object_id=endpoint_id,
                                detail={"abandoned_tasks": abandoned}, db=db)
        return self.get_endpoint(endpoint_id)

    # --- endpoint state --------------------------------------------------
    def get_endpoint(self, endpoint_id: str) -> dict:
        rows = self.store.rows("SELECT * FROM endpoints WHERE id=?", (endpoint_id,))
        if not rows:
            raise CaseworkError("Endpoint not found", "not_found", 404)
        return self._present(rows[0])

    def _present(self, endpoint: dict) -> dict:
        record = dict(endpoint)
        # A credential digest is never part of a response.
        record.pop("token_salt", None)
        record.pop("token_digest", None)
        record["capabilities"] = json.loads(endpoint["capabilities"])
        record["metadata"] = json.loads(endpoint["metadata"])
        record["health"] = self._health(endpoint)
        counts = self.store.rows(
            "SELECT status, count(*) AS n FROM endpoint_tasks WHERE endpoint_id=? GROUP BY status",
            (endpoint["id"],))
        record["tasks"] = {row["status"]: row["n"] for row in counts}
        return record

    def _health(self, endpoint: dict) -> dict:
        if endpoint["status"] == REVOKED:
            return {"state": "revoked", "detail": "Authorization for this endpoint was withdrawn."}
        last = endpoint.get("last_seen_at")
        if not last:
            return {"state": "never_seen", "detail": "The endpoint has not contacted JOCKY."}
        age = (datetime.now(timezone.utc) - _timestamp(last)).total_seconds()
        if age > STALE_AFTER_SECONDS:
            return {"state": "stale", "seconds_since_heartbeat": int(age),
                    "detail": ("No heartbeat within the expected interval. This says JOCKY has not "
                               "heard from the endpoint, not that the machine is off.")}
        return {"state": "healthy", "seconds_since_heartbeat": int(age)}

    def list_endpoints(self) -> list:
        return [self._present(row) for row in
                self.store.rows("SELECT * FROM endpoints ORDER BY enrolled_at DESC")]

    def heartbeat(self, endpoint, data: dict) -> dict:
        """Record contact and report the endpoint's declared capabilities."""
        capabilities = data.get("capabilities")
        with self.store.transaction() as db:
            if isinstance(capabilities, list):
                db.execute("UPDATE endpoints SET capabilities=? WHERE id=?",
                           (encode(sorted({str(c).upper() for c in capabilities})), endpoint["id"]))
            db.execute(
                "UPDATE endpoints SET last_seen_at=?,status=?,agent_version=COALESCE(?,agent_version),"
                " platform=COALESCE(?,platform) WHERE id=?",
                (now(), ACTIVE, data.get("agent_version"), data.get("platform"), endpoint["id"]))
            self._event(db, endpoint["id"], "heartbeat")
        pending = self.store.rows(
            "SELECT count(*) AS n FROM endpoint_tasks WHERE endpoint_id=? AND status=? "
            "AND available_at<=?", (endpoint["id"], QUEUED, now()))[0]["n"]
        return {"acknowledged_at": now(), "pending_tasks": pending,
                "server_versions": versions(),
                "stale_after_seconds": STALE_AFTER_SECONDS}

    # --- task queue ------------------------------------------------------
    def dispatch_plan(self, *, plan: dict, endpoint_ids: list, investigation_id=None,
                      case_id=None) -> dict:
        """Queue one plan's ready tasks on each named endpoint.

        Every endpoint gets its own copy of every task, so the collection runs
        on all of them at once and one slow or absent machine never holds up the
        others. A source an endpoint has not declared is still queued: whether
        it can collect it is the endpoint's answer to give, and a refusal from
        the endpoint is recorded evidence of a gap rather than a silent skip
        here.
        """
        if not endpoint_ids:
            raise CaseworkError("Name at least one endpoint to collect from")
        ready = [task for task in plan.get("tasks", []) if task.get("status") == READY]
        if not ready:
            raise CaseworkError("This plan has no task any platform adapter can run")

        queued = []
        with self.store.transaction() as db:
            for endpoint_id in endpoint_ids:
                endpoint = self.get_endpoint(endpoint_id)
                if endpoint["status"] == REVOKED:
                    raise CaseworkError(f"{endpoint_id} is revoked and cannot be collected from",
                                        "conflict", 409)
                outstanding = db.execute(
                    "SELECT count(*) FROM endpoint_tasks WHERE endpoint_id=? AND status IN (?,?)",
                    (endpoint_id, QUEUED, DISPATCHED)).fetchone()[0]
                if outstanding + len(ready) > MAX_QUEUED_PER_ENDPOINT:
                    raise CaseworkError(
                        f"{endpoint_id} already has {outstanding} outstanding tasks; this build "
                        f"queues at most {MAX_QUEUED_PER_ENDPOINT} per endpoint.", "conflict", 409)
                for task in ready:
                    task_id = f"TASK-{identifier()[:10].upper()}"
                    db.execute(
                        "INSERT INTO endpoint_tasks"
                        " (id,endpoint_id,investigation_id,case_id,source,plan_task,created_at,"
                        "  available_at,max_attempts) VALUES (?,?,?,?,?,?,?,?,?)",
                        (task_id, endpoint_id, investigation_id, case_id, task["source"],
                         encode(task), now(), now(), MAX_ATTEMPTS))
                    queued.append({"task_id": task_id, "endpoint_id": endpoint_id,
                                   "source": task["source"]})
                self._event(db, endpoint_id, "tasks.queued",
                            detail={"count": len(ready),
                                    "sources": [task["source"] for task in ready]})
            self.casework.audit("collection.dispatched", object_type="plan",
                                object_id=investigation_id, case_id=case_id,
                                investigation_id=investigation_id,
                                detail={"endpoints": list(endpoint_ids),
                                        "sources": [task["source"] for task in ready],
                                        "task_count": len(queued)}, db=db)
        return {"queued": queued, "endpoint_count": len(endpoint_ids),
                "tasks_per_endpoint": len(ready),
                "unsupported": plan.get("unsupported", []),
                "note": ("Each task names a source and bounded options. No task carries a command "
                         "to run.")}

    def claim_tasks(self, endpoint, limit=4) -> dict:
        """Hand an endpoint the work it is due.

        The task an endpoint receives is the structured plan task and nothing
        else. It contains a source, bounded options and the arguments the
        program declared.
        """
        limit = max(1, min(int(limit), 16))
        moment = now()
        claimed = []
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT id,plan_task,attempts FROM endpoint_tasks WHERE endpoint_id=? AND status=?"
                " AND available_at<=? ORDER BY created_at LIMIT ?",
                (endpoint["id"], QUEUED, moment, limit)).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE endpoint_tasks SET status=?,dispatched_at=?,attempts=attempts+1"
                    " WHERE id=?", (DISPATCHED, moment, row[0]))
                task = json.loads(row[1])
                claimed.append({"task_id": row[0], "source": task["source"],
                                "collector": task.get("collector"),
                                "arguments": task.get("arguments", []),
                                "options": task.get("options", {}),
                                "attempt": row[2] + 1})
            if claimed:
                self._event(db, endpoint["id"], "tasks.dispatched",
                            detail={"task_ids": [task["task_id"] for task in claimed]})
        return {"tasks": claimed,
                "note": ("A task is a request for named forensic collection. It is not a command, "
                         "and an endpoint that has no collector for the named source should report "
                         "that rather than improvising.")}

    def submit_result(self, endpoint, task_id: str, data: dict) -> dict:
        """Accept one task's outcome from the endpoint that ran it.

        A failure is retried with backoff up to the task's attempt limit and is
        then abandoned with its last error preserved. An abandoned task is a
        recorded gap in the collection, which is what an investigator needs to
        see; it is never quietly dropped.
        """
        rows = self.store.rows("SELECT * FROM endpoint_tasks WHERE id=? AND endpoint_id=?",
                               (task_id, endpoint["id"]))
        if not rows:
            raise CaseworkError("Task not found for this endpoint", "not_found", 404)
        task = rows[0]
        if task["status"] in (SUCCEEDED, ABANDONED):
            raise CaseworkError("This task is already closed", "conflict", 409)

        succeeded = bool(data.get("ok", True)) and data.get("result") is not None
        result = data.get("result") if succeeded else None
        error = data.get("error") or (None if succeeded else {"code": "collector_failed",
                                                              "message": "No result was returned"})
        encoded = encode(result) if result is not None else None
        if encoded and len(encoded) > MAX_RESULT_BYTES:
            succeeded, encoded, result = False, None, None
            error = {"code": "result_too_large",
                     "message": f"Result exceeded the {MAX_RESULT_BYTES // (1024*1024)} MiB limit"}

        digest = hashlib.sha256(encoded.encode()).hexdigest() if encoded else None
        attempts, limit = task["attempts"], task["max_attempts"]
        if succeeded:
            status, available_at, completed = SUCCEEDED, task["available_at"], now()
        elif attempts >= limit:
            status, available_at, completed = ABANDONED, task["available_at"], now()
        else:
            delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
            status, available_at, completed = QUEUED, _future(delay), None

        with self.store.transaction() as db:
            db.execute(
                "UPDATE endpoint_tasks SET status=?,result=?,error=?,result_sha256=?,"
                " available_at=?,completed_at=? WHERE id=?",
                (status, encoded, encode(error) if error else None, digest, available_at,
                 completed, task_id))
            self._event(db, endpoint["id"], "task.result",
                        outcome="success" if succeeded else "failed",
                        detail={"task_id": task_id, "source": task["source"], "status": status,
                                "attempt": attempts, "sha256": digest})
            if status == ABANDONED:
                self.casework.audit(
                    "collection.task_abandoned", object_type="endpoint_task", object_id=task_id,
                    investigation_id=task["investigation_id"], case_id=task["case_id"],
                    outcome="failed",
                    detail={"endpoint": endpoint["id"], "source": task["source"],
                            "attempts": attempts, "error": error}, db=db)
        return {"task_id": task_id, "status": status, "attempts": attempts,
                "retry_after": None if status != QUEUED else available_at,
                "result_sha256": digest}

    def tasks(self, *, endpoint_id=None, investigation_id=None, limit=500) -> list:
        clauses, args = [], []
        for column, value in (("endpoint_id", endpoint_id), ("investigation_id", investigation_id)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        query = "SELECT * FROM endpoint_tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.store.rows(query + " ORDER BY created_at DESC LIMIT ?",
                               tuple(args) + (int(limit),))
        for row in rows:
            for key in ("plan_task", "result", "error"):
                row[key] = json.loads(row[key]) if row[key] else None
        return rows

    def sweep(self) -> dict:
        """Return work stranded by an endpoint that stopped mid-task.

        A dispatched task whose endpoint never reported back is put back on the
        queue once its backoff has elapsed, so a machine that was rebooted
        mid-collection resumes instead of leaving a silent hole.
        """
        stranded = self.store.rows(
            "SELECT id,attempts,max_attempts,dispatched_at FROM endpoint_tasks WHERE status=?",
            (DISPATCHED,))
        requeued, abandoned = 0, 0
        with self.store.transaction() as db:
            for task in stranded:
                age = (datetime.now(timezone.utc) - _timestamp(task["dispatched_at"])).total_seconds()
                if age < STALE_AFTER_SECONDS:
                    continue
                if task["attempts"] >= task["max_attempts"]:
                    db.execute(
                        "UPDATE endpoint_tasks SET status=?,completed_at=?,error=? WHERE id=?",
                        (ABANDONED, now(),
                         encode({"code": "endpoint_silent",
                                 "message": "The endpoint did not report a result for this task."}),
                         task["id"]))
                    abandoned += 1
                else:
                    db.execute("UPDATE endpoint_tasks SET status=?,available_at=? WHERE id=?",
                               (QUEUED, _future(RETRY_DELAYS[0]), task["id"]))
                    requeued += 1
        return {"requeued": requeued, "abandoned": abandoned, "examined": len(stranded)}
