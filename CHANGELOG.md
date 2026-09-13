# Changelog

All notable changes to JOCKY. Versions follow semantic versioning.

## 0.3.0 — 2026-09-13

Engine startup and release packaging. The application is now self-contained on
Linux: it locates and launches its own engine with no Python, no manually
started Flask, and no environment variable on the target machine.

### Fixed

- **The packaged Linux application could not reach its engine.** The release
  bundle contained no `backend/` directory at all, so `BackendSupervisor`
  resolved no executable and never launched anything. The engine is now
  installed into the bundle by `linux/CMakeLists.txt` and
  `windows/CMakeLists.txt`, so a plain `flutter build` produces a complete,
  runnable application. Previously the copy lived only in
  `packaging/linux/build.sh`, and the Flutter install step deletes the whole
  bundle directory on every build — so any copy made by a script was discarded
  by the next `flutter build linux`.
- **The reported cause was wrong.** The 15-second health poll ran without a
  bootstrap session, reported `No engine is listening on http://127.0.0.1:5000`
  against a port the engine never uses, and overwrote the real failure. The
  engine binds an OS-assigned port and mints a per-process token, both announced
  over the bootstrap channel, and every route including `/health` requires that
  token — so a probe without a session cannot succeed and no longer runs.
- **The developer fallback path pointed at a directory that never existed**
  (`<bundle>/../../../../desktop/backend-dist/`). Discovery now walks up from
  the executable to find `backend-dist/`, instead of counting `../` segments
  that differ between Linux and Windows.
- **System Status showed `127.0.0.1:5000` while the engine ran on another
  port.** The endpoint is now published from the bootstrap record when the
  engine reports ready, and reads "not assigned yet" before that.
- `waitForReady` replaced a precise exit reason with a generic timeout when the
  engine exited during startup. The recorded exit code and reason now survive.
- A stale bootstrap token was presented to a replacement engine after a restart.
  The session is cleared when the process it belongs to exits.

### Added

- Engine startup diagnostics name the actual cause: the engine's own
  `startup_error` message, its last stderr lines on an early exit, and a
  per-candidate verdict for discovery (`missing`, `is a directory`,
  `not executable`) instead of only "not found".
- A file present but without an execute bit is rejected during discovery rather
  than failing later with a less obvious error.
- `flutter_client/test/integration/packaged_engine_test.dart`: starts the real
  bundled engine through the real locator over real authenticated HTTP, and
  fails if the endpoint is still the placeholder port. Skips itself when no
  release bundle is present.
- `packaging/windows/build_portable.ps1` produces a portable Windows ZIP.
- `.github/workflows/ci.yml` runs the backend, smoke and client suites on every
  push. `.github/workflows/release.yml` builds the Debian package on
  `ubuntu-latest` and the installer and portable ZIP on `windows-latest`, on
  manual dispatch or a `v*` tag. Building never publishes by itself.

### Changed

- `packaging/linux/build.sh` and `packaging/windows/build.ps1` verify that the
  bundle they produced contains a runnable engine and its `_internal` runtime,
  and fail instead of shipping an incomplete bundle.
- `packaging/linux/build_deb.sh` verifies the built `.deb` actually carries the
  client, the engine and its runtime. It also clears the set-group-ID bit the
  build tree inherits, which `dpkg-deb` rejects on the control directory.
- The Inno Setup script takes its version from `JOCKY_VERSION`, writes to
  `build/windows/installer/`, names the engine as a required source so an
  installer cannot be built without it, and removes the application directory
  on uninstall while preserving operator data in `%LOCALAPPDATA%\JOCKY`.
- The `/health` fixture carries `instance_id`, which the real backend has always
  returned. Widget tests now start from a bootstrapped session, matching the
  only state in which the running application can reach the engine.

### Not verified in this release

Windows artifacts and both GitHub Actions workflows are configured but have not
been executed: this work was done on Linux, and Windows builds require a Windows
host. 1.0.0 is deferred until a Windows installer and the release workflow have
both been run and verified.

## 0.2.0

Flutter desktop client, backend service, SQLite-backed investigations, offline
PDF reporting and the initial packaging scripts.
