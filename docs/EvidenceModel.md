# Evidence model

The vocabulary JOCKY uses to say what it knows, how it knows it, and what it
does not know.

## The first distinction

```
HISTORICAL_EVIDENCE   a source recorded this happening in the past
CURRENT_OBSERVATION   JOCKY saw this at collection time
INFERRED              JOCKY worked this out from other records
UNAVAILABLE           this could not be collected
```

A process snapshot is a `CURRENT_OBSERVATION`: it describes the moment of
collection and establishes nothing about what ran before it. Conflating that
with historical evidence is the most common way a forensic report ends up
asserting something it cannot support.

## Evidence kinds

```
EXECUTION_EVIDENCE     a source recorded a program running
COMMAND_HISTORY        a shell recorded a command being entered
SESSION_EVENT          a login, logout or device attach
PROCESS_SNAPSHOT       a process present at collection time
ARTIFACT_OBSERVATION   a file observed and hashed
FINDING                JOCKY's own statement about the above
```

`COMMAND_HISTORY` and `EXECUTION_EVIDENCE` are kept rigorously apart. A shell
history line proves someone typed something. It does not prove it ran, it does
not prove it succeeded, and it carries no timestamp on most systems. Every event
carries `execution_confirmed`, and the report never presents a typed command as
a program that ran.

## Source status

```
AVAILABLE          read successfully
NOT_AVAILABLE      the source does not exist on this system
NOT_ENABLED        it exists but is switched off
PERMISSION_DENIED  it exists and is enabled, but is not readable as this user
NOT_COLLECTED      it was not requested
```

JOCKY never enables a disabled source. Turning on audit logging to read it would
change the machine under examination.

The distinction between `NOT_AVAILABLE` and `NOT_ENABLED` matters: the first
says the evidence never existed, the second says it exists somewhere else and
this machine chose not to keep it.

## Command reconstruction

```
EXACT            the full command line as the source recorded it
PARTIAL          some of it; what is missing is stated
EXECUTABLE_ONLY  the program, with no arguments
NOT_AVAILABLE    nothing
```

with a strength of `STRONG`, `MODERATE` or `WEAK`.

A missing argument list is a **collection limitation**, not a suspicion. A
report that treats "we could not see the arguments" as a reason for concern
generates one alert per process on a normal machine, which is the same as
generating none.

## Field provenance

Every event records, per field, whether the value was `OBSERVED` in the source
record, `DERIVED` by JOCKY, or `UNAVAILABLE`. A reader never has to guess
whether a missing key means "no" or "not looked at".

## Triage and priority

Two separate judgements, deliberately not merged:

**Triage** — what the evidence supports:

```
POTENTIALLY_HARMFUL
NOT_HARMFUL_ON_AVAILABLE_EVIDENCE
NEEDS_REVIEW
```

**Priority** — where attention is worth spending:

```
PRIORITY_1  investigate first
PRIORITY_2  review
PRIORITY_3  informational
```

Priority comes from a deterministic weighted signal score. A finding only
reaches Priority 1 when corroborated — the same conclusion supported by an
execution record *and* an artifact, rather than one observation alone.

`NOT_HARMFUL_ON_AVAILABLE_EVIDENCE` is not "safe". It says nothing in what was
collected suggests harm, which is a statement about the evidence, not about the
activity.

## Recognition

What a file is, on the evidence of the machine's own records — package
ownership, snap metadata, a vendor installation layout. Separate from every
judgement above, because "what is this" and "does this matter" are different
questions and answering the first must not be allowed to answer the second.

```
recognized: true/false
confidence: HIGH | MODERATE | LOW | NONE
basis_codes: package_manager_ownership | snap_metadata | vendor_layout
             | trusted_system_location
```

`trusted_system_location` is deliberately **not** a recognition. A file in
`/usr/bin` that no package claims is reported as being in a place, not as being
a thing, because which of those two it is matters. See `docs/Recognition.md`.

## Presentation

How much of the investigator's attention a record asks for, kept apart from what
the evidence supports:

```
ROUTINE_RECOGNIZED   the machine's own records account for it and nothing
                     raised a concern
FOR_REVIEW           neither routine nor concerning
NEEDS_ATTENTION      a concern signal fired
```

Changing a record's presentation never changes its triage category. Recognition
lowers the score the way a system location does and cannot cancel a concern
signal.

## Identifiers

```
EXEC-nnnn   execution evidence
CMD-nnnn    command history
SESS-nnnn   session event
ART-nnnn    artifact
F-nnnn      finding
LEAD-nnn    lead
THREAD-nnn  activity thread
```

Stable within one investigation. Findings cite them, the report prints them, and
an investigator uses them to find the underlying record in the database.

## Evidence sources

A file brought into a case — an image, a log export, anything.

```
Acquisition:  REGISTERED -> HASHED | FAILED
Verification: UNVERIFIED | VERIFIED | MISMATCH | MISSING
```

Registering reads the file to compute its digest and never writes to it, moves
it or renames it. Registering the same bytes again creates a new row that
records what it **supersedes**; the original acquisition always survives. A
re-verification that finds different bytes records `MISMATCH` and keeps the
original digest — the source can no longer be treated as the bytes first
registered, and saying so is the point.

## What is not evidence

The **audit trail** records what JOCKY and the investigator did. **Notes**
record what the investigator thinks. **Assessments** record an investigator's
judgement about one record. **Review briefs** and the **case summary** are
JOCKY's own prose about the evidence.

None of these is evidence about the examined host, and all are stored in
separate tables from everything above, because an interpretation that ends up
looking like an observation is worse than no interpretation at all.

An assessment stores the machine's classification and priority **as they stood
when it was made**, alongside the investigator's own. The machine's conclusion
is never edited. A record that lost the original when an investigator disagreed
would be a record of the disagreement's outcome rather than of the disagreement.

Each sentence of the case summary is stored in `report_narrative` with the
evidence identifiers behind it, so the generated prose can be audited against
the records it was assembled from.

## Memory evidence

An image is registered as an evidence source, hashed, and re-verified
immediately before analysis. A changed image is refused: attributing findings to
bytes that are no longer there is what this exists to prevent.

Each normalized memory record carries the plugin that produced it and whether
the value was read directly from the image or derived from structures in it —
the second depends on the tool's symbol table matching the kernel that produced
the image, which is worth a reader knowing.

## Synthetic data

Every record from `scenarios/` carries `synthetic: true` and a source beginning
with `SYNTHETIC`. A memory finding derived from a fixture is classified
`INFERRED` rather than `HISTORICAL_EVIDENCE`, so it cannot be read as evidence
about a host even if the label is missed.

## Limitations are reported as prominently as findings

Every report states what could not be read, which sources were unavailable and
why, where collection was truncated, and what the evidence cannot establish. An
investigator needs to know the shape of the hole as much as the shape of what
was found.
