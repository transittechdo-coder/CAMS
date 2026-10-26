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
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CAMS",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CAMS")
