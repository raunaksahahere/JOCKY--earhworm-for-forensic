# Review briefs and the routine report

Three documents, each doing one job the others should not have to.

| Document | For | Length |
|----------|-----|--------|
| **Investigator report** | The case: what needs attention and why | ~8 pages |
| **Review brief** | One subject: what is this and do I care | 1–2 pages |
| **Routine activity report** | Everything accounted for, grouped, for the record | ~4 pages |

Plus the **evidence package**, which holds all of it with a manifest.

## Review briefs

An investigator looking at `ART-0041` in a list of two thousand records has one
question — what is this, and do I care — and answering it used to mean reading
the evidence package.

```
POST /api/v1/investigations/<id>/briefs
{"subject_type": "artifact", "subject_id": "ART-0041"}
```

Subjects: `artifact`, `finding`, `activity` (addressed by an evidence identifier
such as `CMD-0001`), `lead`, `thread`.

### Structure

Always the same sections, in the same order, on screen and in the PDF:

```
Subject / Classification / Presentation / Priority
Execution:    CONFIRMED | NOT ESTABLISHED | CURRENT ONLY
Recognition:  RECOGNIZED | UNKNOWN | NOT APPLICABLE
Summary                       2-5 sentences
Why this was surfaced
Related activity
Related artifacts
Browser context
USB context
Network context
User and session context
Findings citing this
What is known
What is unknown
Collection limitations
Suggested investigator review
Evidence cited
```

### Every statement carries its evidence

The rule is that a brief may only say what a stored record supports.

- *"Downloaded by the browser"* requires a browser download record whose
  `target_path` is that exact path.
- *"Connected to a remote address"* requires a socket record whose owning
  process matches.
- Proximity in a timeline is **not** a link and never produces one.

Where the evidence does not support the link, the brief says so and says what
that absence does not mean:

> No socket record in this collection is owned by a process of this name. Note
> that a socket table is a snapshot; it cannot show a connection that had
> already closed.

### What is unknown

Filled in as carefully as the rest, because the gap is usually why the
investigator was looking. A recognized artifact's unknowns include:

> Whether the bytes are still the ones the package installed. That needs a
> comparison against a published hash.

### Output

| | |
|--|--|
| Screen | A dialog with the same sections as the PDF |
| PDF | `JOCKY_ReviewBrief_ART-0041.pdf`, 1–2 pages |
| JSON | The same structure, for a case management system |

```
POST /api/v1/investigations/<id>/briefs/export
{"subject_type": "artifact", "subject_id": "ART-0041", "format": "pdf"}
```

Every generated brief is stored in `review_briefs` with its evidence
identifiers, the versions that produced it, and an audit entry. A brief is part
of the record of the investigation.

Every brief carries:

> This brief summarises collected evidence about one subject. It is not a
> malware verdict and not a statement that the subject is safe or harmful.

### It reads stored evidence

A brief queries what the collection already wrote. Nothing is collected again,
no package database is re-read, and generating one on a finished investigation
does not touch the examined machine at all.

## The routine activity report

Deliberately a second document, never the primary one.

```
GET  /api/v1/investigations/<id>/routine
POST /api/v1/investigations/<id>/routine/export   {"detailed": false}
```

### Grouped, not listed

On the development host, 404 of 708 activities present as routine and collapse
into nine groups:

```
shell navigation and inspection     406 occurrences across 118 commands
version control                     353 occurrences across  97 commands
managed system services             188 occurrences
language package management         142 occurrences
package management                   86 occurrences
```

Printing eleven hundred identical version checks is not a record; it is a way of
ensuring nobody reads one. The evidence identifiers travel with each group, so
any individual record is still reachable, and `{"detailed": true}` prints every
command for anyone who wants them.

Recognized software gets its own table — name, instances, confidence — grouped
by what the software *is* rather than by the command that invoked it.

### The language

It is called **Routine / Recognized**. Never "Safe". Every copy carries:

> This report describes activity that did not produce a concern signal in the
> collected evidence. It is not a guarantee of safety. Recognition states what a
> file is, on the evidence of package metadata and installation layout; it does
> not establish that the file is harmless, and it does not establish that the
> bytes on disk are still the ones a package installed.

## The evidence package

```
POST /api/v1/investigations/<id>/package
```

A zip with a `MANIFEST.json` naming the case, the investigation, every version
that produced it, the endpoints the evidence came from, the registered sources
with their digests and integrity history, the collectors and their status, the
programs that drove the collection, and **the SHA-256 of every file as
written**.

```python
from backend.evidence_package import verify_package
verify_package(open("jocky-evidence-inv-1.zip", "rb").read())
# {'verified': True, 'files_checked': 15, ...}
```

A matching digest shows the file is the one JOCKY wrote. The manifest says
exactly that and no more:

> Each file's SHA-256 is recorded above as written. A matching digest shows the
> file is the one JOCKY wrote; it establishes nothing about the examined
> machine.

## The case summary

```
GET /api/v1/investigations/<id>/summary
```

Assembled from counts and stored records, with the evidence identifiers behind
each sentence, and written to `report_narrative` so the part people actually
read can be audited against the records it came from.

It never reaches for a reassuring phrase:

> No priority-1 activity was identified. That is a statement about what was
> collected and how it ranked, not a finding that the machine is clean.

## Investigator assessments

```
POST /api/v1/investigations/<id>/assessments
{"subject_type": "activity", "subject_id": "CMD-0001",
 "assessment": "ACCEPT_AS_ROUTINE", "note": "Our own deployment script."}
```

`ACCEPT_AS_ROUTINE`, `KEEP_FOR_REVIEW`, `MARK_AS_RELEVANT`.

Stored **beside** the machine's classification, never over it, with the
machine's conclusion and priority copied in as they stood when the assessment
was made — so a later re-analysis cannot make it look as though the investigator
disagreed with something they never saw. Assessments accumulate; an earlier
judgement is part of the record too.
