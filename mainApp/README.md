# AIHuMo

AIHuMo is a modular computer-vision and machine-learning system for exercise recognition, repetition analysis, movement-phase detection, form analysis, and future real-time inference.

## Version 0.4 architecture

```text
Source Video
    ↓
Mode 0 — Process New Video
    ├── video inspection
    ├── MediaPipe Pose
    ├── crash-safe raw-landmark checkpoints
    ├── ONE in-memory frame DataFrame
    │     ├── raw landmarks
    │     ├── world landmarks
    │     ├── normalized landmarks
    │     ├── angles
    │     ├── distances
    │     ├── velocity
    │     └── acceleration
    ├── skeleton MP4
    ├── final feature Parquet
    └── metadata / manifest / quality report
    ↓
Mode 1 — Annotation Studio
    ├── manually labeled activity-state segments
    │     ├── idle
    │     ├── transition
    │     └── active
    ├── repetition ranges
    ├── phase ranges
    ├── form labels / scores
    └── atomic annotations.json source of truth
    ↓
Dataset Builder
    ├── labels remain separate from feature Parquet
    ├── configurable target selection
    ├── participant/session-aware splits
    ├── fixed model FPS
    └── fixed-shape temporal windows
    ↓
Train / Validation / Test
    ↓
Multi-task Temporal Model
    ├── activity_state
    ├── exercise
    ├── phase
    ├── rep_boundary
    ├── form_label
    └── form_score
    ↓
Evaluation
    ↓
Future real-time inference
```


## Optional target participant tracking (v0.5)

The default processing mode is now `tracking.mode = "single_pose"`. It uses
MediaPipe's regular pose result independently on each frame and does not create
or maintain a subject-search bounding box. This avoids locking the workout to a
stale hand or person location. The multi-person target-association tracker is
preserved but disabled; enable it explicitly with
`tracking.enabled = true` and `tracking.mode = "target_association"` only when
that workflow is desired.

Mode 0 can now establish and maintain a participant identity within a recording without requiring a YOLO/Ultralytics dependency. MediaPipe is configured for multiple pose candidates and `src/aihumo/tracking.py` performs lightweight identity association using predicted motion, bounding-box overlap, scale, pose shape, and an optional HSV appearance signature.

The tracker automatically selects a primary participant from persistent candidates. It does **not** perform face recognition and does not claim to know the participant's real-world identity. Its job is identity continuity within the recording.

The critical safety rule is:

> AIHuMo never silently replaces an occluded/lost target with another person's pose.

Frames during an occlusion are recorded with target tracking status and missing target landmarks rather than contaminating the movement data with a passerby's pose. When the original target is found again, the tracker records `reacquired`.

Per-frame tracking metadata includes `target_track_id`, `target_confidence`, `target_status`, `pose_confidence`, `detected_pose_count`, `occlusion_ratio`, `reacquisition_flag`, and target bounding-box coordinates. These are quality/control fields and are not automatically model inputs.

Tracking state is stored in crash-recovery checkpoints, so a resumed Mode 0 job continues the same identity instead of restarting the tracker at the checkpoint boundary.

The full authoritative logic is documented in [AiHuMo_Pipe](AiHuMo_Pipe.md).

## Core design decisions

The final feature DataFrame is constructed in memory and written once to one canonical combined feature Parquet through an Arrow table. The pipeline does not repeatedly reopen, merge, or create one Parquet file per feature category. Temporary raw-landmark checkpoint chunks are allowed for crash recovery and are removed after successful completion. If duplicate feature Parquets are found for the same video, processing stops with their paths instead of choosing one silently.

The original video is never overwritten. The processed skeleton MP4 is a separate artifact.

Feature Parquet is input data only. Annotation JSON is the ground-truth source of truth. Derived annotation Parquet, repetition summaries, and repetition-detection suggestions can be regenerated from that source and are not authoritative.

Activity state is annotated manually. Repetition detection is currently a deterministic, human-reviewable suggestion tool rather than an automatic source of truth.

## Repository

```text
src/aihumo/
    annotations.py        annotation schema, persistence, target projection
    config.py             configuration loading
    dataset.py             PyTorch datasets
    dataset_builder.py    experiment dataset construction
    evaluate.py            multi-task evaluation metrics
    features.py            FeatureEngine
    geometry.py            mathematical geometry
    metadata.py            recording metadata
    model.py               temporal CNN + multi-task heads
    pose.py                MediaPipe + video inspection
    processing.py          end-to-end Mode 0 orchestration
    processing_state.py    crash-safe processing state and fingerprints
    quality.py             pose/feature quality reporting
    rep_detection.py       sliding-window repetition suggestions
    scaling.py             train-only feature normalization
    splits.py              participant/session-aware split logic
    storage.py             atomic JSON/Parquet persistence
    validation.py          frame/artifact validation
    windowing.py           fixed model-FPS temporal windows

app/
    AIHuMoDataStudio.py
    mode0_process.py
    mode1_annotation.py
    common.py

configs/config.json
scripts/
    process_video.py
    build_video_manifest.py
    build_dataset.py
    train.py
    evaluate.py
```

## Recording artifact layout

```text
data/processed/S001/V001/
    video/V001_skeleton.mp4
    parquet/V001_landmarks.parquet
    parquet/V001_features.parquet
    metadata/V001_metadata.json
    metadata/V001_feature_manifest.json
    metadata/V001_quality_report.json
    annotations/V001_annotations.json
    annotations/V001_annotations.parquet
    annotations/V001_rep_summary.json
    annotations/V001_rep_suggestions.json
    .processing/processing_state.json
```

`.processing/landmarks/` contains temporary checkpoint chunks while a Mode 0 job is incomplete.

## Mode 0 — Process New Video

Mode 0 collects the required recording identifiers and source video, verifies inputs, processes pose data in a worker thread, and records an atomic processing state. A cancelled or interrupted job can resume when the source video, pose model, and configuration still match. Final artifacts are validated before the job is marked completed.

Quality reporting includes frame count, duration, pose-presence fraction, visibility summaries, and feature missingness. The generated quality report is saved beside the metadata and is also included in the processing result.

## Mode 1 — Annotation Studio

Mode 1 uses six explicit UI layers:

```text
Activity interval       broad exercise context: idle, transition, or active
  └─ Set interval        one set
      └─ Repetition interval
          └─ Phase interval (eccentric, concentric, or hold)
Form interval           sibling overlay for a bounded form/tracking observation
Other interval          setup, camera adjustment, unrelated activity, or reset
```

An Activity interval does not have to cover every frame. Gaps are valid when
the recording has not yet been classified; the studio reports them as a
warning. A setup block can therefore be saved as `general` (shown as Other
interval), followed later by Activity intervals for transition, active exercise,
or rest/idle. The initial no-pose setup detector uses this same Other interval
semantics and never fabricates exercise labels.

Form intervals are overlays rather than hierarchy parents. They can overlap a
repetition or phase and store an issue type, exercise-specific issue category,
and multiple affected joints. Fast-motion blur or landmark drift should be
recorded as a tracking-quality issue; it is not automatically treated as poor
exercise form.

Within the editor, every layer can change its boundary mode, activity state,
and notes. Activity, set, repetition, and phase controls are otherwise scoped
to their owning layer. Disabled controls show the effective inherited value
from the containing parent. The temporal table is re-sorted after each save as
Activity → Set → Repetition → Phase, with Form overlays placed under their
nearest hierarchy range. Set numbering is local to its Activity interval, so a
new Activity interval starts its set collection at 1.

The annotation hierarchy is represented by fields in a flat JSON document:

```text
participant
    ↓
session
    ↓
video
    ↓
activity_state segment
    ↓
set_id + rep_id
    ↓
phase
    ↓
form label / score
```

`annotation_id` identifies an annotation record. `segment_id` identifies its temporal segment. Repetition and set numbers are local identifiers; they are not treated as universal neural-network classes.

The JSON file is atomically written after every completed annotation. Annotation state records progress so the studio can reopen the recording near the last completed frame. The JSON remains authoritative even when a derived Parquet export fails.

## Model target selection

The model-training targets are selected in `configs/config.json` under `dataset.targets`. This is intentionally separate from the annotation truth so experiments can compare different outputs without changing the original annotations.

Example:

```json
"targets": {
  "activity_state": {
    "enabled": true,
    "trainable": true,
    "task": "sequence_classification"
  },
  "exercise": {
    "enabled": true,
    "trainable": true,
    "task": "classification"
  },
  "phase": {
    "enabled": true,
    "trainable": true,
    "task": "sequence_classification"
  },
  "rep_boundary": {
    "enabled": true,
    "trainable": true,
    "task": "sequence_binary"
  },
  "form_label": {
    "enabled": true,
    "trainable": true,
    "task": "classification"
  },
  "form_score": {
    "enabled": true,
    "trainable": true,
    "task": "regression"
  }
}
```

`rep_id` and `set_id` are retained as grouping/evaluation metadata but are not trainable classification heads.

The dataset manifest records the exact target configuration used for an experiment. The training checkpoint also records the effective target set, feature names, label mappings, configuration, and dataset manifest.

## Build the dataset

First create a video manifest from completed processing artifacts:

```powershell
$env:PYTHONPATH = "src"
python scripts/build_video_manifest.py --root . --output data/video_manifest.csv
```

Then build an experiment dataset:

```powershell
$env:PYTHONPATH = "src"
python scripts/build_dataset.py --root . --video-manifest data/video_manifest.csv
```

The dataset builder:

1. Loads immutable feature Parquet as model inputs.
2. Loads `annotations.json` as the ground-truth source.
3. Projects annotations to a temporary labeled frame table.
4. Generates overlapping temporal windows.
5. Resamples every window to the configured `model_fps` so different source FPS recordings have the same `[T, F]` shape.
6. Splits by participant when complete participant IDs are available; otherwise it falls back to session grouping.
7. Fits categorical label mappings using training windows only.
8. Writes experiment-specific NPZ/JSON artifacts without modifying the source feature Parquet.

## Train the model

```powershell
$env:PYTHONPATH = "src"
python scripts/train.py --root . --dataset-dir data/datasets/experiment_001
```

Training performs feature standardization using training data only, trains the enabled multi-task heads, uses early stopping based on validation loss, and saves the best checkpoint under:

```text
models/experiment_001/aihumo_multitask_best.pt
```

Training reports are written under:

```text
reports/experiment_001/
    training_history.json
    test_results.json
```

The model currently uses a shared temporal CNN backbone. Classification targets use classification heads, phase uses a sequence head, repetition uses a binary boundary sequence rather than rep-number classes, and form score uses a regression head.

## Evaluate a saved model

```powershell
$env:PYTHONPATH = "src"
python scripts/evaluate.py --root . --dataset-dir data/datasets/experiment_001 --checkpoint models/experiment_001/aihumo_multitask_best.pt
```

The evaluation script uses the saved checkpoint's target configuration and mappings so the reported results correspond to the model that was actually trained.

## Repetition detection

The baseline repetition analyzer is deliberately separate from the annotation truth.

```text
active segment
      ↓
rolling temporal window
      ↓
smoothed movement signal
      ↓
local period / frequency estimate
      ↓
local minima / maxima
      ↓
amplitude + prominence + cadence consistency
      ↓
rep candidates
      ↓
human review
```

Amplitude and frequency answer different questions: amplitude measures how far the movement travels, while frequency/period measures how often the cycle repeats. AIHuMo uses both rather than treating them as one quantity.

The suggestion file is written as `*_rep_suggestions.json` and never overwrites `annotations.json`.

## Window and data-split policy

The default model window is five seconds with one-second stride and a canonical model FPS of 30. At 30 FPS this is 150 time steps, but the number is derived from configuration rather than hard-coded.

Overlapping windows are never split across train/test by random row sampling. Grouped participant/session splitting prevents highly similar windows from the same person or recording from leaking into both training and evaluation.

## Validation and tests

Run:

```powershell
$env:PYTHONPATH = "src"
pytest -q
python -m compileall src app scripts
```

For a terminal report with the synthetic input, expected behavior, measured
output, and timing for each test, run from `mainApp` in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m pytest -q tests --pipeline-details
```

Install pytest with `.\.venv\Scripts\python.exe -m pip install pytest` if it
is missing. Add `-k "rep_detection or windowing"` to inspect a smaller group.
The report follows the normal pytest progress and failure tracebacks, and
uses synthetic fixtures instead of recordings from the project.

The local project tests cover geometry, feature generation, anatomical reference points, normalization, temporal derivatives, target tracking/occlusion behavior, annotation hierarchy/recovery, window resampling, repetition-signal analysis, processing-state compatibility, and frame validation.

MediaPipe, PyQt6, and PyArrow are runtime dependencies for the complete GUI/processing stack. They must be installed in the target environment before running Mode 0 or reading/writing Parquet through the GUI.

## Exercise catalog and Mode 0 angle graphs

The versioned starter catalog is provided by `src/aihumo/exercise_library.py`.
It contains the original 30-exercise starter catalog plus `Dips`, reusable
candidate form deviations, view-observability metadata, and exercise-specific
angle presets. Mode 1 presents linked PascalCase `Movement type` and `Exercise
name` dropdowns; selecting a movement type filters the available exercise names.
The catalog is annotation guidance only; it does not infer correctness from
angle thresholds.

When `graphs.enabled` is true in `configs/config.json`, Mode 0 generates
recording-scoped angle previews under `Graphs/` after the canonical feature
Parquet is written. Graphs use the existing `timestamp_s` and `angle_*`
columns, preserve missing observations as gaps, and write `graph_manifest.json`
with exercise/library and feature-data provenance. Unknown exercises fall back
to all available angle columns. A graph failure is logged as nonfatal and does
not invalidate the processed feature data.

Open **Interactive Graph Viewer** on the launcher and select the skeleton MP4
and its matching feature Parquet. The viewer opens a read-only workspace with
the video and frame controls on the left and the joint traces on the right.
The graph viewer and Mode 1 open maximized with the operating system's window
controls. Use **Back to menu** in either workspace to return to the launcher.
In Mode 1, **Interactive Graph Viewer** opens a preview at the annotation's
current recording and frame. **Back to annotation** returns to Mode 1.
Escape also goes back in the graph viewer. Launcher graph resume progress is separate.

Use the checkboxes in **Joint traces** to show or hide individual curves.
Turn on **Display Overlay** to see angle values beside the joints, using the
same colors as the visible traces. In Mode 1, the overlay starts with the
neck and hip-midpoint angles. Turn on **Mirror selected graph angles** to
use the traces and angle source selected in the graph preview opened from
Mode 1. The selection stays with the annotation window when you return
from the preview. Angle labels start hidden in both workspaces.

**Angle source** defaults to **Video plane (2D)** when available. Mode 0
scales X by video width and Y by video height before calculating angles in
the video plane. These can be foreshortened when a limb moves toward the
camera. **Estimated world (3D)** uses MediaPipe's monocular, hip-relative
world XYZ estimates. **Legacy (normalized image)** uses the original
normalized image XYZ angles and normalized XY torso tilt.

New recordings store `angle_2d_*`, `angle_3d_*`, and the existing
`angle_*` columns in the same feature Parquet. Mode 1 reads these
automatically for the midpoint overlay and the graph viewer. Both workspaces
can reconstruct missing families in memory for older recordings with the
required landmarks. Missing observations remain gaps.

The default dataset input selection uses legacy angles for compatibility.
To select the saved spatial angles for a new experiment, set
`features.model_angle_spaces` to `["2d"]`, `["3d"]`, or `["2d", "3d"]`
in the experiment's config. Use recordings with the requested families
stored in their Parquet. The standalone feature builder gets source
dimensions from the recording metadata or from `--width` and `--height`.

Zoom with the mouse wheel or toolbar, or set **Detail window** to `1.00 s`
and select **Zoom to window**. At close zoom, **Frame points** displays the
native frame samples. Hover near a trace to inspect its closest sample.
Move away to see the last inspected joint at the current video frame.
The card marks missing samples as unavailable. When valid samples are
available, it also shows landmark coordinates and motion calculated from
consecutive samples. World coordinates are relative to the hips.
The video frame and vertical graph cursor stay linked. Click the plot to seek
to the closest native frame, or pan to a new part of the recording to seek to
the center of that view. Zoom keeps the frame selected if it is still visible.
In both workspaces, Left/Right step one frame and Up/Down jump by the
editable **Jump** value. The launcher **Settings** sets the starting value
for new windows, initially 50 frames. A graph preview opened from Mode 1
starts with that annotation window's current Jump value. Use Tab to move
keyboard focus between controls. Both workspaces have **Play/Pause** between
the frame-step buttons and use the saved source timestamps for playback.
Static PNG exports use the configured
`graphs.export_dpi` value (220 by default).

The launcher has separate **Resume Mode 1 Annotation** and **Resume Interactive
Graph Viewer** lists. Graph resume reopens the saved video and feature Parquet
at the last viewed frame. Annotation resume uses the annotation file's saved
progress.

In launcher **Settings**, choose colors for the selected workflow, the current
thumbnail, and the skeleton lines and joints rendered by Mode 0. A rendered
MP4 retains the colors it was created with. Add participant IDs in Settings
or use **Save participant** beside the editable picker in either Mode 0 dialog.
An optional default participant is prefilled when those dialogs open.

A `Model Lab — Mode 2` placeholder is also present. It lists
the planned 1D CNN, TCN, LSTM, ST-GCN, GCN, and DNN experiment families, but it
does not train or run a model yet.

The configured angle registry contains 15 angles: bilateral shoulder, elbow,
wrist, hip, knee, and ankle angles plus the existing
`torso_nose_shoulder_hip` angle and `torso_vertical`, and the midpoint-defined
`shoulder_midpoint_hip_midpoint_knee_midpoint` angle. The first special angle
is geometrically `nose → shoulder midpoint → hip midpoint` (the vertex is the
shoulder midpoint); the new angle is `shoulder midpoint → hip midpoint → knee
midpoint` (the vertex is the hip midpoint). The feature table also exposes
explicit `nose_*`, `shoulder_midpoint_*`, `hip_midpoint_*`,
`knee_midpoint_*`, and `ankle_midpoint_*` columns as named aliases over the
already calculated landmark arrays. The actual feature count is published in
the feature manifest; no historical total is treated as a schema invariant.

Mode 0 also has a `Process Session Folders` workflow. Each selected folder is
one session and every video is processed as its own recording. Participant ID,
date, environment, operator, and notes are shared metadata. The recording table
shows one row per video so camera ID and camera angle can be assigned separately
for multi-angle sessions; distinct camera IDs are generated by default and
obvious filename hints such as `front` or `side` are offered as defaults.
Session and video IDs are still generated separately so Parquet artifacts cannot
collide. In Mode 1, camera angle is editable only on the Activity interval; Set,
Repetition, Phase, and Form intervals inherit it for display.

The skeleton-overlay MP4 and the Mode 1 current-frame view draw the named
shoulder, hip, knee, and ankle midpoints, the nose-to-shoulder-to-hip geometry,
and the shoulder-to-hip-to-knee geometry. Mode 1 reads angle values from the
canonical feature Parquet when available; rendering does not rerun MediaPipe.

## Synthetic end-to-end smoke test

Run `python scripts/simulate_end_to_end.py` from `mainApp` to exercise the
MediaPipe-free path with generated landmarks. It validates feature generation,
canonical Parquet round-tripping, graph provenance, annotation save/reload,
frame-target projection, fixed-rate windows, participant grouping, and that
annotation persistence does not change the feature Parquet. The script uses a
temporary directory and does not touch project data.
