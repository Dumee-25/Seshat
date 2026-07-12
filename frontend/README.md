# Seshat Cockpit — frontend

The React workspace for `seshat cockpit`. See [../docs/COCKPIT.md](../docs/COCKPIT.md) for the design.

## Develop

Two terminals, from a Seshat project directory:

```
# 1. the API (Python)
seshat cockpit --no-window

# 2. the frontend (this folder), with hot reload
npm install
npm run dev
```

Then open http://localhost:5173 — Vite proxies `/api` to the cockpit server on port 8765.

## Build

```
npm run build
```

This compiles into `../seshat/api/static/`, which FastAPI serves. After building, `seshat cockpit` (no `--no-window`) opens it in a native window (needs the `desktop` extra).

## Stack

Vite + React + TypeScript, hand-written CSS with the Seshat "kohl" theme (no component library). One view so far — the timeline; chat, papers/links, code, and data panels come in later phases.
