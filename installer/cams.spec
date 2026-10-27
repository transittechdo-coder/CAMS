# PyInstaller recipe for CAMS.exe
# Build from the project folder:  pyinstaller installer/cams.spec --noconfirm
# Output: dist/CAMS/CAMS.exe (plus its support files)

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = ROOT / "installer" / "cams.ico"

datas = [
    (str(ROOT / "cams" / "static"), "cams/static"),
    (str(ROOT / "models"), "models"),
]

a = Analysis(
    [str(ROOT / "cams" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "multipart",
        "webview.platforms.edgechromium", "webview.platforms.winforms",
    ],
    excludes=["matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Loading picture shown the instant CAMS.exe is double-clicked (needs Tk in the
# build Python, which python.org and GitHub's Windows Python include).
SPLASH = ROOT / "installer" / "splash.png"
try:
    import tkinter  # noqa: F401
    splash = Splash(str(SPLASH), binaries=a.binaries, datas=a.datas, text_pos=(40, 248),
                    text_size=10, text_color="#A9BCC6", minify_script=True, always_on_top=True) if SPLASH.exists() else None
except Exception as exc:  # no Tk: build without a splash
    print("No splash screen:", exc)
    splash = None

exe = EXE(
    pyz, a.scripts, *([splash] if splash else []), [],
    exclude_binaries=True,
    name="CAMS",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, *([splash.binaries] if splash else []), strip=False, upx=False, name="CAMS")
