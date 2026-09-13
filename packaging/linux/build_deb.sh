#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/flutter_client/build/linux/x64/release/bundle"
VERSION="${JOCKY_VERSION:-0.2.0}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid release version' >&2; exit 1; }
[[ -x "$BUNDLE/backend/jocky-backend" ]] || { echo 'Complete backend is missing' >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || { echo 'This release targets amd64' >&2; exit 1; }
STAGE="$ROOT/build/deb/jocky_${VERSION}_amd64"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/jocky-workstation" "$STAGE/usr/share/applications" "$STAGE/usr/bin" "$STAGE/usr/share/icons/hicolor/scalable/apps"
cp -a "$BUNDLE/." "$STAGE/opt/jocky-workstation/"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: jocky
Version: $VERSION
Architecture: amd64
Maintainer: JOCKY maintainers
Depends: libgtk-3-0, libblkid1, liblzma5, libstdc++6, libgcc-s1, libglib2.0-0, libsecret-1-0
Section: utils
Priority: optional
Description: Offline defensive forensic workstation
 Portable local observation, durable investigations and PDF reports.
CONTROL
cp "$ROOT/flutter_client/packaging/linux/jocky-workstation.desktop" "$STAGE/usr/share/applications/"
cp "$ROOT/assets/jocky.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/jocky-workstation.svg"
ln -sfn /opt/jocky-workstation/jocky_client "$STAGE/usr/bin/jocky-workstation"
chmod -R go-w "$STAGE"
dpkg-deb --build --root-owner-group "$STAGE"
