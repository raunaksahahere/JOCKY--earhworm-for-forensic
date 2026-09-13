# JOCKY — Fully Bundled Windows Runtime

## What this solves

The final JOCKY Windows application does **not** require Python, Node.js, npm, Vite, or the JOCKY source tree on the target PC.

Only the **build machine** needs Python and Node/npm.

## Build on Windows

From the JOCKY root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\desktop\build_windows.ps1
```

The script performs four important packaging steps:

1. Build the React frontend into static files with Vite.
2. Freeze the Flask backend and forensic Python modules into `JOCKY-backend.exe` with PyInstaller.
3. Bundle both into an Electron desktop application.
4. Create an NSIS installer and a portable EXE.

Output:

```text
desktop-app\release\JOCKY-Setup-1.0.0-x64.exe
desktop-app\release\JOCKY-Portable-1.0.0-x64.exe
```

## Target PC

The target Windows PC only needs the generated installer or portable EXE.

At runtime:

```text
JOCKY.exe
   │
   ├── Electron + Chromium (bundled)
   ├── React/Vite production UI (bundled)
   └── JOCKY-backend.exe
          └── Python runtime + Flask + forensic engine (bundled)
```

The application starts the backend silently, waits for `/health`, then opens the local production UI. It does not run `npm run dev`.

## If startup fails

JOCKY writes backend startup output to:

```text
%APPDATA%\JOCKY\jocky-backend.log
```

The startup error dialog also displays the log path.
