#!/usr/bin/env bash
# Launches JOCKY as a desktop application on macOS/Linux.
# First-time setup (only needed once): see README.md "Desktop App" section.
set -e
cd "$(dirname "$0")"
python3 desktop/launcher.py
