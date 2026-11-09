import sys


def _main():
    if len(sys.argv) > 1 and sys.argv[1] == "--prepare-viewer-features":
        from scripts.prepare_viewer_features import main as prepare_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return prepare_main()

    from app.AIHuMoDataStudio import main
    return main()

if __name__ == "__main__":
    raise SystemExit(_main())
