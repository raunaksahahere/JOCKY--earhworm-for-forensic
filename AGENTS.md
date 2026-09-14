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
analysis/    collectors, normalization, correlation, detection
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
.venv/bin/python -m pytest -q                       # 708
cd flutter_client && flutter test && flutter analyze # 151
```

Tests here assert claims, not coverage. If you add a claim to a docstring, a
report or a UI string, add the test that keeps it true.

## Honesty in documentation

`docs/RequirementMatrix.md` carries a status for every requirement. Three are
fixture-only and say so. Everything Windows says WINDOWS READY / NOT VALIDATED
because no Windows host has run any of it.

Do not mark something validated that has not been run. Do not describe Windows
as working. If you close one of those gaps, update the matrix and say what you
ran it on.

## Git

Commit as the repository owner. Messages explain why the change was needed, not
what the diff shows.
