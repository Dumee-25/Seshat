# Packaging Seshat as a Windows app

This builds `Seshat.exe` and a double-click installer (`SeshatSetup.exe`) from
the Python package. Everything here runs on Windows; there is no cross-compile.

## Prerequisites

- Windows 10/11 with the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (preinstalled on Windows 11).
- A **clean, dedicated** Python 3.11+ virtual environment with the app and build
  tools installed, activated so that `python` resolves to it:
  ```
  python -m venv .venv-build
  .venv-build\Scripts\activate
  python -m pip install -e ".[desktop]" pyinstaller
  ```
  Do not build from a base Anaconda/conda environment or any other fat, shared
  interpreter. PyInstaller bundles what it can reach from the build environment,
  so building out of Anaconda base drags jupyterlab, bokeh, scipy, and the rest
  of the scientific stack into the analysis — the build crawls and the bundle
  bloats. A dedicated venv holds ~38 packages and freezes in about a minute.
- [Node.js](https://nodejs.org) on PATH, to build the React cockpit that gets bundled into the exe.
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer (optional; the onedir app builds without it).
- [Ollama](https://ollama.com) is a runtime dependency, not bundled. The app's first-run `seshat setup` detects it and pulls the models.

## Build

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

That script builds the frontend (`npm ci && npm run build` in `frontend/`, which
writes `seshat/api/static`) and then freezes the app. The spec refuses to build
if that static bundle is missing, so the exe can never ship a backend with no
UI. The build output is not committed; it is produced fresh on every build.

Outputs:
- `dist\Seshat\Seshat.exe` — the standalone app (a folder; ship the whole folder). Around 94 MB.
- `dist\SeshatSetup.exe` — the installer, around 35 MB (if Inno Setup is present).

The app should be on screen almost immediately: measured from a fresh install,
the window appears about 4 seconds after launch, and about 2 seconds on later
launches. If it takes appreciably longer than that, it is not warming up — it
has failed. Read `%USERPROFILE%\.seshat\app.log`, since a windowed build has no
console to print the reason to.

## How the frozen app works

`Seshat.exe` is one executable with several modes, selected in
`seshat/app/entry.py`:

- no arguments (double-click) -> launches the desktop app (`seshat app`);
- `--seshat-run-window <url>` -> opens a UI window;
- anything else -> the normal CLI (`Seshat.exe watch`, `Seshat.exe stats`, ...).

The app re-invokes itself with that internal flag instead of `python -m ...`,
because a frozen exe has no `python -m`. That logic lives in
`seshat/app/launch.py` and is unit-tested. The cockpit API needs no such mode:
it runs on a background thread inside the main process.

## Debugging a failed build

1. Read `%USERPROFILE%\.seshat\app.log` first. The shipped build is windowed
   (`console=False`), so it has no console and everything it prints goes there.
2. In `packaging/seshat.spec`, set `console=True` and rebuild — you'll see the
   traceback in a console window.
3. A `ModuleNotFoundError` at runtime means a hidden import was missed: add it
   to `hiddenimports` in the spec. uvicorn is the usual culprit, since it
   resolves its loop and protocol implementations by string at runtime.
4. A window that opens blank means FastAPI has no static files to serve: check
   that `seshat/api/static/index.html` exists and that the spec's `datas` entry
   for it survived.
5. Rebuild and repeat. Once it launches cleanly, set `console=False` again.

**Test the windowed build by double-clicking it, not from a shell.** Running the
exe with its output redirected — which is what any scripted check does — hands
it real stdout handles that a double-click does not, and that difference has
already hidden one crash that took the app down before its window opened (see
`ensure_streams` in `seshat/app/entry.py`). A bug on this path reaches every
user who launches from a shortcut, and no shell-based test will show it.

## Project selection

An installed app launched from the Start Menu has no project directory. On
first use, run `seshat init` in your research project and launch `seshat app`
there once; the app remembers it (`~/.seshat/app.toml`) and the shortcut opens
it thereafter.
