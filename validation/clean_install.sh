#!/usr/bin/env bash
#
# Install the built .deb in a clean environment and check it works there.
#
# A package that runs on the machine that built it has proved nothing: the build
# host has the interpreter, the libraries and the source tree. This installs it
# into a container that has none of those and drives the installed engine over
# its own bootstrap channel, which is the first time anything has run the
# packaged product the way a user would.
#
#   bash validation/clean_install.sh [path/to/jocky_x.y.z_amd64.deb]
set -euo pipefail

DEB="${1:-}"
if [[ -z "$DEB" ]]; then
    DEB="$(ls -t build/deb/jocky_*_amd64.deb 2>/dev/null | head -1 || true)"
fi
[[ -f "$DEB" ]] || { echo "No .deb found. Build one first."; exit 1; }

echo "=============================================================================="
echo "  JOCKY CLEAN-ENVIRONMENT INSTALL VALIDATION"
echo "=============================================================================="
echo
echo "  Package: $DEB ($(du -h "$DEB" | cut -f1))"

if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
    echo
    echo "  SKIPPED: docker is unavailable, so there is no clean environment to install into."
    echo "  Installing on the build host would prove nothing: it already has the"
    echo "  interpreter, the libraries and the source tree."
    exit 2
fi

# ubuntu:24.04 with no python3, no build tools and no JOCKY source.
CONTAINER="jocky-clean-install-$$"
cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "  Target : ubuntu:24.04, no Python, no source tree"
echo
docker run -d --name "$CONTAINER" --hostname jocky-clean ubuntu:24.04 sleep 900 >/dev/null

echo "-- 1. Confirm the environment is clean --------------------------------"
docker exec "$CONTAINER" bash -lc '
  if command -v python3 >/dev/null; then echo "   python3 IS present: $(python3 -V)"; \
  else echo "   python3 absent — the package must carry its own interpreter"; fi
  test ! -d /opt/jocky-workstation && echo "   no prior JOCKY installation"
'

echo
echo "-- 2. Install the package ---------------------------------------------"
docker cp "$DEB" "$CONTAINER:/tmp/jocky.deb" >/dev/null
docker exec "$CONTAINER" bash -lc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null 2>&1
  # dpkg first so any missing dependency is reported as the package declaring
  # it, then apt-get -f to satisfy them. A package whose dependencies cannot be
  # met on a clean Ubuntu is a packaging failure, not an environment problem.
  dpkg -i /tmp/jocky.deb >/dev/null 2>&1 || apt-get install -f -y -qq >/dev/null 2>&1
  dpkg -s jocky | sed -n "s/^\(Package\|Version\|Status\|Installed-Size\):/   &/p"
'

echo
echo "-- 3. Check what landed on disk ---------------------------------------"
docker exec "$CONTAINER" bash -lc '
  set -e
  for path in /opt/jocky-workstation/backend/jocky-backend \
              /opt/jocky-workstation/jocky_client \
              /usr/bin/jocky-workstation \
              /usr/share/applications/jocky-workstation.desktop; do
    test -e "$path" && echo "   ok      $path" || { echo "   MISSING $path"; exit 1; }
  done
  for data in compiler/investigation.lark compiler/grammar.lark \
              analysis/data/driver_risk_reference.json \
              analysis/data/software_reference.json; do
    found=$(find /opt/jocky-workstation -path "*/$data" | head -1)
    test -n "$found" && echo "   ok      $data" || { echo "   MISSING $data"; exit 1; }
  done
'

echo
echo "-- 4. Run the installed engine as a user would -------------------------"
# curl is installed here purely so the probe can talk to the engine. It is a
# test tool, not a JOCKY dependency: the package declares what it needs and curl
# is not among them, which is why the container did not already have it.
docker exec "$CONTAINER" bash -lc \
    'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl >/dev/null 2>&1'
docker cp validation/clean_probe.sh "$CONTAINER:/tmp/probe.sh" >/dev/null
docker exec "$CONTAINER" bash /tmp/probe.sh

echo "-- 5. Result -----------------------------------------------------------"
echo "   The package installs on a clean Ubuntu with its declared dependencies,"
echo "   carries its own interpreter and all data files, and the installed engine"
echo "   is present at the path the desktop entry points at."
echo
echo "   RESULT: PASSED"
