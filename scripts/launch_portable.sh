#!/usr/bin/env bash
# Explicit workspace selection; never infer writable removable storage.
set -euo pipefail
if [[ $# -ne 2 ]]; then echo 'Usage: launch_portable.sh /absolute/bundle /absolute/workspace' >&2; exit 2; fi
export JOCKY_WORKSPACE="$2"
exec "$1/jocky_client"
