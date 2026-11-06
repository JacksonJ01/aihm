# AiHuMo_Pipe

**Authoritative AIHuMo pipeline and annotation guide**

## 1. Purpose

AIHuMo is a modular movement-analysis framework. The GUI is an interface to the pipeline, not the pipeline itself.

The authoritative processing path is:

```text
Participant
  -> Session
  -> Video
  -> Video metadata
  -> Person detection / target tracking
  -> MediaPipe Pose Landmarker
  -> Target raw landmarks
  -> AIHuMo anatomical reference points
  -> Body axes / geometry
  -> Configurable normalization
  -> Angles / distances
  -> Velocity / acceleration
  -> Validated frame feature table
  -> Feature Parquet
  -> Manual annotation JSON
  -> Dataset builder
  -> Participant/session-aware temporal windows
  -> Baseline temporal model
  -> Evaluation
  -> Future multi-task model
  -> Future real-time inference
```

## 2. Target-person tracking

### 2.1 Why tracking exists

Pose estimation answers **which pixels contain a plausible human pose**. It does not by itself establish that the pose belongs to the participant being analyzed.

AIHuMo therefore treats participant identity continuity as a separate acquisition problem.

The tracker does not perform face recognition and does not claim to know a person's real-world identity. It maintains an identity **within one recording**.

### 2.2 Target-selection logic

The default system automatically establishes a primary participant from persistent pose candidates. Initial selection scores combine:

- persistence across the warm-up interval
- relative person size
- distance from the image center
- pose completeness/quality

If several candidates are close in score, the result is marked `ambiguous`. The default configuration still selects the highest-scoring candidate, but the ambiguity is retained in the tracking metadata. A future GUI correction can replace the target before processing is considered dataset-ready.

### 2.3 Persistent tracking logic

For every frame:

```text
1. MediaPipe detects up to N pose candidates.
2. Convert each candidate into:
   - 33 landmark coordinates
   - bounding box
   - pose quality
   - optional appearance histogram
3. Predict the location of existing tracks using their recent motion.
4. Score candidate/track pairs using:
   - bounding-box IoU
   - predicted-center similarity
   - body-size similarity
   - pose-shape similarity
   - lightweight appearance similarity
5. Greedily accept the highest valid associations.
6. Create new non-target tracks for unmatched candidates.
7. If the target track is matched:
      TRACKED or REACQUIRED
8. If the target track is temporarily unmatched:
      PARTIALLY_OCCLUDED / OCCLUDED
9. If it remains unmatched beyond the configured limit:
      LOST
10. Never replace a missing target with another person's pose merely because
    that person's pose is more confident.
```

### 2.4 Tracking states

```text
SEARCHING
    Initial target has not been established.

TRACKED
    Target identity and pose are both currently supported.

PARTIALLY_OCCLUDED
    Target was not matched on a very short interval.

OCCLUDED
    Target remains temporarily missing but its identity is retained.

LOST
    Target has exceeded the normal occlusion interval.

REACQUIRED
    A candidate has matched the retained target identity after a gap.

AMBIGUOUS
    Initial candidate selection is insufficiently separated.
```

### 2.5 Safe-failure rule

This is a dataset-integrity rule:

> **AIHuMo must never silently switch the tracked participant to another person.**

If the participant is occluded or lost, AIHuMo writes missing target landmarks for those frames and records the tracking state. It does not insert a passerby's pose as if it belonged to the participant.

A short missing interval is therefore preferable to corrupted movement data.

### 2.6 Tracking data stored per frame

Tracking fields are quality/control metadata, not automatic model inputs:

```text
target_track_id
target_confidence
target_status
pose_confidence
detected_pose_count
occlusion_ratio
reacquisition_flag
target_selection_method
target_bbox_x1
target_bbox_y1
target_bbox_x2
target_bbox_y2
```

These fields remain in the frame table so processing quality can be audited later.

### 2.7 Recovery interaction

Tracking state is part of Mode 0 processing recovery. The crash-safe processing state stores the tracker state at each persisted landmark checkpoint. A resumed job therefore continues the same target identity instead of starting a new tracker at the checkpoint boundary.

## 3. Pose extraction

MediaPipe Pose Landmarker remains the pose-estimation backend.

The tracker may request multiple pose candidates. Only the selected target's pose is written as the target frame representation.

The frame table preserves:

```text
lm0_x ... lm32_z
lm0_visibility ... lm32_visibility
lm0_presence ... lm32_presence
world0_x ... world32_z
```

Missing MediaPipe values remain missing. They are never fabricated.

## 4. Anatomical reference points

AIHuMo derives the following points from the target landmarks:

```text
hip_center     = (left_hip + right_hip) / 2
shoulder_center = (left_shoulder + right_shoulder) / 2
torso_center   = (hip_center + shoulder_center) / 2
knee_center    = (left_knee + right_knee) / 2
ankle_center   = (left_ankle + right_ankle) / 2
```

`head_center` is optional.

These are AIHuMo-derived features, not MediaPipe landmarks.

## 5. Body geometry

The pipeline exposes:

```text
torso_vector       = shoulder_center - hip_center
lower_body_vector  = knee_center - hip_center
ankle_vector       = ankle_center - knee_center

shoulder_width     = ||left_shoulder - right_shoulder||
hip_width          = ||left_hip - right_hip||
combined_width     = (shoulder_width + hip_width) / 2
torso_length       = ||shoulder_center - hip_center||
```

Vector components, magnitudes, and temporal derivatives are available as features.

## 6. Normalization

Normalization is configurable and representations never overwrite each other.

Baseline:

```text
torso_center = (hip_center + shoulder_center) / 2
combined_width = (shoulder_width + hip_width) / 2
P_norm = (P - torso_center) / combined_width
```

Supported representations:

- torso + combined shoulder/hip width
- hip-centered + shoulder-width scale
- shoulder-centered + shoulder-width scale
- torso-centered + torso-length scale
- optional experimental body-aligned rotation

The current baseline preserves orientation.

The legacy `n{i}_{axis}` names are retained as a compatibility alias for the baseline torso/combined-width representation. New representations receive explicit namespaces such as `hip_norm_lm11_x` and `body_aligned_lm11_x`.

## 7. Temporal features

Velocity uses actual frame timestamps:

```text
v_t = (x_t - x_(t-1)) / (t_t - t_(t-1))
```

Acceleration is explicitly the derivative of velocity:

```text
a_t = (v_t - v_(t-1)) / (t_t - t_(t-1))
```

The first velocity sample and insufficient/invalid acceleration samples are `NaN`. Invalid time differences are never converted into fabricated values.

## 8. Feature dataset rule

Mode 0 creates one complete in-memory DataFrame, adds the configured feature families, validates it, and writes the final feature Parquet once.

Temporary landmark checkpoint Parquets are recovery artifacts only. They are not the feature-construction mechanism.

## 9. Annotation source of truth

`annotations.json` is authoritative ground truth.

Hierarchy:

```text
Participant
  -> Session
    -> Video
      -> Set
        -> Rep
          -> Phase / Form
```

Activity state is manually labeled as:

```text
idle
transition
active
```

Repetition detection produces candidates/suggestions only. It does not create ground-truth repetitions automatically.

## 10. Dataset construction

Dataset construction combines:

```text
final_features.parquet
+ annotations.json
+ dataset configuration
```

Targets are explicitly configured. `rep_id` and `set_id` remain local grouping identifiers and are not universal classification classes.

Temporal windows are configured by duration, stride, source/model FPS, overlap, and resampling. The five-second/150-frame case is a configuration example, not an implementation constant.

Primary train/validation/test splitting is participant/session/video aware.

## 11. Model boundary

The first baseline is a lightweight temporal model. The intended future architecture is:

```text
Shared temporal backbone
    -> Activity head
    -> Exercise head
    -> Phase head
    -> Repetition-boundary head
    -> Form label head
    -> Form score head
```

The model must not receive recording identifiers, annotation labels, or target-tracking metadata merely because those values exist in the frame table.

## 12. Validation requirements

Processing must fail loudly for:

- invalid source video
- invalid timestamps
- missing landmarks
- duplicate columns
- accidental `_x` / `_y` merge artifacts
- invalid target status
- tracked frames without target poses
- invalid configuration
- frame-count mismatch
- missing persisted artifacts
- unreadable Parquet/JSON

No `except: pass` is permitted for processing failures.

## 13. Provenance

Important artifacts should retain:

```text
source SHA-256
pose-model fingerprint
configuration hash
software version
Git commit when available
dataset version
processing timestamp
```

Hashing establishes byte-level identity; it does not establish semantic correctness.

## 14. Real-time compatibility

The target tracker, pose extraction, geometry, normalization, and feature engine are independent of PyQt6. The same configured preprocessing path can therefore be adapted to a rolling frame buffer for future live inference.
