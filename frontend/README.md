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
npm ci && npm run build
```

This compiles into `../seshat/api/static/`, which FastAPI serves. After building, `seshat cockpit` (no `--no-window`) opens it in a native window, as does `seshat app` — both need the `desktop` extra. `packaging/build.ps1` runs this build before freezing the exe, so a packaged install ships the compiled app.

The output directory is gitignored: it is a build artifact, produced fresh rather than committed.

## Stack

Vite + React + TypeScript, hand-written CSS with the Seshat "kohl" theme (no component library). All five surfaces are built: timeline, chat, papers & links, code, and data.

## Layout

The shell is a fixed 200px sidebar (icon + label per surface) over a full-width status bar; `App.tsx` owns the view switch and the 5-second poll that feeds the timeline's live tail. Each surface is one component, and `api.ts` is the only place that talks HTTP.

Two panels — chat and code — scroll internally rather than as a page; they are listed in `SELF_SCROLLING` in `App.tsx`, which drops the `scrolls` class off the content wrapper so their own flex layout takes over.

The timeline is the only surface that writes back: confirming or correcting an inferred intent posts to `/api/entries/{id}/intent`, then asks `App` to re-poll so the badge reflects the stored status rather than a local guess.
