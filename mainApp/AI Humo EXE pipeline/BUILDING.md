# AIHuMo portable Windows build

This directory contains the reproducible preview build for the Windows x64
one-folder distribution. User recordings, annotations, checkpoints, test
artifacts, and local settings are intentionally excluded.

## Build

From PowerShell in this directory:

```powershell
.\build_portable.ps1 -Version 0.1.1
```

The script uses `..\.venv` by default. Pass `-PythonExe` to use a separate build
environment. Install PyInstaller in that environment and place the MediaPipe
pose model at `..\full_model\pose_landmarker_full.task` before building.
The executable and runtime files are under `dist\v<version>\`. The script
creates a portable ZIP and its SHA-256 checksum under `release\`. Build outputs
are versioned so the script leaves previous portable folders and their data
intact.

## Included runtime assets

- Desktop application and `aihumo` pipeline modules
- PyQt6, OpenCV, pandas, PyArrow, Matplotlib, and MediaPipe runtime dependencies
- `configs\config.json`
- `full_model\pose_landmarker_full.task`
- Frozen-safe dispatch for the Prepare Existing Recording utility

## Later production work

A public installer should add code signing, a stable user-data location,
automatic upgrades, crash logs, a license/third-party notice bundle, and CI
release builds on a clean Windows runner.
