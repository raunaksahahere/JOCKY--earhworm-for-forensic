"""Legacy developer launcher.

The production Windows application is built with Electron + a PyInstaller
backend and does not require Python or Node on the target machine.
Use desktop/build_windows.bat to create the fully bundled application.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if __name__ == "__main__":
    print("JOCKY production desktop build:")
    print("  1. Run desktop\\build_windows.bat")
    print("  2. Launch the generated JOCKY installer/portable EXE")
    print("\nFor development, run the Flask backend and dashboard separately.")
    input("\nPress Enter to close...")
