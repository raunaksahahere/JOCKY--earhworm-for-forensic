# Windows validation status

Three different claims. They are kept apart because conflating them is how a
tool ends up described as working on a platform nobody has investigated a host
on.

| Claim | Status | Established by |
|-------|--------|----------------|
| **Windows application build** | **VALIDATED** | `.github/workflows/windows.yml` on `windows-latest` |
| **Windows packaged runtime** | **VALIDATED** | `packaging/windows/smoke_packaged.ps1` against the published artifact |
| **Windows GitHub release** | **PUBLISHED** | The portable archive and installer are Release assets |
| **Windows forensic host collection** | **NOT YET VALIDATED** | Needs a real investigated Windows host. Has not happened. |

## The run that established this

Release **0.8.1**, workflow run `34971374632`.

| | |
|--|--|
| Runner | Microsoft Windows Server 2025 Datacenter 10.0.26100 (build 26100) |
| Python | 3.12.10 |
| Flutter | 3.47.2 |
| Inno Setup | 6, from the runner image |
| Python tests | 865 passed, 8 skipped |
| Flutter tests | 172 passed |
| `flutter analyze` | clean |
| Portable archive | `jocky-workstation-0.8.1-windows-x64-portable.zip`, 41,654,968 bytes, 168 files |
| Installer | `jocky-workstation-0.8.1-windows-x64-setup.exe`, 32,004,324 bytes |
| SHA-256 (portable) | `6a38448833af05c615de727d2c8c61dda5a46205e788023925866a9c3d76277a` |

The eight skipped Python tests are the ones that exercise POSIX file mechanics —
mode bits, effective uid, birth time — plus the multi-host validation, which
needs a Docker daemon running Linux containers and so has none on a Windows
runner. Each states its reason.

The packaged smoke test, on the unpacked archive:

```
ok      jocky_client.exe / backend\JOCKY-backend.exe / backend\_internal
ok      grammar.lark, investigation.lark, driver_risk_reference.json,
        software_reference.json, bundled interpreter python3.dll
engine ready on port 55013 with a per-process token
health: ready, version 0.8.1, schema 7
the health reply carries the instance the bootstrap announced
an unauthenticated request is refused (401)
platform reported by the packaged engine: Windows
collection finished: completed
6 evidence records: SYSTEM INFO, PROCESSES, EXECUTION HISTORY, FILES,
                    ARTIFACTS, NETWORK
investigator report: 4 pages, and the advertised page count matched it
the engine shut down on request with exit code 0
```

The installer was then installed silently and put through the same test, and the
published asset was downloaded from the Releases page onto a fresh runner,
checked against that digest and run again.

## What is validated

The application **builds** on a GitHub-hosted Windows runner: the Python suite
runs, `flutter analyze` is clean, the Flutter tests pass, PyInstaller freezes
the engine, and `flutter build windows --release` produces a bundle with the
engine inside it.

The **packaged artifact runs**. This is the part that matters, and it is checked
against the final file rather than the build tree:

1. The unpacked archive carries `jocky_client.exe`, `backend\JOCKY-backend.exe`,
   `_internal`, both grammars, the driver reference, the recognition reference,
   the bundled fonts and a Python DLL. Every one of those is read at import
   time, so a missing one is not a degraded feature — the engine would not start.
2. The bundled engine is started over the same NDJSON bootstrap channel the
   desktop client uses, and announces a port, a per-process token and an
   instance id.
3. `/api/v1/health` answers ready, and the reply carries the instance the
   bootstrap announced.
4. An unauthenticated request is refused with 401.
5. A read-only collection runs — one file hashed, a one-hour window, the network
   collector — a report is issued, and the investigator PDF renders with the page
   count the engine advertised.
6. The engine shuts down on request with exit code 0.

The **installer** is compiled, installed silently, and the same smoke test is
run against the installed copy. The archive and the installer are two different
packagings and both are published, so both are tested.

The **published asset** is then downloaded from the Releases page onto a fresh
runner, checked byte-for-byte against the digest of the artifact that passed,
unpacked, and run through the smoke test again. The file on the Releases page is
therefore provably the file that passed.

## What is not validated

**That the Windows forensic collectors read what they should on an investigated
host.** An executable that launches is not a validated forensic collector.

Specifically unvalidated:

- Windows Security 4688 process-creation events
- Sysmon Event 1
- PowerShell operational log
- Windows Prefetch
- UserAssist
- Windows driver enumeration and signature checking
- Windows memory acquisition workflow against a real image

`analysis/execution_windows.py` is fixture-tested. The fixtures were written
from documented event formats, not captured from a host, and no output has been
compared against a Windows machine's real telemetry.

### What the runner does and does not tell us

A GitHub Windows runner is a real Windows machine, so the smoke test's
collection is a real collection — but of a CI runner, which has almost no
history and no investigative interest. It proves the collectors execute without
crashing. It does not establish that they find what a real host would hold, that
the event formats match what current Windows emits, or that the parsing is
correct against real data.

### Recognition has no Windows source

`analysis/recognition.py` reads a package database, a snap directory and a file
of vendor installation layouts. The first two do not exist on Windows, and the
layout descriptors are written for Linux and macOS installation shapes, so on a
Windows host recognition accounts for nothing.

It says so rather than failing: `SoftwareIndex` reports each source as
`NOT_AVAILABLE` with the path it looked in, and every artifact comes back
`recognized: false`. Nothing is silently assumed, and no artifact is described
as accounted-for when nothing accounted for it.

But the consequence is real: **the routine / recognized presentation category
does almost no work on Windows.** An investigator there sees the full list of
activity rather than the reduced one, because the machine's own records are not
being read to account for any of it. Closing that means reading the Windows
installed-programs registry and the side-by-side store, and validating the
result against a real host.

### The platform adapter is honest about this

`WindowsAdapter` carries `validated = False`, and `describe_plan` prints
`NOT VALIDATED ON A REAL HOST` for any Windows plan. Four of the six selectable
sources have no Windows adapter entry at all:

| Source | Windows |
|--------|---------|
| `NETWORK` | Adapter present |
| `MEMORY` | Adapter present |
| `BROWSER` | No collector in this build |
| `USB` | No collector in this build |
| `DRIVERS` | No collector in this build |
| `SERVICES` | No collector in this build |

`GET /api/v1/collection-sources` reports that per source with the reason, and
the client shows those sources disabled rather than letting an investigator
select one, watch the collection succeed and find no evidence in the report. A
silent gap is the one kind a forensic tool must never produce.

### Recognition has no Windows source

`analysis/recognition.py` accounts for a file from package ownership, snap
metadata and a small set of vendor installation layouts. The first two are Linux
sources and the third only fires on layouts that exist on Linux, so **on Windows
nothing is recognized**: every artifact comes back unaccounted for.

That is the honest result rather than a bug, and the report says which sources
it could read so the two are distinguishable:

```json
"sources": [
  {"source": "dpkg",             "status": "NOT_AVAILABLE"},
  {"source": "snap",             "status": "NOT_AVAILABLE"},
  {"source": "vendor reference", "status": "AVAILABLE"}
]
```

"Recognized nothing" and "had nothing to recognize with" are different
statements, and an investigator reading a Windows report needs the second.
Closing this would mean reading the Windows installer database, the uninstall
registry keys or Authenticode signatures — a new collector, and one that would
need validating against a host before it could be trusted.

## What would close the gap

1. Run a collection on a real Windows host with Sysmon and 4688 auditing
   enabled, and compare the normalized output against the host's own Event
   Viewer.
2. Do the same on a host with those sources *disabled*, and confirm JOCKY
   reports `NOT_ENABLED` rather than `NOT_AVAILABLE`.
3. Analyse a real Windows memory image through the Volatility3 path.
4. Write Windows adapter entries for the four missing sources, and validate each
   against a host.

Until at least the first of those has happened, this document says NOT YET
VALIDATED, and so does `docs/RequirementMatrix.md`.

## Running it

```bash
# On a tag, automatically. Manually from the Actions tab:
gh workflow run windows.yml -f publish=true
```

The workflow will not publish if the Flutter build fails, the freeze fails, a
required resource is missing, the packaged application does not launch,
readiness fails, the smoke test fails, the version and tag disagree, or the
artifact is empty. The release is created only after the artifact that would be
published has itself passed.
