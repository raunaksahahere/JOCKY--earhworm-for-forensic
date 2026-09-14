# Implementation plan

What was built in this pass, in the order it was built, and what remains.

## Order, and why

The pass was built bottom-up, because each layer is only testable once the one
below it exists.

**1. The language and the IR.** Everything downstream is a consumer of the IR,
so it went first. The grammar had to be fixed immediately: ignoring whitespace
globally made names swallow the following keyword, and eighteen statements
parsed as five.

**2. The collectors.** Six new ones — network, browser, USB, drivers, memory,
services. Each was exercised against the real host as it was written, because a
collector that has only ever seen a fixture is a collector that does not work.

**3. The schema.** Migrations 5 and 6, each verified against the actual
development database rather than only a synthetic one.

**4. Casework.** Cases, evidence sources, audit trail, notes.

**5. Plan execution.** The registry that binds a plan to code, and the wiring
into the collection pipeline. This is where the security boundary lives, so it
came before anything that would depend on it.

**6. The control plane and the agent.** The largest piece, and the one whose
design constraint — an endpoint is never sent a command — shaped everything
about it.

**7. Cross-source and cross-host correlation.** Written because the scenarios
demanded them: scenario B expected a removable-media thread and scenario C a
download-to-execution link, and neither existed.

**8. Scenarios and the demo.** Which is where three integration bugs surfaced.

**9. Tests.** Which is where three more did.

**10. The client.** The case file screen and the source picker.

**11. Documentation.**

## What the work found

Writing the scenarios and the tests was not verification of finished code; it
was where a third of the real bugs were found.

- Driver detections read `result` where the collector writes `risk_status`. No
  driver finding could ever have fired.
- Memory detections read the analysis tool's raw column names, not the
  normalized ones. Same outcome.
- Memory normalization did not recognise `ImageFileName`, the column
  Volatility3's `windows.pslist` actually emits, so every process from a Windows
  image would have normalized to a nameless record.
- A parent pid of 0 was turned into `None` by a truthiness check, losing every
  kernel root.
- Endpoints could not collect the core sources at all — the registry excluded
  them because the local collector owns them, which left a remote endpoint able
  to gather browser history but not processes.
- The agent claimed one batch of four and stopped, leaving two of six tasks for
  the next poll.
- Cross-host correlation paired USB root hubs by their PCI address and unrelated
  downloads by bare filename.

Each is now a test.

## The 0.8.0 pass

Built in this order, because each rests on the one before:

1. **Recognition**, since the presentation category, the routine report and
   half of every brief depend on knowing what a file is.
2. **Migration 7**, verified against the real development database.
3. **Briefs**, then the routine report, then their PDFs.
4. **Real multi-host validation**, which is the gap the matrix had been honest
   about for a release.
5. **The memory workflow**, around an analysis path that still has no real image.
6. **Search, assessments, the case summary, the evidence package manifest.**
7. **The storage-abstraction proof**, which turns a documented claim into a
   checked one.
8. Tests, client, documentation, release.

### What that found

- A configurable snap root that matching ignored, so the option silently did
  nothing.
- Investigations never stored their `case_id` at all. Migration 5 added the
  column and nothing ever wrote it, so every collection looked unattached
  however it was created — found only when the evidence-package manifest had no
  case to describe.
- Findings in the report payload carried no evidence references; the rows were
  stored in a separate table and never joined back, so a finding brief could
  cite nothing.
- Flutter assertions that matched the screen's raw-JSON debug dump rather than
  the list an investigator reads.

## What remains

**Windows validation.** Everything Windows is written and fixture-tested.
Nothing has run on a Windows host. This is the largest outstanding gap and no
amount of further code closes it — it needs a machine. It was explicitly
deferred for the 0.8.0 pass.

**A real memory image.** `analysis/memory.py` drives Volatility3, and that path
has never seen a real image.

**Two physical machines.** Multi-host is now validated on two containers with
separate filesystems, hostnames and process tables. Containers share a kernel,
so kernel-level evidence across hosts is still unvalidated.

**The move off SQLite.** Documented in `docs/Architecture.md`, deliberately not
performed. The abstraction that makes it cheap exists; doing it now without a
workload that needs it would be churn.

## What would come next

1. Run the Windows collectors on a Windows host and mark the matrix honestly.
2. Acquire a memory image in a lab and validate the Volatility3 path.
3. Enroll two genuinely separate machines and re-check what cross-host
   correlation surfaces when the answer is not trivially "everything".
4. Widen the detection ruleset — it is deliberately six rules, all explainable.
