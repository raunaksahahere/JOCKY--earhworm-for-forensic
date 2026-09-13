# Packaging the JOCKY Flutter workstation

## What ships

A release bundle contains the Flutter client and, when available, the packaged
Python engine:

```text
<bundle>/
  jocky_client[.exe]      Flutter desktop client
  data/                   Flutter assets and ICU data
  lib/ or *.dll           Flutter engine and plugin libraries
  backend/
    jocky-backend         Linux  — PyInstaller output
    JOCKY-backend.exe     Windows — PyInstaller output
```

`BackendSupervisor` resolves `backend/<engine>` relative to the running
executable, launches it with `JOCKY_HOST` / `JOCKY_PORT`, and polls
`GET /health` until it answers. When the engine is absent the client starts
anyway and reports it as not found — it never pretends to be connected.

The engine binary itself is produced by the existing Python packaging in
`../desktop/`; this project does not rebuild it.

## Linux

```bash
scripts/build_linux.sh            # analyze, test, build, bundle the engine
scripts/build_deb.sh              # assemble a .deb from that bundle
```

`build_deb.sh` needs `dpkg-deb`. Set `JOCKY_VERSION` and `JOCKY_ARCH` to
override the defaults (`0.1.0`, `amd64`), and `JOCKY_BACKEND_DIST` to point at
a PyInstaller engine elsewhere.

Installed layout: the bundle in `/opt/jocky-workstation`, a launcher symlink at
`/usr/bin/jocky-workstation`, and a desktop entry.

## Windows

```powershell
scripts\build_windows.ps1         # analyze, test, build, bundle the engine
```

Then compile `packaging\windows\jocky-workstation.iss` with Inno Setup to
produce an installer. Both steps require a Windows machine with the Flutter
Windows toolchain (Visual Studio, "Desktop development with C++").

## Validation status

| Step | Status |
| --- | --- |
| `flutter build linux --release` | executed on Linux, succeeded |
| `scripts/build_deb.sh` | executed on Linux, produced `jocky-workstation_0.1.0_amd64.deb` (8.5 MB, engine not bundled — no PyInstaller output was present) |
| `flutter build windows --release` | **not executed** — needs a Windows host |
| Inno Setup installer | **not executed** — needs a Windows host with Inno Setup |

Do not treat the unexecuted rows as passing. They are configuration, not
validated builds.
