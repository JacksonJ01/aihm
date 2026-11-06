// ─── Landmark ────────────────────────────────────────────────────────────────

/** One of MediaPipe Pose's 33 normalized landmarks. */
export type LandmarkData = {
  x: number;          // normalized [0, 1] horizontal
  y: number;          // normalized [0, 1] vertical
  z: number;          // depth relative to hips (negative = toward camera)
  visibility: number; // model confidence [0, 1]
};

// ─── Joint Angles ─────────────────────────────────────────────────────────────

/**
 * All 12 joint angles captured per frame.
 * Core 8: elbow, shoulder, hip, knee (both sides).
 * Extended 4: wrist, ankle (both sides) — computed from landmarks 13-32.
 */
export type JointAngleKey12 =
  | "leftElbow"    | "rightElbow"
  | "leftShoulder" | "rightShoulder"
  | "leftHip"      | "rightHip"
  | "leftKnee"     | "rightKnee"
  | "leftWrist"    | "rightWrist"
  | "leftAnkle"    | "rightAnkle";

export type JointAngleData = Record<JointAngleKey12, number | null>;

// ─── Frame ───────────────────────────────────────────────────────────────────

/**
 * One frame of data, serialized as a single JSON line in frames.jsonl.
 * Arrays are synchronized: frame N at the same index across all channels.
 */
export type FrameData = {
  frame: number;               // 0-based index within recording
  timestamp: number;           // seconds from recording start
  posePresent: boolean;
  poseScore: number | null;    // mean landmark visibility across exercise joints
  landmarks: LandmarkData[];   // all 33 MediaPipe Pose landmarks
  angles: JointAngleData;      // 12 joint angles (deg)
  velocities: Partial<Record<JointAngleKey12, number | null>>;   // deg/s
  accelerations: Partial<Record<JointAngleKey12, number | null>>; // deg/s²
};

// ─── Included Channels ───────────────────────────────────────────────────────

export type IncludedChannels = {
  angles: boolean;
  velocities: boolean;
  accelerations: boolean;
  rangeStats: boolean;
  interJointDistances: boolean;
  globalFeatures: boolean;
};

// ─── Recording Metadata ──────────────────────────────────────────────────────

/**
 * Stored as metadata.json inside each recording folder.
 * Also summarised as one row in AIHM_Dataset/metadata.csv.
 */
export type RecordingMetadata = {
  recording_id: string;       // e.g. "R0001" — unique across all exercises
  exercise: string;           // display label, e.g. "Squat"
  exerciseKey: string; // folder-safe key (camelCase or custom slug)
  subject: string;
  camera_angle: string;       // "left" | "center" | "right"
  camera_height: string;      // "high" | "mid" | "low"
  speed: string;              // "slow" | "normal" | "fast"
  form: string;               // "good" | "bad" | "alternate"
  fps: number;                // computed from real frame timestamps
  duration: number;           // seconds
  set_number: number;
  rep_target: number;
  save_mp4: boolean;
  frame_count: number;
  included_channels: IncludedChannels;
  timestamp: string;          // ISO-8601 recording start time
  status: "complete" | "partial";
};

// ─── Session / Repetition (future hierarchy) ─────────────────────────────────

/** Grouping of multiple recordings in one gym session. */
export type SessionInfo = {
  session_id: string;
  subject: string;
  start_time: string;       // ISO-8601
  recording_ids: string[];
};

/** Frame range for a single repetition within a recording. */
export type RepetitionMarker = {
  rep_number: number;
  start_frame: number;
  end_frame: number;
  start_timestamp: number;  // seconds
  end_timestamp: number;    // seconds
  peak_frame?: number;      // frame of maximum contraction
};

// ─── API Request / Response shapes ───────────────────────────────────────────

export type CreateRecordingRequest = {
  metadata: Omit<RecordingMetadata, "recording_id" | "timestamp" | "status">;
};

export type CreateRecordingResponse = {
  recording_id: string;
  folder: string;
};

export type AppendFramesRequest = {
  frames: FrameData[];
};

export type AppendFramesResponse = {
  appended: number;
  total_frames: number;
};

export type FinalizeRecordingResponse = {
  recording_id: string;
  frame_count: number;
  duration: number;
  fps: number;
  path: string;
};

export type RecordingSummary = Pick<
  RecordingMetadata,
  "recording_id" | "exercise" | "exerciseKey" | "subject" | "status" | "frame_count" | "timestamp"
>;
