# AIHuMo native desktop builds

This directory contains reproducible preview builds for Windows x64, Linux x64,
macOS Intel x64, and macOS Apple Silicon arm64. User recordings, annotations,
checkpoints, test artifacts, and local settings are intentionally excluded.

## Windows build

From PowerShell in this directory:

```powershell
.\build_portable.ps1 -Version 0.1.3
```

The script uses `..\.venv` by default. Pass `-PythonExe` to use a separate build
environment. Install PyInstaller in that environment and place the MediaPipe
pose model at `..\full_model\pose_landmarker_full.task` before building.
The executable and runtime files are under `dist\v<version>\`. The script
creates a portable ZIP and its SHA-256 checksum under `release\`. Build outputs
are versioned, and the script refuses to overwrite an existing version.

## Linux and macOS builds

Each Unix platform has its own native script and README:

- `Linux/build_portable.sh`
- `macOS/build_portable.sh`

PyInstaller packages must be built on the operating system they target. The
GitHub Actions workflow `.github/workflows/desktop-cross-platform.yml` runs all
four native builds. Pushing a tag such as `desktop-v0.1.3` validates the version,
builds and smoke-tests every package, creates the matching GitHub Release, and
uploads each package with its SHA-256 checksum.

## Included runtime assets

- Desktop application and `aihumo` pipeline modules
- PyQt6, OpenCV, pandas, PyArrow, Matplotlib, and MediaPipe runtime dependencies
- `configs\config.json`
- `full_model\pose_landmarker_full.task`
- Frozen-safe dispatch for the Prepare Existing Recording utility

## Later production work

A public installer should add code signing, a stable user-data location,
automatic upgrades, crash logs, and a license/third-party notice bundle.
