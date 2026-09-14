# Working on JOCKY

JOCKY is a defensive forensic workstation. The product is not the code — it is
the trustworthiness of what the code asserts. Read `docs/Rules.md` before
changing anything, and `docs/SecurityBoundaries.md` before adding a capability.

## The two questions

Before adding anything:

1. **Which verb is it?** The product does six things: observe, normalize,
   correlate, detect, explain, report. If the honest answer is a seventh, it
   does not belong here.
2. **What would it let a compromised control plane do?** If the answer is more
   than "request forensic collection", the design is wrong.

## Non-negotiable

- **Never claim more than the evidence supports.** A shell history line is not
  proof a command ran. A process snapshot is not history. A filename is not a
  verdict. Every finding must name its evidence and state what it cannot
  establish.
- **Never change the machine under examination.** No enabling a disabled source,
  no writing to a browser profile, no touching an evidence file.
- **Never destroy a prior record.** Supersede, do not overwrite. Record a
  mismatch, do not correct it. Keep a failed acquisition — it is a fact.
- **A program cannot run code.** `backend/plan_runner.REGISTRY` is the complete
  list of what an investigation can cause to happen, and a plan's collector path
  is *checked against* it, never imported from it.
- **An endpoint is never sent a command.** If you find yourself adding a field
  that an agent would evaluate, stop.
- **No credentials.** Command lines are off by default and redacted when on;
  browser secrets are never read; no real secret in any test or fixture.
- **Synthetic data is labelled everywhere it appears.**

## Where things live

```
analysis/    collectors, normalization, recognition, correlation, detection,
             briefs, search, case summary
             knows nothing about storage, HTTP or cases
compiler/    language -> AST -> IR -> plan
             knows nothing about collectors
backend/     API, services, storage — the only layer that writes
endpoint/    the agent for another authorized machine
scenarios/   synthetic lab data
```

The layering is what makes the synthetic scenarios honest: they push fabricated
data through exactly the functions a real collection uses, with no special path.
Keep it.

## Adding a collector

1. Write it in `analysis/`. Return a dictionary with `status`,
   `classification`, `complete`, `warnings`, a `limits` block naming what it
   does **not** do, and a ceiling constant.
2. Register it in `backend/plan_runner.REGISTRY` and `compiler/plan.py`.
3. Add its source to the grammar's `SOURCE` terminal.
4. Test it against the real host, not only a fixture.
5. Add a test asserting the limits it declares.

## Adding a recognition source

Recognition answers "what is this" from the machine's own records. Two rules:

1. **Never execute anything.** Reading a version with `--version` changes the
   machine under examination and runs a binary whose provenance is the open
   question. A test reads the module's source and fails on any execution path.
2. **A name is not evidence.** Every layer must rest on something a file's
   location alone cannot fake — package ownership, snap metadata, a marker file
   inside an installation. `/tmp/python3` must never be recognized as Python.

Recognition is context. It may lower a score; it may never cancel a concern
signal.

## Writing a brief section

A brief may only say what a stored record supports. "Downloaded by the browser"
needs a download record naming that exact path. Proximity in a timeline is not a
link. Where the evidence does not support the statement, say so and say what the
absence does not mean.

## Adding a detection

Every rule goes in `analysis/detections.RULES` with an id and a description, and
every finding it produces cites that rule. A finding that cannot state its
evidence, its rule and its confidence is not a finding.

## Changing the schema

Every migration needs a forward migration, a regression test, and — where
practical — a test that migrates a real existing database and counts the rows
that must survive. Bump `DATABASE_SCHEMA_VERSION`. Never rewrite data
destructively.

## Tests

```sh
.venv/bin/python -m pytest -q                       # 804
cd flutter_client && flutter test && flutter analyze # 158
python3 validation/multihost.py                     # real two-host validation
```

Tests here assert claims, not coverage. If you add a claim to a docstring, a
report or a UI string, add the test that keeps it true.

## Honesty in documentation

`docs/RequirementMatrix.md` carries a status for every requirement. Memory
analysis is fixture-only and says so. Everything Windows says WINDOWS READY /
NOT VALIDATED because no Windows host has run any of it.

Multi-host is validated on two containers, and the matrix states what containers
do not cover: they share a kernel, so kernel-level evidence across hosts is
still unvalidated. Never describe a container validation as two machines.

Do not mark something validated that has not been run. Do not describe Windows
as working. If you close one of those gaps, update the matrix and say what you
ran it on.

## Git

Commit as the repository owner. Messages explain why the change was needed, not
what the diff shows.
