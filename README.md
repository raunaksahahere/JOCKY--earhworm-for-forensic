# JOCKY — Portable defensive forensic workstation

JOCKY runs on an **authorized investigation machine**. It collects documented
operating-system telemetry and artefacts, normalizes them into one evidence
vocabulary, correlates across sources and across hosts, ranks what deserves
attention, and produces a report that states its own limits as plainly as its
findings. Flutter is the desktop presentation; Python owns all forensic logic.

Choose **Analyze This Device** from Overview. Add file or directory sources
explicitly if needed, pick any additional evidence sources, then run collection.
Each source is its own step, so one that is unavailable becomes a named gap in
the report rather than a failed collection. Open **Case File** for cases,
registered evidence sources, authorized endpoints and the audit trail.

Software the machine's own records account for — anything a package manager,
snap or known installation layout placed — is marked as recognized and can be
filtered out of view, so a collection of two thousand records opens on the few
hundred that need a person.

What comes out is three documents, each doing one job:

| | Question | Typical |
|--|----------|---------|
| **Investigator report** | What do I need to know? | 8 pages |
| **Review brief** | Tell me about this one thing. | 1–2 pages |
| **Evidence package** | Show me everything. | everything collected |

A day of telemetry is around 1,700 records. Printing them made a 71-page report
whose first eight pages were the useful part, so the report is now those eight
pages and its length is set by how much there is to say rather than how much was
collected. Nothing was removed: the appendices are unchanged, available on
request, and carried inside the evidence package alongside a manifest and a
SHA-256 for every file.

### What it will not do

A process snapshot is not a historical timeline. A shell history line is not
proof a command ran. A filename indicator is a reason to look, not a verdict. A
hash compares bytes; it does not establish authenticity. A driver matching the
known-abused reference is present on this machine, which is not evidence it was
abused here. Recognized software is software the machine can account for, which
is not a finding that it is safe — and recognition never cancels a concern
signal, so a recognized interpreter running from a temporary directory with
remote content piped into it is still a lead.

JOCKY implements no bypass, injection, stealth, persistence or exploit feature.
It does not capture packets, read browser secrets, acquire memory, load or
modify drivers, or expose a remote shell. An enrolled endpoint receives a
forensic collection request naming a source — never a command. See
[docs/SecurityBoundaries.md](docs/SecurityBoundaries.md).

**Windows: the application is validated, the forensics are not.** The build and
the packaged runtime are checked on a Windows runner and the release is
published, but the Windows collectors are fixture-tested only — no host's real
telemetry has been compared against them. An executable that launches is not a
validated forensic collector. See [docs/WindowsValidation.md](docs/WindowsValidation.md).

## Try it

```sh
cd application
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/demo.py --output demo-output
```

Thirteen steps from a case to a finished evidence package, on this machine, in
about a minute. See [docs/Demo.md](docs/Demo.md).

## Documentation

| | |
|--|--|
| [Architecture](docs/Architecture.md) | Layering, the compilation chain, storage, the path off SQLite |
| [Recognition](docs/Recognition.md) | How JOCKY says what a file is, without being fooled by its name |
| [Review briefs](docs/ReviewBriefs.md) | One-page answers, the routine report, the evidence package |
| [Investigation language](docs/InvestigationLanguage.md) | Grammar, statements, compilation |
| [Evidence model](docs/EvidenceModel.md) | The vocabulary for what is known and what is not |
| [Security boundaries](docs/SecurityBoundaries.md) | What is absent, and where each boundary is enforced |
| [Endpoint protocol](docs/EndpointProtocol.md) | How an authorized machine is collected from |
| [App flow](docs/AppFlow.md) | Opening the app to holding a report |
| [Demo](docs/Demo.md) | The reproducible end-to-end run |
| [Requirement matrix](docs/RequirementMatrix.md) | Every requirement, what implements it, how far it is validated |
| [Testing](docs/Testing.md) | The suites and what they guard |
| [Rules](docs/Rules.md) | The constraints this is built under |
| [Tracker](docs/Tracker.md) | What is done, what is open, what broke |
| [Windows validation](docs/WindowsValidation.md) | What is validated on Windows, and what is not |

## Product source

```text
backend/             SQLite, application service, collectors, authenticated API/runtime, PDF
flutter_client/      Windows/Linux Flutter app, client services and widget/integration tests
analysis/            Existing read-only forensic analysis modules
compiler/            Command parser, investigation language, IR and execution plans
endpoint/            The agent that collects on another authorized machine
scenarios/           Deterministic synthetic lab scenarios, labelled throughout
communication/       Existing dispatcher and development compatibility API
crypto/              Non-destructive authenticated evidence export
reports/             Command report schema v1
assets/              Branding and licensed bundled Unicode fonts
contracts/           Versioned client contract, API/schema files and fixtures
packaging/           PyInstaller spec, Linux package and Windows installer build entry points
scripts/             Build, smoke-test and portable launch helpers
tests/               Python regression and workstation tests
dashboard/           Retained legacy React reference; not a runtime dependency
desktop-app/         Retained legacy Electron reference; not a runtime dependency
desktop/             Retained legacy packaging reference; not the production entry
agent/, sha256/      Retained native prototype/vendor code; not shipped or required
reference-repo/      Ignored reference material
docs/                Architecture, evidence model, security boundaries, requirement matrix
```

The product repository root is this directory (the local checkout is named
`application/`). Python packages remain in their working layout to preserve
imports. The native agent is a mock transport prototype, not a real collection
agent; psutil and the existing Python modules perform collection.

## Develop and test (Linux)

Build-host prerequisites: Python 3.12 with venv/pip, Flutter stable with Linux
desktop support, clang, CMake, Ninja, pkg-config, GTK3 development headers,
liblzma-dev, libstdc++ development libraries and dpkg-deb. Development tools are
not required on the target machine. On Debian/Ubuntu:

```sh
sudo apt-get install python3-venv python3-dev clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev libstdc++-12-dev dpkg-dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/build_backend.py
.venv/bin/python scripts/smoke_backend.py --executable backend-dist/jocky-backend/jocky-backend
cd flutter_client
flutter pub get
flutter analyze
flutter test
```

`JOCKY_BACKEND` is a development override only. A packaged build requires no
environment variable: `flutter build linux --release` installs the frozen engine
into the bundle (see `linux/CMakeLists.txt`), and the application resolves
`backend/jocky-backend` beside its own executable. Run `scripts/build_backend.py`
before building the client, or the bundle is produced with a CMake warning and
cannot start an engine.

Discovery order, relative to the running executable: `backend/<engine>`, then
`backend/<engine>/<engine>`, then `data/backend/<engine>`, then `backend-dist/`
in any ancestor directory (the developer layout). When none is runnable, System
Status names every location and why it was rejected.

Native desktop integration (from flutter_client):

```sh
JOCKY_TEST_BACKEND="$(realpath ../backend-dist/jocky-backend/jocky-backend)" flutter test integration_test/portable_workflow_test.dart -d linux
```

## Complete Linux bundle and Debian package

From the repository root:

```sh
.venv/bin/python scripts/build_backend.py
bash packaging/linux/build.sh
bash packaging/linux/build_deb.sh
```

Artifacts: `flutter_client/build/linux/x64/release/bundle/` and
`build/deb/jocky_0.8.1_amd64.deb` (override with `JOCKY_VERSION`). The bundle includes the Python interpreter,
modules, grammar, native Python dependencies and fonts. Node/Electron are absent.
The Debian package installs resources in `/opt/jocky-workstation`, a launcher,
desktop entry and icon; user data remains outside the installation directory.
Build on the oldest supported distribution: the current validation host uses
glibc 2.39, so this build does not establish compatibility with older systems.
The portable bundle still requires compatible GTK/glibc/system desktop libraries.

Explicit portable launch:

```sh
bash scripts/launch_portable.sh /absolute/release/bundle /absolute/portable/workspace
```

Settings also allows selecting Portable workspace or System application data
(restart required). Workspace selection does not move existing records. A previous
Flutter JSON record store can be explicitly imported in Settings; originals are
backed up and preserved. Environment `JOCKY_WORKSPACE` overrides saved preferences.
Close JOCKY before removing media. Filesystem locking, write permissions and
available space are required. Network filesystems are unsupported.

## Windows (requires a Windows build host)

Install Python 3.12, Flutter Windows toolchain, Visual Studio Desktop development
with C++, and Inno Setup 6 on the build host. From the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\build_backend.py
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
powershell -ExecutionPolicy Bypass -File packaging\windows\build_installer.ps1
powershell -ExecutionPolicy Bypass -File packaging\windows\build_portable.ps1
```

Artifacts: `build\windows\installer\jocky-workstation-<version>-windows-x64-setup.exe`
and `build\windows\jocky-workstation-<version>-windows-x64-portable.zip`.

## Release pipeline

`.github/workflows/ci.yml` runs the backend suite, the real-process smoke test
and the client suite on every push. `.github/workflows/release.yml` builds the
Debian package on `ubuntu-latest` and the installer and portable ZIP on
`windows-latest` — neither target can be cross-built, since PyInstaller freezes
for the OS it runs on. It is never triggered by an ordinary push: run it from
the Actions tab, or push a `v*` tag. A tag, or an explicit `publish` input,
creates a draft GitHub Release; building alone publishes nothing.

The installer includes the entire Flutter release directory and one-directory
backend. Portable launch is `packaging\windows\launch_portable.ps1 -Bundle
<absolute-bundle> -Workspace <absolute-workspace>`. Windows binaries and installer
have not been built on the Linux validation host. Release signing is separate.

## Historical execution evidence

"Analyze This Device" collects system information, a current process snapshot,
historical execution evidence, the artifacts that evidence names, correlation
findings and a merged timeline.

Every source is read-only and already present on the host. JOCKY never enables
auditing, installs a sensor, or changes any security or EDR setting. A source
that is switched off is reported `NOT_ENABLED`; one that needs privileges JOCKY
does not hold is reported `PERMISSION_DENIED`.

| Platform | Source | What a record proves |
| --- | --- | --- |
| Linux | systemd journal | the image was running when it logged — not when it started |
| Linux | shell history | a command was entered — not that it ran or succeeded |
| Linux | kernel audit log | the kernel recorded an execve (usually root-only, often off) |
| Linux | process accounting | the kernel recorded a process exit (off by default) |
| Linux | wtmp | a login session opened or closed — session context, not execution |
| Windows | Security 4688 | Windows recorded a process being created (audit policy is off by default) |
| Windows | Sysmon event 1 | process creation with parent image and hash (only if Sysmon is deployed) |
| Windows | PowerShell 4104 | a script block was compiled for execution |
| Windows | Prefetch | the named executable has run on this volume (metadata only; the body is not parsed) |
| Windows | UserAssist | the interactive user launched a program, with a run count and last-run time |

Collection is bounded everywhere: a 7-day default window (90-day maximum), 5000
events, 200 artifacts, one directory level with no recursion, 128 MiB per
digest. Command-line arguments are off by default, opt-in per investigation,
and redacted when enabled — a mitigation against credentials in arguments, not
a guarantee.

Findings are rule-based triage carrying severity, confidence and the evidence
they rest on. JOCKY does not call anything malware, does not infer execution
from a source that does not record it, and does not replace an unknown with a
guess.

## Reading an investigation

Every activity record carries the kind of evidence it is, and the report never
blurs the three together:

| Evidence kind | What it proves | Execution |
| --- | --- | --- |
| `EXECUTION_EVIDENCE` | a source recorded the process running | confirmed by the source |
| `COMMAND_HISTORY` | a command was entered into a shell | **not established** |
| `SESSION_EVENT` | a login session opened or closed | not applicable |

Where a source recorded the whole command, the whole command is what you see —
quoting, pipes, redirections and URLs preserved exactly. Where it recorded only
an image name, the report says so (`EXECUTABLE_ONLY`) instead of inventing
arguments. A reduced form exists alongside for searching and never replaces the
raw command.

Priority says where to look first, and is separate from what the evidence
supports — the two are allowed to disagree:

- **Priority 1 — investigate first**: several independent signals combine.
- **Priority 2 — review**: a concrete reason, evidence incomplete.
- **Priority 3 — informational**: routine system activity, and records whose
  only gap is a missing command line.

A missing command line is a collection limitation, never a suspicion. It is
recorded and shown, and contributes nothing to priority. Every priority carries
the named signals that produced it, so "priority 1" is always answerable with
"because of these three things".

Triage is three-way and is not a verdict:

- **POTENTIALLY HARMFUL** — the evidence gives a concrete reason to look, such
  as a remote fetch piped into an interpreter, or an image running from a
  writable temporary directory.
- **NOT SURE / NEEDS REVIEW** — recorded, but neither recognised as routine nor
  matched by a concern rule.
- **NOT HARMFUL ON AVAILABLE EVIDENCE** — nothing in what was collected stood
  out. This is not a statement that the activity was safe.

No single keyword classifies anything. `curl`, `python3`, `sudo`, `nc` and `ssh`
on their own are ordinary tools and land in NEEDS REVIEW.

The main PDF is roughly 8–15 pages: coverage, a triage table, the activity that
needs attention, then confirmed execution separated from typed commands and from
session activity. Detail lives in appendices. Nothing is deleted to achieve
that — SQLite and the JSON export hold every record, and findings cite stable
identifiers (EXEC-0001, CMD-0001, ART-0001) so any statement can be traced back.

## Contracts, storage and limits

See [client contract](contracts/CLIENT.md), [OpenAPI index](contracts/api.json),
[report schema](contracts/report.schema.json), and [command contract](COMMAND_CONTRACT.md).
SQLite schema1 includes metadata/settings, investigations, evidence, executions,
findings, reports, transitions and hash observations. Startup validates storage,
applies migrations, and marks unfinished work interrupted. Corruption is reported;
JOCKY never silently resets a database. API backup uses SQLite's online backup API.

Local HTTP requires generated per-launch authentication and instance identity.
The UI owns the backend via private NDJSON bootstrap and shuts it down on exit.
The legacy development Flask server is retained for regression/development only;
packaged builds use `backend.runtime` and Waitress. No browser CORS in production.

ENCRYPT FILE remains recognized by parser v1, but the former destructive fixed-key
operation has been removed. Safe export uses AES-GCM, streaming I/O and a supplied
recovery passphrase with scrypt; source evidence is untouched. See the contract
for export/recovery details. Never put recovery secrets in source/configuration.

## Provenance and release status

Existing source history and third-party notices are preserved. The inherited
codebase does not provide a verified project-wide license grant in this checkout.
No license has been invented or assigned. Resolve provenance/redistribution rights
before a public distributable release; this does not change implementation ownership
or remove third-party obligations. Bundled Noto font notices are in assets/fonts/NOTICE.

Legacy PRD/reference documents are context, not a claim of implemented capabilities.
Next release work: Windows validation, clean-host dependency tests, removable-media
and power-loss testing, real forensic validation, signing, and UI/report polish.
