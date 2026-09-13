# JOCKY — Portable defensive forensic workstation

JOCKY runs on an **authorized investigation machine**, collects supported local
observations, and stores investigations in SQLite for offline review and PDF/JSON
export. Flutter is the desktop presentation; Python owns all forensic logic.

Choose **Analyze This Device** from Overview. Add file/directory sources explicitly
if needed, then run collection. Stages and collection limitations are displayed.
Open Previous investigations to review saved device/process/file observations,
findings, evidence references and reports. Export PDF without rerunning the engine.

Current process snapshots are not historical execution timelines. No historical
OS execution-log collector is included. Filename indicators are review prompts,
not malware verdicts. Hashes compare bytes; they do not establish authenticity.
JOCKY implements no bypass, injection, stealth, persistence or exploit features.

## Product source

```text
backend/             SQLite, application service, collectors, authenticated API/runtime, PDF
flutter_client/      Windows/Linux Flutter app, client services and widget/integration tests
analysis/            Existing read-only forensic analysis modules
compiler/            Existing Lark parser and command contract v1
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
docs/                Ignored working documents
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

For development UI launch, set `JOCKY_BACKEND` to the absolute frozen backend
executable path and run `flutter run -d linux` inside flutter_client. Production
launch finds `backend/jocky-backend` beside the Flutter binary.

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
`build/deb/jocky_0.2.0_amd64.deb`. The bundle includes the Python interpreter,
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
```

The installer includes the entire Flutter release directory and one-directory
backend. Portable launch is `packaging\windows\launch_portable.ps1 -Bundle
<absolute-bundle> -Workspace <absolute-workspace>`. Windows binaries and installer
have not been built on the Linux validation host. Release signing is separate.

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
