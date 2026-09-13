# JOCKY Windows Desktop Packaging

## Goal

The production JOCKY Windows application is a fully bundled desktop runtime.
The target machine does **not** need Python, Node.js, npm, Vite, or the source tree.

## Build machine requirements

- Windows 10/11
- Python 3.10+
- Node.js/npm
- Internet access for first-time dependency installation

These are build-time requirements only.

## Build

Run from the JOCKY project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\desktop\build_windows.ps1
```

The script:

1. installs Python dependencies and PyInstaller
2. builds `dashboard` as a static Vite production bundle
3. freezes the Flask backend into `JOCKY-backend.exe`
4. installs Electron packaging dependencies
5. creates an NSIS installer and a portable EXE

Output:

```text
desktop-app\release\
```

## Runtime

The packaged app launches Electron, starts the bundled backend silently, waits for `/health`, and opens the production frontend from local application resources.

No development server is used at runtime.
