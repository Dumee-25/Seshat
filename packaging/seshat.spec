# PyInstaller spec for the Seshat desktop app (onedir).
#
# Build from the repo root:  pyinstaller packaging/seshat.spec
# The React frontend must be built first (`npm ci && npm run build` in
# frontend/), which writes seshat/api/static — packaging/build.ps1 does both in
# order. That static bundle is what the frozen FastAPI server serves; without
# it the app would have a backend and no UI, so the spec refuses to build.
#
# Freezing got considerably less awkward when Streamlit went: no data files to
# chase, no metadata version lookups, no submodule collection. What remains is
# uvicorn, whose runtime string imports the excludes/hiddenimports below cover.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
STATIC = ROOT / "seshat" / "api" / "static"

if not (STATIC / "index.html").exists():
    raise SystemExit(
        f"The React app is not built: {STATIC / 'index.html'} is missing.\n"
        "Run `npm ci && npm run build` in frontend/ first, or use "
        "packaging\\build.ps1, which does it for you."
    )

datas, binaries, hiddenimports = [], [], []

# Heavy packages that ship data/binaries and need full collection.
for pkg in ("sqlite_vec", "webview", "pystray", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Resolved via importlib.metadata at runtime.
for pkg in ("click", "seshat"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# The built React app (FastAPI serves it at the root), plus the eval example so
# `seshat eval` works from a frozen install.
datas += [
    (str(STATIC), "seshat/api/static"),
    (str(ROOT / "eval" / "questions.example.json"), "eval"),
]

# uvicorn resolves its loop/protocol implementations by string at runtime, so
# PyInstaller's static analysis cannot see them.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "seshat.api.app",
    "seshat.app.window",
]

a = Analysis(
    [str(ROOT / "seshat" / "app" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "tensorflow", "matplotlib",  # not used; keep the bundle lean
        "streamlit", "altair", "pyarrow",  # retired with the Streamlit UI
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Seshat",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # set True to see logs while debugging a build
    icon=str(ROOT / "packaging" / "seshat.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Seshat",
)
