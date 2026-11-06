from pathlib import Path
import argparse, json
import pandas as pd
from aihumo.ids import make_session_id, make_video_id

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--session-id", default=None)
    p.add_argument("--participant-id", default="P001")
    p.add_argument("--video", nargs=3, action="append",
                   metavar=("VIDEO_PATH", "CAMERA_ID", "DESCRIPTION"),
                   required=True)
    args = p.parse_args()

    root = Path(args.root)
    session_id = args.session_id or make_session_id()
    rows = []
    for video_path, camera_id, description in args.video:
        rows.append({
            "session_id": session_id,
            "video_id": make_video_id(),
            "participant_id": args.participant_id,
            "video_path": video_path,
            "camera_id": camera_id,
            "description": description,
        })

    out = root / "data/raw/manifests" / f"{session_id}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(out)
    print(pd.DataFrame(rows).to_string(index=False))

if __name__ == "__main__":
    main()
