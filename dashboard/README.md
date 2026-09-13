# JOCKY Desktop Frontend

This directory contains the production React/Vite frontend used by the JOCKY Windows desktop application.

## Development

```bash
npm install
npm run dev
```

## Production build

```bash
npm install
npm run build
```

The production build is written to `dist/` and is static. It does **not** require the TanStack Start server runtime.

The desktop shell uses a hash-based router so the built application can be loaded directly from the Electron application's local resources without a Node/Vite development server.

## Backend

The frontend talks to the local Flask API at:

```text
http://127.0.0.1:5000
```

Override it during development with:

```text
VITE_API_BASE_URL=http://127.0.0.1:5000
```

In the production Windows build, the bundled Electron process starts the bundled Flask/Python backend automatically.
