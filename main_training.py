from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON_EXECUTABLE = Path(sys.executable)
EXTRACTOR_SCRIPT = PROJECT_ROOT / "scripts" / "extract_workout_pose_dataset.py"
TRAINER_SCRIPT = PROJECT_ROOT / "scripts" / "train_workout_classifier.py"
PREDICTOR_SCRIPT = PROJECT_ROOT / "scripts" / "predict_workout_exercise.py"
DEFAULT_INPUT_ROOT = PROJECT_ROOT / "preprocessedWorkoutVideos"
DEFAULT_EXTRACTED_ROOT = PROJECT_ROOT / "generated" / "workout-pose-dataset"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "generated" / "workout-models" / "workout-centroid-model.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "generated" / "workout-models" / "main-training-report.json"


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def run_step(command: list[str], step_name: str) -> str:
    print(f"[{step_name}] {' '.join(command)}")
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.stdout


def find_prediction_clip(extracted_root: Path) -> Path:
    clip_files = sorted(extracted_root.rglob("clip.json"))
    if clip_files:
        return clip_files[0]

    legacy_clip_files = sorted(
        path
        for path in extracted_root.rglob("*.json")
        if path.name not in {"index.json", "manifest.json"}
    )
    if legacy_clip_files:
        return legacy_clip_files[0]

    raise RuntimeError(f"No processed clip files found under {portable_path(extracted_root)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run workout extraction, training, and prediction sequentially.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT, help="Root folder containing raw workout videos.")
    parser.add_argument("--extracted-root", type=Path, default=DEFAULT_EXTRACTED_ROOT, help="Folder where extracted pose datasets are written.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH, help="Path where the trained model artifact is written.")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH, help="Path for the final pipeline report.")
    parser.add_argument("--manifest-csv", type=Path, default=None, help="Optional CSV manifest that lists relative video paths and exercise keys to process.")
    parser.add_argument("--predict-clip", type=Path, default=None, help="Optional processed clip JSON to use for the prediction step.")
    parser.add_argument("--extract-limit", type=int, default=0, help="Optional clip limit for the extraction step.")
    parser.add_argument("--extract-exercise", action="append", default=[], help="Optional exercise filters for extraction.")
    parser.add_argument("--feature-mode", default="both", help="Which angle features to train on: 2d, 3d, or both.")
    parser.add_argument("--benchmark-feature-mode", action="append", default=[], help="Optional feature mode to benchmark alongside the selected training mode. Can be repeated.")
    parser.add_argument("--window-family", default="short", help="Window family to use during prediction.")
    parser.add_argument("--overwrite", action="store_true", help="Force reprocessing during extraction.")
    args = parser.parse_args()

    extractor_command = [
        str(PYTHON_EXECUTABLE),
        str(EXTRACTOR_SCRIPT),
        "--input-root",
        str(args.input_root),
        "--output-root",
        str(args.extracted_root),
    ]
    if args.extract_limit:
        extractor_command.extend(["--limit", str(args.extract_limit)])
    if args.overwrite:
        extractor_command.append("--overwrite")
    if args.manifest_csv is not None:
        extractor_command.extend(["--manifest-csv", str(args.manifest_csv)])
    for exercise in args.extract_exercise:
        extractor_command.extend(["--exercise", exercise])

    extractor_output = run_step(extractor_command, "extract")

    trainer_command = [
        str(PYTHON_EXECUTABLE),
        str(TRAINER_SCRIPT),
        "--windows",
        str(args.extracted_root),
        "--output-model",
        str(args.model_path),
        "--feature-mode",
        args.feature_mode,
    ]
    for benchmark_feature_mode in args.benchmark_feature_mode:
        trainer_command.extend(["--benchmark-feature-mode", benchmark_feature_mode])
    trainer_output = run_step(trainer_command, "train")

    prediction_clip = args.predict_clip or find_prediction_clip(args.extracted_root)
    predictor_command = [
        str(PYTHON_EXECUTABLE),
        str(PREDICTOR_SCRIPT),
        "--model",
        str(args.model_path),
        "--clip",
        str(prediction_clip),
        "--window-family",
        args.window_family,
    ]
    predictor_output = run_step(predictor_command, "predict")

    report_payload: dict[str, Any] = {
        "inputRoot": portable_path(args.input_root),
        "extractedRoot": portable_path(args.extracted_root),
        "modelPath": portable_path(args.model_path),
        "predictionClip": portable_path(prediction_clip),
        "predictionWindowFamily": args.window_family,
        "featureMode": args.feature_mode,
        "benchmarkFeatureModes": args.benchmark_feature_mode,
        "manifestCsv": portable_path(args.manifest_csv) if args.manifest_csv else None,
        "steps": {
            "extract": extractor_output.strip(),
            "train": trainer_output.strip(),
            "predict": predictor_output.strip(),
        },
    }

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote report to {portable_path(args.report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())