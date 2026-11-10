import type { JointAngleKey, JointAngles, PoseLandmark } from "@/lib/pose";

// ---------------------------------------------------------------------------
// Per-frame record captured during a live session
// ---------------------------------------------------------------------------

export type JointAngleDynamics = Partial<Record<JointAngleKey, number | null>>;

export type FrameRecord = {
  frameIndex: number;
  timestampMs: number;
  posePresent: boolean;
  poseScore: number | null;
  angles: JointAngles;
  velocities: JointAngleDynamics;       // deg/s, null when angle was missing
  accelerations: JointAngleDynamics;    // deg/s², null when velocity was missing
  /** All 33 raw MediaPipe Pose landmarks — present when dataset capture is active. */
  landmarks?: PoseLandmark[];
};

// ---------------------------------------------------------------------------
// Session-level metadata (mirrors LoggedWorkoutParams from workoutsSession)
// ---------------------------------------------------------------------------

export type SessionIncludedChannels = {
  angles: boolean;
  velocities: boolean;
  accelerations: boolean;
  rangeStats: boolean;
  interJointDistances: boolean;
  globalFeatures: boolean;
};

export type SessionMetadata = {
  schemaVersion: 4;
  sessionId: string;
  recordedAt: string;         // ISO-8601
  durationSeconds: number;
  frameCount: number;
  exerciseKey: string;
  cameraViewpoint: string;
  movementSpeed: string;
  formQuality: string;
  recordingLengthSeconds: number;
  setNumber: number;
  repTarget: number;
  subjectId: string;
  includedChannels: SessionIncludedChannels;
};

// ---------------------------------------------------------------------------
// Full exported session document
// ---------------------------------------------------------------------------

export type SessionChannelArrays = {
  timestampsMs: number[];
} & Partial<Record<string, (number | null)[]>>;

export type SessionDocument = {
  metadata: SessionMetadata;
  data: SessionChannelArrays;
};
