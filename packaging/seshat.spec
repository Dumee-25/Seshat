# PyInstaller spec for the Seshat desktop app (onedir).
#
# Build from the repo root:  pyinstaller packaging/seshat.spec
# Streamlit is the awkward dependency to freeze: it needs its data files, its
# package metadata (for version lookups), and its submodules collected. The
# collect_all + copy_metadata calls below handle that; if a first build fails
# on a missing module or datafile, add it here rather than guessing.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent

datas, binaries, hiddenimports = [], [], []

# Heavy packages that ship data/binaries and need full collection.
for pkg in ("streamlit", "sqlite_vec", "webview", "pystray", "PIL", "altair", "pyarrow"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Streamlit resolves versions via importlib.metadata at runtime.
for pkg in ("streamlit", "click", "seshat"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# The Streamlit UI script is run (not imported), so bundle it explicitly, plus
# the eval example so `seshat eval` works from a frozen install.
datas += [
    (str(ROOT / "seshat" / "ui" / "app.py"), "seshat/ui"),
    (str(ROOT / "eval" / "questions.example.json"), "eval"),
]

hiddenimports += [
    "streamlit.web.bootstrap",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "seshat.app.window",
    "seshat.ui.app",
]

a = Analysis(
    [str(ROOT / "seshat" / "app" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib"],  # not used; keep the bundle lean
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
