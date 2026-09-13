#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/flutter_client"
BACKEND="${JOCKY_BACKEND_DIST:-$ROOT/backend-dist/jocky-backend}"
[[ -x "$BACKEND/jocky-backend" && -d "$BACKEND/_internal" ]] || { echo 'Build the complete backend with .venv/bin/python scripts/build_backend.py first.' >&2; exit 1; }
flutter pub get
flutter analyze
flutter test
flutter build linux --release
BUNDLE="$ROOT/flutter_client/build/linux/x64/release/bundle"
mkdir -p "$BUNDLE/backend"
cp -a "$BACKEND/." "$BUNDLE/backend/"
echo "Complete release bundle: $BUNDLE"
