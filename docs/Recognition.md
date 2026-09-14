# Software recognition

An investigator should not have to research `/usr/bin/python3` because the raw
record is unfamiliar. But the reason JOCKY can say what that file is must be
evidence about *this* machine, not a list of names typed into the source.

A file called `python3` sitting in `/tmp` is not Python. A recognition layer
that can be fooled by naming a file is worse than none, because it reassures an
investigator about the one record that deserved their attention.

## What it reads

Four layers, strongest first. A weaker one never overrides a stronger one.

| Layer | Source | Confidence | Covers |
|-------|--------|-----------|--------|
| Package ownership | The package manager's record of which package owns this exact path | HIGH | The whole distribution — 421,000 paths from 2,784 packages on the development host |
| Snap metadata | `/snap/<name>/current/meta/snap.yaml` | HIGH | Everything installed as a snap |
| Vendor layout | `analysis/data/software_reference.json`, 14 descriptors | HIGH or MODERATE | Software installed outside any package manager |
| Trusted location | The path itself | LOW | Nothing — see below |

The first layer is why there is no large allowlist. The package manager already
knows what it installed and where, and reading its own records covers thousands
of programs with nothing hardcoded. The curated file exists only for software
that no package manager placed.

## A location is not an identity

A path in `/usr/bin` that no package claims is reported as
`trusted_system_location` with `recognized: false`. It is deliberately not a
recognition:

> The path is in /usr/bin, a directory the operating system manages, but no
> package claims it.
>
> This says where the file is, not what it is. A file placed in a system
> directory by something other than the package manager looks exactly like this,
> and which of the two it is matters.

That case is one worth telling an investigator about, not quietly resolving.

## Vendor layouts need a marker

Each entry in the curated file names a path fragment **and a marker file that
must exist inside the installation**:

```json
{
  "name": "Flutter SDK",
  "path_contains": "/flutter/",
  "marker": "bin/cache/flutter.version.json",
  "version_json_key": "frameworkVersion",
  "confidence": "HIGH"
}
```

`~/Downloads/flutter/bin/flutter` with nothing inside it is not Flutter.
`~/flutter/bin/flutter` with the version file present is, and the version comes
out of that file: **3.47.2**.

Adding an entry is the extension point. Keep it small; if a package manager
accounts for the software, the first layer already has it.

## Nothing is executed

Reading a version with `--version` is the obvious shortcut and is exactly what a
forensic tool must not do. It changes the machine under examination, and it runs
a binary whose provenance is the open question.

Versions come from metadata already on disk: the package database, a snap's
`snap.yaml`, a JSON key or a regular expression against a marker file.
`tests/test_recognition.py::test_recognition_runs_no_program` reads the module's
own source and fails if it contains any execution path at all.

Symbolic links are followed, because reading where a link points is a metadata
read. When the answer comes from the target, the result records `resolved_from`
so the step taken is visible.

## What a recognition says

```json
{
  "recognized": true,
  "recognized_name": "python3-minimal",
  "description": "minimal subset of the Python language",
  "category": "python",
  "version": "3.12.3-0ubuntu2.1",
  "confidence": "HIGH",
  "basis_codes": ["package_manager_ownership"],
  "recognition_basis": [
    "The package manager records that 'python3-minimal' owns exactly this path, at version 3.12.3-0ubuntu2.1.",
    "The package originates from Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>."
  ],
  "source": "dpkg package python3-minimal 3.12.3-0ubuntu2.1",
  "matched_evidence": ["ART-0001"],
  "limitations": [
    "Package ownership establishes which package placed a file at this path. It does not establish that the bytes now there are still the package's; compare the hash against the distribution to check that."
  ]
}
```

There is no safety score. Every result states its basis in a sentence, names its
source, cites the evidence it annotates, and states its own limits. A test
asserts the words "safe", "clean", "benign" and "trusted" appear nowhere in a
result.

## Recognition never suppresses a finding

Recognition is context. It lowers a record's triage score the way a system
location does, and it cannot cancel a concern signal:

| Record | Recognition | Score | Classification |
|--------|------------|-------|----------------|
| `python3 --version` from `/usr/bin/python3` | HIGH | −2 | Routine / recognized |
| `curl … \| /tmp/.cache/python3` | HIGH, same package | +3 | **Potentially harmful**, Priority 2 |

The second row is recognized software. It is still a lead, because it is running
from a world-writable directory with remote content piped into it. Weighing
those against each other is the whole reason triage scores rather than
short-circuits.

## The presentation category

Separate from the triage category, and about attention rather than evidence:

```
ROUTINE_RECOGNIZED   the machine's own records account for this and nothing
                     raised a concern
FOR_REVIEW           neither routine nor concerning; a person should read it
NEEDS_ATTENTION      a concern signal fired
```

On the development host this splits 709 activities into 405 routine, 299 for
review and 5 needing attention. The triage category behind each one is
unchanged; only how much of the investigator's attention it asks for.

One deliberate exception: a recognized **interpreter** whose arguments were not
recorded stays `FOR_REVIEW`. Recognizing `python3` says nothing about the script
it was handed, and that script is the only thing about it worth knowing.

## Where it runs

Once, during analysis, and the result is stored with the record
(`artifact_observations.recognition`, `execution_events.recognition`). The
package index — 421,000 paths — is built once per collection in about 0.45
seconds and reused. Recomputing it per screen render would re-read the package
database every time an investigator scrolled.
