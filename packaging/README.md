# Packaging Seshat as a Windows app

This builds `Seshat.exe` and a double-click installer (`SeshatSetup.exe`) from
the Python package. Everything here runs on Windows; there is no cross-compile.

## Prerequisites

- Windows 10/11 with the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (preinstalled on Windows 11).
- A Python 3.11+ environment with the app and build tools installed:
  ```
  python -m pip install -e ".[ui,desktop]" pyinstaller
  ```
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer (optional; the onedir app builds without it).
- [Ollama](https://ollama.com) is a runtime dependency, not bundled. The app's first-run `seshat setup` detects it and pulls the models.

## Build

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Outputs:
- `dist\Seshat\Seshat.exe` — the standalone app (a folder; ship the whole folder).
- `dist\SeshatSetup.exe` — the installer (if Inno Setup is present).

## How the frozen app works

`Seshat.exe` is one executable with several modes, selected in
`seshat/app/entry.py`:

- no arguments (double-click) -> launches the desktop app (`seshat app`);
- `--seshat-run-streamlit <port>` -> runs the Streamlit server in-process;
- `--seshat-run-window <url>` -> opens a UI window;
- anything else -> the normal CLI (`Seshat.exe watch`, `Seshat.exe stats`, ...).

The app re-invokes itself with those internal flags instead of `python -m ...`,
because a frozen exe has no `python -m`. That logic lives in
`seshat/app/launch.py` and is unit-tested.

## Debugging a failed build

Streamlit is the usual culprit. If the built app exits immediately or errors:

1. In `packaging/seshat.spec`, set `console=True` and rebuild — you'll see the
   traceback in a console window.
2. A `ModuleNotFoundError` at runtime means a hidden import was missed: add it
   to `hiddenimports` in the spec.
3. A missing data file (templates, static assets) means extend the
   `collect_all` list or add an explicit `datas` entry.
4. Rebuild and repeat. Once it launches cleanly, set `console=False` again.

## Project selection

An installed app launched from the Start Menu has no project directory. On
first use, run `seshat init` in your research project and launch `seshat app`
there once; the app remembers it (`~/.seshat/app.toml`) and the shortcut opens
it thereafter.
