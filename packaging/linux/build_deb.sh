#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/flutter_client/build/linux/x64/release/bundle"
VERSION="${JOCKY_VERSION:-0.6.0}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid release version' >&2; exit 1; }
[[ -x "$BUNDLE/jocky_client" ]] || { echo 'Flutter executable is missing; build the release bundle first' >&2; exit 1; }
[[ -x "$BUNDLE/backend/jocky-backend" ]] || { echo 'Bundled engine is missing; build the release bundle first' >&2; exit 1; }
[[ -d "$BUNDLE/backend/_internal" ]] || { echo 'Bundled engine runtime (_internal) is missing' >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == amd64 ]] || { echo 'This release targets amd64' >&2; exit 1; }
STAGE="$ROOT/build/deb/jocky_${VERSION}_amd64"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/jocky-workstation" "$STAGE/usr/share/applications" "$STAGE/usr/bin" "$STAGE/usr/share/icons/hicolor/scalable/apps"
for SIZE in 16 24 32 48 64 128 256 512; do
  mkdir -p "$STAGE/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
done
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
for SIZE in 16 24 32 48 64 128 256 512; do
  cp "$ROOT/assets/icons/jocky-${SIZE}.png" "$STAGE/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/jocky-workstation.png"
done
ln -sfn /opt/jocky-workstation/jocky_client "$STAGE/usr/bin/jocky-workstation"
# The build tree is setgid and dpkg-deb rejects a control directory carrying
# that bit. GNU chmod preserves set-user-ID and set-group-ID on directories
# unless they are named explicitly, so neither 0755 nor g=rx clears them.
find "$STAGE" -type d -exec chmod u=rwx,g=rx,o=rx,u-s,g-s {} +
chmod -R go-w "$STAGE"
dpkg-deb --build --root-owner-group "$STAGE"

# The engine must be inside the package, executable, with its runtime. A .deb
# that installs a client with no engine is exactly the failure this guards.
PACKAGE="$STAGE.deb"
# Listed once into a variable: piping dpkg-deb into `grep -q` makes grep exit
# early, and the resulting SIGPIPE fails the whole pipeline under pipefail.
CONTENTS="$(dpkg-deb -c "$PACKAGE")"
grep -q '/opt/jocky-workstation/jocky_client$' <<<"$CONTENTS" || {
  echo 'Built package contains no client executable' >&2; exit 1; }
grep -q '/opt/jocky-workstation/backend/jocky-backend$' <<<"$CONTENTS" || {
  echo 'Built package contains no engine' >&2; exit 1; }
grep -q '/opt/jocky-workstation/backend/_internal/' <<<"$CONTENTS" || {
  echo 'Built package contains no engine runtime' >&2; exit 1; }
grep -q '/usr/share/icons/hicolor/256x256/apps/jocky-workstation.png$' <<<"$CONTENTS" || {
  echo 'Built package contains no application icon' >&2; exit 1; }
echo "Package: $PACKAGE"
