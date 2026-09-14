# Security boundaries

JOCKY is a defensive forensic tool. It observes, normalizes, correlates,
detects, explains and reports. It does not evade, inject, exploit or deploy.

This document states what the code will not do, and where in the code that is
enforced — because a boundary that lives only in a README is not a boundary.

## The shape of the thing

```
observe -> normalize -> correlate -> detect -> explain -> report
```

Every capability in the product is one of those six verbs. Where a forensic
technique has an offensive twin, JOCKY implements the observational half and
refuses the other.

## What is deliberately absent

None of the following exists anywhere in this codebase, and none of it should be
added:

- EDR or AV bypass, or any detection evasion
- Process injection, hollowing, or writing to another process's memory
- Exploit execution or payload delivery
- Credential theft or collection
- Persistence mechanisms
- Covert command and control, or domain fronting
- Bring-your-own-vulnerable-driver exploitation
- Malware deployment
- Disabling security controls
- Packet interception or covert network collection
- A generic remote shell, or arbitrary remote command execution

## Enforced boundaries, by module

### A program cannot run code

`backend/plan_runner.py` holds a fixed `REGISTRY` of ten collectors. That
registry is the complete list of what any investigation program can cause to
happen.

A plan task carries a dotted collector path. That path is **checked against** the
registry, never imported from it. Resolving it dynamically would turn the
investigation language into an arbitrary-code loader — precisely the property a
forensic tool must not have. A plan naming `os.system` is refused with a warning
and does not run.

Collectors receive named keyword arguments assembled per source. The option
dictionary is never passed through wholesale, so a value that reaches the IR
cannot reach a collector unless a human wrote the line that forwards it.

*Tests:* `tests/test_plan_execution.py` — a plan naming unknown code is refused;
a collector receives only named arguments.

### An endpoint is never sent a command

`backend/fleet.py`, `endpoint/agent.py`. An endpoint task has a source, bounded
options and the arguments the program declared. There is no command column in
`endpoint_tasks`, no command field on a task, and no route that carries one.

The agent does not trust the control plane. It looks the source up in **its own**
registry and runs what it finds there, or reports that it has no collector for
it. Someone who took over the control plane would gain the ability to request
forensic collection, not the ability to run programs on enrolled machines.

*Tests:* `tests/test_fleet.py` — a task never carries a command;
`tests/test_casework_api.py` — no endpoint route name contains command, exec,
shell, run or script; `tests/test_plan_execution.py` — the agent refuses a source
it has no collector for, and a task whose collector disagrees with its build.

### Authorization precedes collection

An endpoint exists only because an operator issued a single-use, expiring
enrollment token naming one machine. `authorization_reference` is **required**:
the warrant, ticket or written consent under which that machine may be collected
from is stored with the endpoint and shown in the UI.

Credentials are stored as salted digests, never in recoverable form. Revoking an
endpoint abandons its queued work but leaves evidence already collected
untouched — withdrawing future authority does not retract what was lawfully
collected before.

*Tests:* `tests/test_fleet.py` — authorization requires a stated authority; an
enrollment token is single-use; no credential appears in a response; an endpoint
credential does not open the investigator API.

### Memory analysis is read-only

`analysis/memory.py` reads an image the investigator supplies and returns
normalized process rows. `limits` records `read_only: true`, `memory_written:
false`, `code_executed: false`. JOCKY does not acquire memory, does not write to
an image, and does not execute anything found in one.

### Drivers are verified, never touched

`analysis/drivers.py` compares loaded drivers against a reference of drivers
known to have been abused. It does not load, unload, modify, disable or exploit
a driver, and it never executes kernel code. `limits.drivers_loaded_or_modified`
is `false`.

A match means the driver is present. The finding says so explicitly and says
that presence is not evidence it was abused on this host — several entries in
the reference are legitimate signed vendor drivers still in use for their
intended purpose.

### Network collection is metadata only

`analysis/network.py` reads the socket table, interfaces, routes and resolver
configuration. `limits.packet_capture` is `false`. No traffic is captured,
intercepted or inspected.

### Browser collection excludes secrets

`analysis/browser.py` reads history and download records. It copies the profile
database aside and opens the copy read-only, so a live browser is never
disturbed and the original is never written — asserted byte-for-byte in the
tests.

`limits` names each excluded class individually: `passwords_read`,
`cookies_read`, `tokens_read`, `form_data_read`, all `false`. Naming them
separately rather than under one flag is deliberate: a reader should be able to
check the specific thing they are worried about.

### Command lines are off by default and redacted when on

Collecting command-line arguments is opt-in per investigation. When enabled,
values matching common credential patterns are masked before storage
(`analysis/execution_model.py`, `redact_command_line`). This is a mitigation,
not a guarantee, and the UI says so where the option is offered.

### The local API is loopback-only

Every investigator route requires a per-process bearer token and an instance
header, and refuses a non-loopback peer and any browser `Origin`. The only
routes reachable from another machine are the four an endpoint agent needs, and
those authenticate with the endpoint's own credential and expose nothing but
forensic collection.

## Synthetic data

Everything `scenarios/` produces is fabricated. Every record carries
`synthetic: true` and a source beginning with `SYNTHETIC`; every scenario
carries a banner. A scenario result must never be presented as evidence about a
real machine, and a memory finding derived from a fixture is classified
`INFERRED` so it cannot be read as one.

No test or fixture in this repository contains a real secret.

## If you are extending this

Two questions before adding a capability:

1. Which of the six verbs is it? If the honest answer is a seventh, it does not
   belong here.
2. What would it let a compromised control plane do? If the answer is more than
   "request forensic collection", the design is wrong.
