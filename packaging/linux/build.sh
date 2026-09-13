#!/usr/bin/env bash
# Complete Linux release bundle: Flutter client plus the frozen engine.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="${JOCKY_BACKEND_DIST:-$ROOT/backend-dist/jocky-backend}"
BUNDLE="$ROOT/flutter_client/build/linux/x64/release/bundle"

[[ -x "$BACKEND/jocky-backend" && -d "$BACKEND/_internal" ]] || {
  echo "No complete engine at $BACKEND." >&2
  echo 'Build it first: .venv/bin/python scripts/build_backend.py' >&2
  exit 1
}

cd "$ROOT/flutter_client"
flutter pub get
flutter analyze
flutter test
JOCKY_BACKEND_DIST="$BACKEND" flutter build linux --release

# linux/CMakeLists.txt installs the engine into the bundle, so it survives the
# bundle wipe that every `flutter build linux` performs. Copy here only if that
# rule did not fire — a stale CMake cache can still hold an older engine path.
if [[ ! -x "$BUNDLE/backend/jocky-backend" ]]; then
  echo 'CMake did not install the engine; copying it directly.' >&2
  mkdir -p "$BUNDLE/backend"
  cp -a "$BACKEND/." "$BUNDLE/backend/"
fi

# Refuse to call an unrunnable bundle a release.
[[ -x "$BUNDLE/jocky_client" ]] || { echo 'Flutter executable missing' >&2; exit 1; }
[[ -x "$BUNDLE/backend/jocky-backend" ]] || { echo 'Engine executable missing from the bundle' >&2; exit 1; }
[[ -d "$BUNDLE/backend/_internal" ]] || { echo 'Engine runtime (_internal) missing from the bundle' >&2; exit 1; }

echo "Complete release bundle: $BUNDLE"
