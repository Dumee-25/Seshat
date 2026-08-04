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

## Test

```
npm test
```

Vitest in jsdom, with `npm run test:watch` while working. The suite is weighted
towards the things that were hardest to get right rather than towards coverage:

- **`markdown.test.tsx`** — the hand-rolled renderer for chat answers. Most of
  it is prose that only *looks* like markup (`2 * 3`, `val_loss_history`,
  unclosed markers), because that is where every real bug has been.
- **`panels.test.tsx`** — that a panel which failed to load never renders an
  empty state claiming the project is empty.
- **`shell.test.tsx`** — the status bar reporting the last poll rather than a
  stale success, and the queued count explaining a stalled queue.
- **`chat.test.tsx`** — citation labels, cancelling a question, and the
  two-step Clear.
- **`timeline.test.tsx`** — keyboard triage, paging, and debounced search.

Vitest is pinned to the same major as Vite so tests and the build share one
toolchain; bumping one means bumping the other.

Running the tests needs **Node >= 22.22.2** (jsdom's floor, declared in
`engines`). Building does not — an older Node still produces the bundle, it
just cannot run the suite.

## Build

```
npm ci && npm run build
```

This compiles into `../seshat/api/static/`, which FastAPI serves. After building, `seshat cockpit` (no `--no-window`) opens it in a native window, as does `seshat app` — both need the `desktop` extra. `packaging/build.ps1` runs this build before freezing the exe, so a packaged install ships the compiled app.

The output directory is gitignored: it is a build artifact, produced fresh rather than committed.

## Stack

Vite + React + TypeScript, hand-written CSS with the Seshat "kohl" theme (no component library). All five surfaces are built: timeline, chat, papers & links, code, and data.

## Layout

The shell is a fixed 200px sidebar (icon + label per surface) over a full-width status bar. `App.tsx` owns the view switch, the 5-second status poll behind that bar, and a slower check of whether Ollama can actually answer. Each surface is one component, and `api.ts` is the only place that talks HTTP.

Three panels — timeline, chat, and code — scroll internally rather than as a page; they are listed in `SELF_SCROLLING` in `App.tsx`, which drops the `scrolls` class off the content wrapper so their own flex layout takes over. The timeline is there so its filter bar stays put while the feed moves under it.

`Timeline.tsx` fetches its own feed: filter state, paging, and the 5-second live tail all live with the component that owns them rather than being threaded down from `App`. It is also the only surface that writes back — confirming, correcting, or undoing an inferred intent posts to `/api/entries/{id}/intent[/reset]` and then re-polls, so the badge reflects the stored status rather than a local guess.

Two rules the tests exist to hold on to, because both were got wrong once:

- A panel that could not load must never fall through to an empty state
  claiming the project is empty. Keep "failed to load" and "loaded, nothing
  here" as separate states — a flag set in `.finally()` cannot distinguish them.
- The status bar reports the *last poll*, not the last success. Stale counts
  stay on screen (they are still the most recent truth), but the connection
  indicator must not keep claiming to be live.
