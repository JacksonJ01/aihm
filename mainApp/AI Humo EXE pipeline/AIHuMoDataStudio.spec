from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


bundle_dir = Path(SPECPATH)
project_root = bundle_dir.parent
if not (project_root / "aihumo_data_studio.py").is_file():
    nested_project = project_root / "mainApp"
    if (nested_project / "aihumo_data_studio.py").is_file():
        project_root = nested_project

datas = [
    (str(project_root / "configs" / "config.json"), "configs"),
    (str(project_root / "full_model" / "pose_landmarker_full.task"), "full_model"),
]
binaries = []
hiddenimports = [
    "scripts.prepare_viewer_features",
    *collect_submodules("pyarrow"),
]

# MediaPipe ships native libraries and task-support assets that must be copied
# in addition to its importable Python modules.
media_datas, media_binaries, media_hiddenimports = collect_all("mediapipe")
datas += media_datas
binaries += media_binaries
hiddenimports += media_hiddenimports

a = Analysis(
    [str(project_root / "aihumo_data_studio.py")],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "torch", "torchvision"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIHuMo Data Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AIHuMo Data Studio",
)

# macOS users expect an application bundle. Windows and Linux keep the regular
# one-folder COLLECT output.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AIHuMo Data Studio.app",
        icon=None,
        bundle_identifier="org.aihumo.datastudio",
        info_plist={
            "CFBundleDisplayName": "AIHuMo Data Studio",
            "CFBundleName": "AIHuMo Data Studio",
            "NSHighResolutionCapable": True,
        },
    )
