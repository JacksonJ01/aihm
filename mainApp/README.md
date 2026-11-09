# AIHuMo

AIHuMo is a modular computer-vision and machine-learning system for exercise recognition, repetition analysis, movement-phase detection, form analysis, and future real-time inference.

The [GitHub releases page](https://github.com/JacksonJ01/aihm/releases)
provides portable Windows x64, macOS Intel x64, macOS Apple Silicon arm64, and
Linux x64 downloads. See the
[platform packaging guide](AI%20Humo%20EXE%20pipeline/README.md) to choose a
download or build it from source.

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

Overlapping windows stay with their recording. When participant IDs are complete,
all recordings for a participant stay in one split. A manifest with some
participant IDs missing must be corrected before export. Legacy manifests
without participant IDs use session grouping.

Window resampling interpolates between adjacent finite observations with a
detected pose. It uses the model's existing zero fill for unavailable inputs,
including tracking gaps and source intervals longer than three nominal frame
intervals. The native feature Parquet retains its missing values and source
timestamps.

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
The launcher, both Mode 0 dialogs, Mode 1, and the graph viewer open maximized
with the operating system's title bar and window controls. Use **Back to menu**
in Mode 1 or the graph viewer to return to the launcher.
In Mode 1, **Interactive Graph Viewer** opens a preview at the annotation's
current recording and frame and carries over **Display Overlay**.
**Back to annotation** returns to Mode 1. In the launcher-opened viewer,
**Open annotations** opens the matching recording in Mode 1 at the graph frame.
**Back to graph viewer** returns to that linked viewer. Escape also goes back
in the graph viewer. Launcher graph resume progress is separate.

Use **Angles**, **Landmarks**, or **Distances** in **Joint traces** to configure
each set independently. The landmark list contains the left and right toe
index, ankle, knee, hip, shoulder, elbow, wrist, and hand index. Each
selection applies to its graphs in individual and combined views.
Turn on **Display Overlay** to see angle values beside the joints. In Mode 1,
the default overlay shows the left and right elbow, shoulder, hip, and knee
angles when available. **Mirror selected graph angles** uses the graph's
default checked traces and angle source immediately. If you change them in
the graph preview, the overlay uses that selection after you return to Mode 1.
Mirrored labels match the graph's trace colors. Angle labels start hidden in
both workspaces.

**Source values** defaults to **Torso-normalized 2D** when available. Mode 0
scales X by video width and Y by video height before calculating angles in
the video plane. These can be foreshortened when a limb moves toward the
camera. **Estimated world (3D)** uses MediaPipe's monocular, hip-relative
world XYZ estimates. **Legacy (normalized image)** uses the original
normalized image XYZ angles and normalized XY torso tilt.

Choose **Show All Graphs** under **Graph view** for angles, movement, and
distances on one screen. **Show All** beside **Source values** compares
sources in any view. With both controls on, scroll through the separated
source groups inside the plot area. Use **Shift+scroll** to zoom in this
combined view. Plots share elapsed time and the green video playhead.
Movement can show individual components, overlaid XY or XYZ, and a speed
strip with its own scale. **Frame points** starts off.

Mode 0 stores legacy image, estimated world 3D, and torso-normalized 2D
measurements in the same feature Parquet. Torso-normalized XY uses the hip
midpoint as the origin and the projected shoulder-to-hip length as the scale.
The comparison mean uses three valid angles from the same native frame.
Mean position averages hip-relative XY after scaling each source by its
shoulder-to-hip length in XY. Velocity and acceleration use consecutive
native timestamps from that mean position. The viewer reads the saved
values from Parquet.
The graph menu also offers **Landmark movement** for left and right
positions or speed, and **Landmarks Distances** for the spacing between
elbows, wrists, knees, and ankles, plus shoulder-to-wrist and hip-to-ankle
distances on each side. Use **Frame measurements** to inspect saved readings
for a single frame. **Frame Details** groups the selected source's angle,
motion, distance, signed distance-rate, and distance-acceleration readings.
Mean-source distances use the saved torso-normalized mean XY positions.
Distance derivatives use native frame timestamps. Missing features remain
unavailable until prepared.

Choose **Prepare existing recording** in the launcher to add these columns
from saved landmarks. Select the feature Parquet and matching skeleton video.
The same preparation is available from the command line:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe scripts/prepare_viewer_features.py --features <feature-parquet> --video <skeleton-mp4>
```

Preparation keeps a backup of the feature file and leaves the videos and
annotations intact. Both viewers have separate controls for the skeleton,
saved midpoint centerline, and angle labels. If the saved source video
cannot be verified, a baked skeleton video remains visible. Variable-rate
clean sources use the saved frame timestamps for accurate seeks. During playback,
the viewers preload up to 48 frames ahead and 16 behind, within a memory
limit. In Mode 2 the selected camera targets 50 frames ahead and 50 behind
within a 640 MiB decoded-frame budget. The two most recently viewed cameras
reuse their loaded graph data and plots while the alignment and files match.
The player draws the current frame in each visible camera pane and follows
the source clock as frames become available. The graph renders the next zoomed
window in the background. It swaps in the finished plot and draws the live
cursor over it. If the render is still in progress, the video can continue
while the graph holds its current window.
You can still step to every native frame when annotating.
Tap the frame or jump buttons to move once. Hold a button for three seconds
to play in its direction, then release to pause. The frame buttons hold at
normal speed. Play and held jump buttons use the selected playback multiplier.
Switching review windows pauses playback and graph pre-rendering in the
previous workspace. Linked windows catch up to the current frame when you
return, with playback paused and annotation drafts still open.

The default dataset input selection uses legacy angles for compatibility.
To select the saved spatial angles for a new experiment, set
`features.model_angle_spaces` to `["2d"]`, `["3d"]`, or `["2d", "3d"]`
in the experiment's config. Use recordings with the requested families
stored in their Parquet. The standalone feature builder gets source
dimensions from the recording metadata or from `--width` and `--height`.

Zoom with the mouse wheel, toolbar, or **+** and **−** buttons. The
**Detail window** readout shows the visible time range and duration.
At close zoom, **Frame points** displays the
native frame samples. Hover near a trace to inspect its closest sample.
Move away to see the last inspected joint at the current video frame.
The Frame Details card reserves its height at the current viewer width.
The card marks missing samples as unavailable. When valid samples are
available, it also shows saved landmark coordinates and motion. World
coordinates are relative to the hips.
The video frame and vertical graph cursor stay linked. Click the plot to seek
to the closest native frame, or pan the Interactive Graph Viewer to seek to
the center of that view. **Zoom to Seek** starts off, so zoom stays
anchored to the current video frame at the green playhead. Turn it on to
seek to the timestamp under the pointer while zooming over a plot.
Click **Zoom at Playhead** to restore the default. The
**+ / −** buttons always use the selected frame. When all graph and source
groups are visible, use **Shift+scroll** to zoom and regular scrolling to
move through the panels.
In both workspaces, Left/Right step one frame and Up/Down jump by the
editable **Jump** value. The launcher **Settings** sets the starting value
for new windows, initially 50 frames. A graph preview opened from Mode 1
starts with that annotation window's current Jump value. Use Tab to move
keyboard focus between controls. Both workspaces have **Play/Pause** between
the frame-step buttons and use the saved source timestamps for playback.
Static PNG exports use the configured
`graphs.export_dpi` value (220 by default).

The launcher has one **Resume** section for the selected mode. Click a
Mode 1–5 tile to update **Resume**, or double-click it to open the workflow.
Use the trash icon next to **Resume** to remove the selected history entry
while keeping its files on disk. Open it manually to add it to **Resume** again.
On a focused tile, Space selects and Enter opens. Hover over
the Mode 0 tile to choose **New Video** or **Video Batch**. Mode 0 resume
restores the processing inputs so the existing recovery flow can reopen the
job. Mode 1 resumes from the annotation file's saved progress, and Mode 2
reopens a saved alignment. Modes 3 and 4 keep separate video and feature
Parquet histories with their last viewed frames.

**Mode 3 — Interactive Graph Viewer (2D)** shows the timeline graphs.
**Mode 4 — Interactive Graph Viewer (3D)** opens a pose synchronized to
the video frame. Left-drag on the world pose or its top-right orientation
cube to rotate it during playback. Click a cube face, edge, or corner to
snap to that view, or use the six signed axis buttons for a straight-on view.
Use **Rotate** to return to rotation after using toolbar pan or zoom. The wheel, zoom
buttons, and toolbar zoom around the displayed pose and keep the same frame.
Use **Pose source**
to switch to saved XY landmarks, or **Timeline graphs** to inspect the
same time-series charts as Mode 3.

In Mode 1, press **W** at the start of a new range, move to the end, and press
**S** to save it. A click in the **Temporal annotations** table selects a row.
Press **A** or **Edit selected** to load it for editing, then **S** to update it.
Press **D** or **Cancel edit** to discard the edit and clear the selection.
Use the on-screen buttons when a text field has keyboard focus.

In launcher **Settings**, choose colors for the selected workflow and the
skeleton lines and joints rendered by Mode 0. A rendered
MP4 retains the colors it was created with. Add participant IDs in Settings
or use **Save participant** beside the editable picker in either Mode 0 dialog.
An optional default participant is prefilled when those dialogs open.

Open **Mode 2 — Session Alignment** to process two to four Mode 0 recordings
or load an alignment JSON. Mode 2 matches the available saved angle traces
on a shared timeline in seconds, using the shortest recording as its
reference. The video area shows two cameras side by side, or a two-by-two
grid for three or four cameras. The selection outline follows the video
edges. Click anywhere in a camera tile to switch the annotation table,
timing controls, and Interactive Graph Viewer to that camera. The camera view dropdown switches between **Show Multi View**
and **Maximize Selected** in both windows while keeping the same playhead.
The **Play/Pause** button in the player controls all cameras. The shared
session scrubber and time readout sit directly above the playback buttons.
Trim and selected camera timing controls sit below the buttons.
**Compare all cameras** opens a joint-angle overlay on the
shared timeline that follows the active player and uses the same zoom controls.

Use **All aligned cameras** to save a new annotation into each recording's
native annotation file, with its own frame numbers and source timestamps.
Use **Selected camera only** for view-specific issues. Editing or deleting
an existing row changes the selected recording.

The temporal annotation table follows the editor's selected layer. Enable
**Show all layers** to see the full table. The **Form interval** layer can
store a form rating and any issue details or affected joints.

The saved alignment references the original files and records each camera's
native frame range. **Export trimmed clips** writes separate skeleton MP4
copies for the cameras that need trimming and keeps the shortest recording
whole. MP4 copies use each video's nominal frame rate and contain no audio.
Use the alignment JSON for the original per-frame timing and clock correction.

A `Model Suite — Mode 5` placeholder is also present. It lists
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
