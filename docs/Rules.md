# Rules

The constraints this project is built under. They are not style preferences;
each one exists because violating it would make the output untrustworthy.

## Forensic honesty

1. **Never claim more than the evidence supports.** A shell history line is not
   proof a command ran. A process snapshot is not history. A filename is not a
   verdict.
2. **State what could not be collected, as prominently as what was.** A report
   that lists findings but hides gaps invites a false conclusion.
3. **Distinguish observation from inference, always.** Every event records, per
   field, whether the value was observed, derived or unavailable.
4. **Never change the machine under examination.** No enabling a disabled
   source, no writing to a browser profile, no touching an evidence file.
5. **Never destroy a prior record.** Supersede, do not overwrite. Record a
   mismatch, do not correct it. Keep a failed acquisition.
6. **Synthetic data is labelled everywhere it appears** and may never be
   presented as host evidence.

## Security

7. **Observe, normalize, correlate, detect, explain, report.** If a capability
   is not one of those six verbs, it does not belong here.
8. **A program cannot run code.** The collector registry is the complete list of
   what an investigation can cause to happen.
9. **An endpoint is never sent a command.** It receives a source name. The agent
   runs its own code or nothing.
10. **Authorization precedes collection**, and the authority is recorded.
11. **Never collect credentials.** Command lines are off by default and redacted
    when enabled; browser secrets are never read.
12. **No real secret in any test or fixture.**

See `docs/SecurityBoundaries.md` for what is explicitly absent and where each
boundary is enforced.

## Engineering

13. **Every schema change is a forward migration with a regression test**, and
    where practical a test against a real existing database.
14. **Every collector declares a ceiling.** Unbounded collection on a busy host
    is an unfinished collection.
15. **One failing collector degrades a collection, never fails it.** The failure
    is recorded as evidence.
16. **Versions are recorded with every result** — application, API, report
    schema, database schema, IR, plan, ruleset.
17. **The client hardcodes nothing the engine owns** — not the command
    reference, not the source list.
18. **Comments explain why, not what.** The code says what it does.

## Delivery

19. **Do not claim Windows works.** It has never been run on Windows. Everything
    Windows is labelled WINDOWS READY / NOT VALIDATED.
20. **Do not claim anything complete without validation.** `docs/RequirementMatrix.md`
    carries an honest status for every requirement, including the three that are
    fixture-only.
