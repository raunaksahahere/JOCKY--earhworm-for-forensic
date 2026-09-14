# Endpoint protocol

How the control plane and an enrolled machine talk, and why the protocol is
shaped the way it is.

## The premise

An agent that can be told to run commands is a remote administration tool. One
that can only be asked for named forensic collection is a forensic tool. The
difference is the entire reason this agent can reasonably be deployed on a
machine belonging to someone else, so the protocol is built to make the second
thing true and the first thing impossible.

There is no command field anywhere in the protocol. A task names a **source**.

## Authorization

Before anything else, an operator issues an enrollment token:

```
POST /api/v1/endpoints/authorize
{ "endpoint_name": "lab-1",
  "authorization_reference": "WARRANT-2026/11" }
```

`authorization_reference` is required. Collecting from a machine should carry a
record of who permitted it, and that record is stored with the endpoint for the
life of the enrollment.

The response contains the token **once**. It is single-use, expires in 60
minutes, and is stored server-side only as a salted digest.

## Enrollment

```
POST /api/v1/endpoints/enroll        (no local session required)
{ "enrollment_token": "...", "endpoint_name": "lab-1",
  "hostname": "...", "platform": "Linux", "platform_release": "...",
  "agent_version": "...", "capabilities": ["NETWORK", "USB", ...] }
```

The endpoint declares what it can collect. The server issues a long-lived
credential, again stored only as a salted digest, and marks the enrollment token
used. Replaying it fails.

The agent writes the credential to `~/.config/jocky/endpoint.json` with mode
`0600`.

### On the digest

These credentials are 40 bytes of generated entropy, not passwords. The digest
is a single salted SHA-256 rather than a stretched hash: there is no dictionary
to slow down, and an endpoint presents its credential on every poll, where a
deliberately slow hash would be a self-inflicted denial of service rather than a
defence.

## The four endpoint-facing routes

Every one authenticates with `Authorization: Bearer <endpoint token>` and
`X-Jocky-Endpoint: <endpoint id>`.

| Route | Purpose |
|-------|---------|
| `POST /api/v1/endpoints/enroll` | Redeem a token (unauthenticated by design) |
| `POST /api/v1/endpoints/heartbeat` | Report contact and capabilities |
| `POST /api/v1/endpoints/tasks/claim` | Take work that is due |
| `POST /api/v1/endpoints/tasks/<id>/result` | Return one task's outcome |

These are the only routes reachable from another machine. An endpoint credential
is refused on every investigator route — an endpoint cannot read the case file
it collects for.

## What a task looks like

```json
{ "task_id": "TASK-...",
  "source": "NETWORK",
  "collector": "analysis.network.collect_network",
  "arguments": [],
  "options": {"window_hours": 24},
  "attempt": 1 }
```

`collector` is present for the record and for a consistency check. The agent
looks `source` up in **its own** registry; if the task's `collector` disagrees
with what this build provides, the task is refused rather than run. The agent
executes its own code or nothing.

An agent with no collector for the named source reports that:

```json
{ "ok": false,
  "error": {"code": "source_unsupported",
            "message": "This endpoint has no collector for X. Nothing was
                        collected and nothing is claimed about it."} }
```

A refusal is recorded evidence of a gap, which is what an investigator needs to
see. It is never a silent skip.

## Dispatch

```
POST /api/v1/collections/dispatch
{ "program": "<JOCKY investigation language>",
  "endpoints": ["EP-...", "EP-..."],
  "case_id": "CASE-..." }
```

The program is compiled to IR and then to a plan. Every endpoint receives its
own copy of every ready task, so the collection runs on all of them at once and
one slow or absent machine never holds up the others.

## Results, retry and abandonment

A result is hashed on arrival and stored with its digest. Failures retry with
backoff (30s, 120s, 600s) up to three attempts, then the task is **abandoned**
with its last error preserved. An abandoned task is a recorded gap in the
collection; it is never quietly dropped.

A result larger than 16 MiB is rejected rather than truncated — a silently
shortened result is evidence that is quietly wrong.

A dispatched task whose endpoint went silent returns to the queue once its
backoff elapses (`POST /api/v1/endpoint-tasks/sweep`), so a machine rebooted
mid-collection resumes instead of leaving a hole.

## Health

`healthy`, `stale`, `never_seen` or `revoked`. `stale` means JOCKY has not heard
from the endpoint within 300 seconds. It does **not** mean the machine is off,
and the API says so in the health detail — an investigator should not read an
inference into a connectivity fact.

## Revocation

```
POST /api/v1/endpoints/<id>/revoke
```

The endpoint can no longer authenticate. Its queued and dispatched tasks are
abandoned with a stated reason. Evidence it already returned is untouched.

## Limits

| | |
|--|--|
| Endpoints | 500 |
| Outstanding tasks per endpoint | 64 |
| Task attempts | 3 |
| Result size | 16 MiB |
| Claim batch | 16 |
| Agent task timeout | 900s |
| Stale after | 300s |
