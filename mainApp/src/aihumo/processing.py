from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pandas as pd

from .features import FeatureEngine
from .graphs import generate_angle_graphs
from .metadata import build_metadata
from .pose import extract_landmarks_dataframe, inspect_video, iter_landmark_rows
from .processing_state import ProcessingState, fingerprint_file, stable_json_hash
from .quality import build_quality_report
from .storage import (
    assert_single_canonical_feature_parquet,
    load_json,
    load_parquet,
    save_json_atomic,
    save_parquet_atomic,
)
from .tracking import TargetStatus, TargetTracker
from .validation import validate_artifacts, validate_frame_dataframe

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class ProcessingResult:
    output_dir: Path
    landmarks_path: Path
    features_path: Path
    processed_video_path: Path
    metadata_path: Path
    feature_manifest_path: Path
    quality_report_path: Path
    processing_state_path: Path
    graph_manifest_path: Path | None = None


def _emit(callback: ProgressCallback | None, fraction: float, message: str) -> None:
    if callback:
        callback(float(max(0.0, min(1.0, fraction))), message)


def _artifact_paths(output_root: Path, session_id: str, video_id: str) -> dict[str, Path]:
    output_dir = output_root / session_id / video_id
    return {
        "output_dir": output_dir,
        "video_dir": output_dir / "video",
        "parquet_dir": output_dir / "parquet",
        "metadata_dir": output_dir / "metadata",
        "checkpoint_dir": output_dir / ".processing" / "landmarks",
        "state_path": output_dir / ".processing" / "processing_state.json",
        "landmarks_path": output_dir / "parquet" / f"{video_id}_landmarks.parquet",
        "features_path": output_dir / "parquet" / f"{video_id}_features.parquet",
        "processed_video_path": output_dir / "video" / f"{video_id}_skeleton.mp4",
        "metadata_path": output_dir / "metadata" / f"{video_id}_metadata.json",
        "manifest_path": output_dir / "metadata" / f"{video_id}_feature_manifest.json",
        "quality_path": output_dir / "metadata" / f"{video_id}_quality_report.json",
    }


def processing_job_status(
    *,
    source_video: str | Path,
    model_path: str | Path,
    cfg: dict[str, Any],
    output_root: str | Path,
    session_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Inspect whether a Mode 0 job is new, resumable, complete, or conflicting."""
    paths = _artifact_paths(Path(output_root), session_id, video_id)
    source = Path(source_video)
    model = Path(model_path)
    if not source.exists() or not model.exists():
        return {"status": "invalid_inputs", "output_dir": str(paths["output_dir"])}

    if not paths["state_path"].exists():
        final_exists = any(paths[key].exists() for key in ("landmarks_path", "features_path", "processed_video_path"))
        return {
            "status": "existing_artifacts_without_state" if final_exists else "new",
            "output_dir": str(paths["output_dir"]),
        }

    state = ProcessingState.load(paths["state_path"])
    compatible = state.compatible_quickly_with(
        source_fingerprint=fingerprint_file(source, include_hash=False),
        model_fingerprint=fingerprint_file(model, include_hash=False),
        config_fingerprint=stable_json_hash(cfg),
    )
    if not compatible:
        return {
            "status": "conflict",
            "stage": state.stage,
            "job_status": state.status,
            "output_dir": str(paths["output_dir"]),
            "message": "Existing processing state was created from a different source video, pose model, or configuration.",
        }
    return {
        "status": "complete" if state.status == "completed" else "resumable",
        "stage": state.stage,
        "job_status": state.status,
        "next_frame": state.next_frame,
        "persisted_frames": state.persisted_frames,
        "output_dir": str(paths["output_dir"]),
        "message": state.error,
    }


def create_skeleton_video(
    source_video: str | Path,
    landmarks_df: pd.DataFrame,
    output_path: str | Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Create a source-derived skeleton MP4 without modifying the source."""
    source_video = Path(source_video)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video for skeleton rendering: {source_video}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or len(landmarks_df))
    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise ValueError(f"Invalid video metadata for skeleton output: {source_video}")

    points_array = np.full((len(landmarks_df), 33, 2), np.nan, dtype=np.float32)
    for i in range(33):
        points_array[:, i, 0] = pd.to_numeric(landmarks_df[f"lm{i}_x"], errors="coerce").to_numpy(dtype=np.float32)
        points_array[:, i, 1] = pd.to_numeric(landmarks_df[f"lm{i}_y"], errors="coerce").to_numpy(dtype=np.float32)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not create processed video: {output_path}")

    connections = [
        (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
        (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
        (23, 25), (25, 27), (27, 29), (29, 31), (24, 26), (26, 28), (28, 30), (30, 32),
        (15, 17), (15, 19), (15, 21), (16, 18), (16, 20), (16, 22), (17, 19), (18, 20),
    ]

    processed = 0
    try:
        while True:
            if cancel_check and cancel_check():
                raise InterruptedError("Skeleton video generation was cancelled.")
            ok, frame = cap.read()
            if not ok:
                break
            if processed < len(points_array):
                points: list[tuple[int, int] | None] = []
                for i in range(33):
                    x, y = points_array[processed, i]
                    points.append((int(round(float(x) * width)), int(round(float(y) * height))) if np.isfinite(x) and np.isfinite(y) else None)
                for a, b in connections:
                    if points[a] is not None and points[b] is not None:
                        cv2.line(frame, points[a], points[b], (0, 255, 0), 2, cv2.LINE_AA)
                for point in points:
                    if point is not None:
                        cv2.circle(frame, point, 3, (0, 0, 255), -1, cv2.LINE_AA)

                # Tracking metadata is rendered into the validation video so a human
                # can see when AIHuMo believes the target is tracked or occluded.
                if "target_bbox_x1" in landmarks_df.columns:
                    x1 = pd.to_numeric(landmarks_df["target_bbox_x1"], errors="coerce").iloc[processed]
                    y1 = pd.to_numeric(landmarks_df["target_bbox_y1"], errors="coerce").iloc[processed]
                    x2 = pd.to_numeric(landmarks_df["target_bbox_x2"], errors="coerce").iloc[processed]
                    y2 = pd.to_numeric(landmarks_df["target_bbox_y2"], errors="coerce").iloc[processed]
                    if np.isfinite([x1, y1, x2, y2]).all():
                        status = str(landmarks_df.get("target_status", pd.Series(["tracked"] * len(landmarks_df))).iloc[processed])
                        left, top = int(round(x1 * width)), int(round(y1 * height))
                        right, bottom = int(round(x2 * width)), int(round(y2 * height))
                        cv2.rectangle(frame, (left, top), (right, bottom), (255, 200, 0), 2, cv2.LINE_AA)
                        cv2.putText(frame, status, (left, max(20, top - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 2, cv2.LINE_AA)
            writer.write(frame)
            processed += 1
            if processed == 1 or processed % 30 == 0 or processed == total:
                _emit(progress_callback, processed / max(1, total), f"Skeleton video: frame {processed}/{total}")
    finally:
        cap.release()
        writer.release()

    if processed != total:
        raise RuntimeError(f"Skeleton output frame count mismatch: {processed} vs expected {total}")
    if processed == 0:
        raise ValueError(f"Skeleton video contains no frames: {output_path}")
    return processed


def _load_checkpoint_chunks(state: ProcessingState, checkpoint_dir: Path) -> pd.DataFrame:
    chunks = []
    for relative_path in state.checkpoint_chunks:
        path = checkpoint_dir.parent.parent / relative_path if not Path(relative_path).is_absolute() else Path(relative_path)
        # State stores paths relative to the job directory (.processing/...).
        if not path.exists():
            raise RuntimeError(f"Processing checkpoint is missing: {path}")
        chunks.append(pd.read_parquet(path))
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def _normalize_single_pose_rows(df: pd.DataFrame, tracking_cfg: dict[str, Any]) -> pd.DataFrame:
    """Repair pre-change checkpoints that called empty frames ``tracked``."""
    single_pose = not (
        bool(tracking_cfg.get("enabled", False))
        and tracking_cfg.get("mode", "single_pose") == "target_association"
    )
    required = {"target_status", "pose_present"}
    if not single_pose or not required.issubset(df.columns):
        return df
    out = df.copy()
    missing_pose = pd.to_numeric(out["pose_present"], errors="coerce").fillna(0) != 1
    tracked = out["target_status"].astype(str).isin({TargetStatus.TRACKED.value, TargetStatus.REACQUIRED.value})
    repair = missing_pose & tracked
    if repair.any():
        out.loc[repair, "target_status"] = TargetStatus.SEARCHING.value
        if "target_confidence" in out.columns:
            out.loc[repair, "target_confidence"] = 0.0
        if "target_track_id" in out.columns:
            out.loc[repair, "target_track_id"] = np.nan
    return out


def _persist_landmark_chunk(df: pd.DataFrame, checkpoint_dir: Path, chunk_index: int) -> str:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    filename = f"landmarks_{chunk_index:05d}.parquet"
    save_parquet_atomic(df, checkpoint_dir / filename)
    return str(Path(".processing") / "landmarks" / filename)


def _extract_with_checkpoints(
    *,
    source_video: Path,
    model_path: Path,
    pose_cfg: dict,
    identifiers: dict[str, Any],
    video_info: dict[str, Any],
    state: ProcessingState,
    state_path: Path,
    checkpoint_dir: Path,
    cfg: dict[str, Any],
    progress_callback: ProgressCallback | None,
    cancel_check: Callable[[], bool] | None,
) -> pd.DataFrame:
    checkpoint_interval = max(1, int(cfg.get("processing", {}).get("checkpoint_interval_frames", 300)))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    if state.status == "new":
        state.stage = "landmarks"
        state.save(state_path)

    tracking_cfg = cfg.get("tracking", {})
    tracker = None
    if bool(tracking_cfg.get("enabled", False)) and tracking_cfg.get("mode", "single_pose") == "target_association":
        tracker = (
            TargetTracker.from_document(tracking_cfg, state.tracking_state)
            if state.tracking_state
            else TargetTracker(tracking_cfg)
        )

    if state.next_frame > 0:
        checkpoint_df = _normalize_single_pose_rows(_load_checkpoint_chunks(state, checkpoint_dir), tracking_cfg)
    else:
        checkpoint_df = pd.DataFrame()
        for path in checkpoint_dir.glob("*.parquet"):
            path.unlink(missing_ok=True)
        state.checkpoint_chunks = []

    start_frame = state.next_frame
    chunk_rows: list[dict[str, Any]] = []
    chunk_index = len(state.checkpoint_chunks)

    try:
        for row in iter_landmark_rows(
            source_video,
            model_path,
            pose_cfg,
            identifiers,
            video_info,
            tracking_cfg=tracking_cfg,
            tracker=tracker,
            start_frame=start_frame,
            progress_callback=lambda p, m: _emit(progress_callback, 0.05 + p * 0.35, m),
            cancel_check=cancel_check,
        ):
            chunk_rows.append(row)
            if len(chunk_rows) >= checkpoint_interval:
                chunk_df = pd.DataFrame(chunk_rows)
                relative = _persist_landmark_chunk(chunk_df, checkpoint_dir, chunk_index)
                state.checkpoint_chunks.append(relative)
                state.persisted_frames = state.persisted_frames + len(chunk_df)
                state.next_frame = int(chunk_df["frame_id"].iloc[-1]) + 1
                state.tracking_state = tracker.to_document() if tracker is not None else None
                state.status = "in_progress"
                state.stage = "landmarks"
                state.error = None
                state.save(state_path)
                chunk_rows = []
                chunk_index += 1

        if chunk_rows:
            chunk_df = pd.DataFrame(chunk_rows)
            relative = _persist_landmark_chunk(chunk_df, checkpoint_dir, chunk_index)
            state.checkpoint_chunks.append(relative)
            state.persisted_frames += len(chunk_df)
            state.next_frame = int(chunk_df["frame_id"].iloc[-1]) + 1
            state.tracking_state = tracker.to_document() if tracker is not None else None
            state.save(state_path)

    except InterruptedError as exc:
        if chunk_rows:
            chunk_df = pd.DataFrame(chunk_rows)
            relative = _persist_landmark_chunk(chunk_df, checkpoint_dir, chunk_index)
            state.checkpoint_chunks.append(relative)
            state.persisted_frames += len(chunk_df)
            state.next_frame = int(chunk_df["frame_id"].iloc[-1]) + 1
            state.tracking_state = tracker.to_document() if tracker is not None else None
        state.status = "cancelled"
        state.stage = "landmarks"
        state.error = str(exc)
        state.save(state_path)
        raise
    except Exception as exc:
        state.status = "failed"
        state.stage = "landmarks"
        state.error = f"{type(exc).__name__}: {exc}"
        state.save(state_path)
        raise

    checkpoint_df = _normalize_single_pose_rows(_load_checkpoint_chunks(state, checkpoint_dir), tracking_cfg)
    if checkpoint_df.empty or len(checkpoint_df) != int(video_info["frame_count"]):
        state.status = "failed"
        state.error = (
            f"Landmark checkpoint count mismatch: {len(checkpoint_df)} "
            f"vs expected {video_info['frame_count']}"
        )
        state.save(state_path)
        raise RuntimeError(state.error)

    checkpoint_df = checkpoint_df.sort_values("frame_id").reset_index(drop=True)
    validate_frame_dataframe(checkpoint_df)
    # The checkpoint chunks are recovery state only. The final raw-landmark
    # artifact is written once by process_video after recording-level metadata
    # has been applied.
    state.next_frame = len(checkpoint_df)
    state.persisted_frames = len(checkpoint_df)
    state.stage = "landmarks_extracted"
    state.status = "in_progress"
    state.error = None
    state.save(state_path)
    return checkpoint_df


def _cleanup_checkpoints(checkpoint_dir: Path) -> None:
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir, ignore_errors=False)
    processing_dir = checkpoint_dir.parent
    try:
        processing_dir.rmdir()
    except OSError:
        pass


def process_video(
    *,
    source_video: str | Path,
    model_path: str | Path,
    cfg: dict,
    identifiers: dict,
    optional_metadata: dict,
    output_root: str | Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ProcessingResult:
    """Run the complete Mode 0 pipeline with crash-safe raw checkpoints.

    Final feature Parquet is still generated exactly once from one complete
    in-memory DataFrame. Checkpoint Parquet files are temporary recovery state,
    not model inputs or final dataset artifacts.
    """
    source_video = Path(source_video)
    model_path = Path(model_path)
    output_root = Path(output_root)
    session_id = str(identifiers["session_id"])
    video_id = str(identifiers["video_id"])
    paths = _artifact_paths(output_root, session_id, video_id)

    if not source_video.exists():
        raise FileNotFoundError(f"Source video does not exist: {source_video}")
    if not model_path.exists():
        raise FileNotFoundError(f"MediaPipe model does not exist: {model_path}")

    output_dir = paths["output_dir"]
    for key in ("video_dir", "parquet_dir", "metadata_dir", "checkpoint_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    assert_single_canonical_feature_parquet(paths["parquet_dir"], video_id, paths["features_path"])
    state_fingerprint = fingerprint_file(source_video)
    model_fingerprint = fingerprint_file(model_path)
    config_fingerprint = stable_json_hash(cfg)

    if paths["state_path"].exists():
        state = ProcessingState.load(paths["state_path"])
        if not state.compatible_with(
            source_fingerprint=state_fingerprint,
            model_fingerprint=model_fingerprint,
            config_fingerprint=config_fingerprint,
        ):
            raise RuntimeError(
                "A processing checkpoint already exists for this session/video but its source, "
                "pose model, or configuration does not match the current request. "
                "Use a new video_id or deliberately remove the old processing job."
            )
    else:
        final_artifacts = [paths[key] for key in ("landmarks_path", "features_path", "processed_video_path", "metadata_path")]
        if any(path.exists() for path in final_artifacts):
            raise FileExistsError(
                f"Output directory already contains artifacts without a resumable state: {output_dir}. "
                "Refusing to overwrite them automatically."
            )
        state = ProcessingState.new(
            session_id=session_id,
            video_id=video_id,
            source_fingerprint=state_fingerprint,
            model_fingerprint=model_fingerprint,
            config_fingerprint=config_fingerprint,
        )
        state.save(paths["state_path"])

    if state.status == "completed":
        validate_artifacts(
            source_video=source_video,
            processed_video=paths["processed_video_path"],
            landmarks_path=paths["landmarks_path"],
            features_path=paths["features_path"],
            metadata_path=paths["metadata_path"],
            manifest_path=paths["manifest_path"],
        )
        return ProcessingResult(
            output_dir, paths["landmarks_path"], paths["features_path"],
            paths["processed_video_path"], paths["metadata_path"],
            paths["manifest_path"], paths["quality_path"], paths["state_path"],
        )

    try:
        _emit(progress_callback, 0.02, "Inspecting source video")
        video_info = inspect_video(source_video)
        LOGGER.info(
            "Processing %s/%s: %sx%s @ %.3f FPS, %d frames",
            session_id, video_id, video_info["width"], video_info["height"],
            video_info["source_fps"], video_info["frame_count"],
        )

        state.stage = "landmarks"
        state.status = "in_progress"
        state.error = None
        state.save(paths["state_path"])

        if paths["landmarks_path"].exists() and state.next_frame >= video_info["frame_count"]:
            landmark_df = load_parquet(paths["landmarks_path"])
            validate_frame_dataframe(landmark_df)
        else:
            landmark_df = _extract_with_checkpoints(
                source_video=source_video,
                model_path=model_path,
                pose_cfg=cfg.get("pose", {}),
                identifiers=identifiers,
                video_info=video_info,
                state=state,
                state_path=paths["state_path"],
                checkpoint_dir=paths["checkpoint_dir"],
                cfg=cfg,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        # Recording metadata lives on every frame. Labels do not.
        for key, value in optional_metadata.items():
            if value is not None:
                landmark_df[key] = value
        validate_frame_dataframe(landmark_df)
        if len(landmark_df) != video_info["frame_count"]:
            raise RuntimeError("Landmark frame count changed during processing.")
        # If metadata columns were added after the checkpoint Parquet was created,
        # refresh the final raw-landmark artifact once before moving forward.
        save_parquet_atomic(landmark_df, paths["landmarks_path"])
        state.stage = "landmarks_saved"
        state.save(paths["state_path"])

        if not paths["processed_video_path"].exists():
            _emit(progress_callback, 0.42, "Creating skeleton-overlay video")
            partial_video = paths["processed_video_path"].with_suffix(".partial.mp4")
            partial_video.unlink(missing_ok=True)
            create_skeleton_video(
                source_video,
                landmark_df,
                partial_video,
                lambda p, m: _emit(progress_callback, 0.42 + p * 0.18, m),
                cancel_check,
            )
            partial_video.replace(paths["processed_video_path"])
        state.stage = "skeleton_saved"
        state.save(paths["state_path"])

        if paths["features_path"].exists():
            final_df = load_parquet(paths["features_path"])
            validate_frame_dataframe(final_df)
            feature_columns = [
                column for column in FeatureEngine(cfg).select_model_features(final_df)
                if column in final_df.columns
            ]
            if paths["manifest_path"].exists():
                feature_manifest = load_json(paths["manifest_path"])
            else:
                feature_manifest = FeatureEngine(cfg)._build_manifest(final_df, feature_columns, [], {})
        else:
            _emit(progress_callback, 0.62, "Generating complete feature DataFrame")
            feature_result = FeatureEngine(cfg).build(
                landmark_df,
                lambda p, m: _emit(progress_callback, 0.62 + p * 0.25, m),
            )
            final_df = feature_result.dataframe
            feature_columns = feature_result.feature_columns
            feature_manifest = feature_result.feature_manifest
            validate_frame_dataframe(final_df)
            if len(final_df) != len(landmark_df):
                raise ValueError("Feature generation changed the frame count.")
            save_parquet_atomic(final_df, paths["features_path"])
            LOGGER.info("Final feature count: %d", len(feature_columns))
        state.stage = "features_saved"
        state.save(paths["state_path"])

        quality_report = build_quality_report(final_df, feature_columns)
        quality_report["ready_for_annotation"] = (
            quality_report["pose_present_fraction"]
            >= float(cfg.get("quality", {}).get("min_pose_present_fraction", 0.80))
        )
        quality_report["thresholds"] = cfg.get("quality", {})

        metadata = build_metadata(
            cfg=cfg,
            identifiers=identifiers,
            source_video=source_video,
            processed_video=paths["processed_video_path"],
            landmarks_parquet=paths["landmarks_path"],
            features_parquet=paths["features_path"],
            video_info={**video_info, "frame_count": len(final_df)},
            optional_metadata=optional_metadata,
        )
        metadata["source_fingerprint"] = state_fingerprint
        metadata["model_fingerprint"] = model_fingerprint
        metadata["config_fingerprint"] = config_fingerprint
        metadata["quality_report"] = str(paths["quality_path"])
        metadata["annotation_ground_truth"] = "separate annotations.json; never stored in feature Parquet"
        metadata["target_tracking"] = cfg.get("tracking", {})

        # Graphs are a derived, non-authoritative visualization artifact. They
        # consume the already-written canonical feature table and never rerun
        # MediaPipe or alter feature values.
        graph_manifest = None
        if cfg.get("graphs", {}).get("enabled", True):
            try:
                graph_manifest = generate_angle_graphs(
                    final_df,
                    paths["output_dir"] / "Graphs",
                    exercise_id=optional_metadata.get("exercise_hint"),
                    feature_data_version=cfg.get("project", {}).get("processing_version"),
                    export_images=bool(cfg.get("graphs", {}).get("export_images", True)),
                )
                metadata["graph_manifest"] = graph_manifest.get("manifestPath")
            except Exception as graph_error:
                LOGGER.warning("Angle graph generation failed; feature processing remains valid: %s", graph_error)
                metadata["graph_generation_warning"] = f"{type(graph_error).__name__}: {graph_error}"

        manifest = {
            "schema_version": "1.1",
            "project": cfg.get("project", {}),
            **identifiers,
            "source_video": str(source_video),
            "processed_video": str(paths["processed_video_path"]),
            "landmarks_parquet": str(paths["landmarks_path"]),
            "features_parquet": str(paths["features_path"]),
            "metadata_json": str(paths["metadata_path"]),
            "quality_report_json": str(paths["quality_path"]),
            "video": {**video_info, "frame_count": len(final_df)},
            "processing": {
                "checkpoint_interval_frames": int(cfg.get("processing", {}).get("checkpoint_interval_frames", 300)),
                "resume_supported": True,
                "single_in_memory_feature_dataframe": True,
                "target_tracking": cfg.get("tracking", {}),
            },
            "label_separation": {
                "features_are_inputs_only": True,
                "annotation_source_of_truth": "annotations.json",
            },
            **feature_manifest,
        }

        _emit(progress_callback, 0.90, "Saving metadata, manifest, and quality report")
        save_json_atomic(metadata, paths["metadata_path"])
        save_json_atomic(manifest, paths["manifest_path"])
        save_json_atomic(quality_report, paths["quality_path"])

        _emit(progress_callback, 0.96, "Validating saved artifacts")
        validate_artifacts(
            source_video=source_video,
            processed_video=paths["processed_video_path"],
            landmarks_path=paths["landmarks_path"],
            features_path=paths["features_path"],
            metadata_path=paths["metadata_path"],
            manifest_path=paths["manifest_path"],
            quality_path=paths["quality_path"],
        )

        state.status = "completed"
        state.stage = "completed"
        state.error = None
        state.checkpoint_chunks = []
        state.next_frame = len(final_df)
        state.persisted_frames = len(final_df)
        state.save(paths["state_path"])
        _cleanup_checkpoints(paths["checkpoint_dir"])
        _emit(progress_callback, 1.0, "Processing complete")

        return ProcessingResult(
            output_dir=output_dir,
            landmarks_path=paths["landmarks_path"],
            features_path=paths["features_path"],
            processed_video_path=paths["processed_video_path"],
            metadata_path=paths["metadata_path"],
            feature_manifest_path=paths["manifest_path"],
            quality_report_path=paths["quality_path"],
            processing_state_path=paths["state_path"],
        )

    except InterruptedError:
        raise
    except Exception as exc:
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"
        state.save(paths["state_path"])
        LOGGER.exception("Video processing failed")
        raise
