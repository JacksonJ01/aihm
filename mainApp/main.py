"""Canonical AIHuMo Data Studio launcher.

Run this file from the project root. Application modules under ``app`` are
imported as a package and are not intended to be launched directly.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--prepare-viewer-features":
        from scripts.prepare_viewer_features import main as prepare_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return int(prepare_main() or 0)

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke-test":
        root = Path(__file__).resolve().parent
        required = (
            root / "configs" / "config.json",
            root / "full_model" / "pose_landmarker_full.task",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError("Missing packaged runtime files: " + ", ".join(missing))
        return 0

    from app.AIHuMoDataStudio import main as studio_main

    return int(studio_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
