import { calculateJointAngle, type PoseLandmark } from "@/lib/pose";
import type { FrameRecord } from "@/lib/session-schema";
import type { FrameData, JointAngleData, LandmarkData } from "./types";

// ─── Extended angle definitions ───────────────────────────────────────────────
// MediaPipe Pose landmark indices used for the 4 angles beyond the core 8.
// Wrist angle:  elbow → wrist → index finger tip
// Ankle angle:  knee  → ankle → foot index
const EXTENDED_ANGLE_DEFS: Array<{
  key: keyof Pick<JointAngleData, "leftWrist" | "rightWrist" | "leftAnkle" | "rightAnkle">;
  indices: [number, number, number];
}> = [
  { key: "leftWrist",   indices: [13, 15, 19] }, // leftElbow  → leftWrist  → leftIndex
  { key: "rightWrist",  indices: [14, 16, 20] }, // rightElbow → rightWrist → rightIndex
  { key: "leftAnkle",   indices: [25, 27, 31] }, // leftKnee   → leftAnkle  → leftFootIndex
  { key: "rightAnkle",  indices: [26, 28, 32] }, // rightKnee  → rightAnkle → rightFootIndex
];

const VISIBILITY_THRESHOLD = 0.35;

// ─── Landmark conversion ──────────────────────────────────────────────────────

export function toLandmarkData(lm: PoseLandmark): LandmarkData {
  return {
    x: Math.round(lm.x * 1e6) / 1e6,
    y: Math.round(lm.y * 1e6) / 1e6,
    z: Math.round(lm.z * 1e6) / 1e6,
    visibility: Math.round((lm.visibility ?? 0) * 1e6) / 1e6,
  };
}

// ─── Extended angle computation ───────────────────────────────────────────────

function computeExtendedAngles(
  landmarks: PoseLandmark[],
): Pick<JointAngleData, "leftWrist" | "rightWrist" | "leftAnkle" | "rightAnkle"> {
  const result = {
    leftWrist:  null as number | null,
    rightWrist: null as number | null,
    leftAnkle:  null as number | null,
    rightAnkle: null as number | null,
  };

  for (const def of EXTENDED_ANGLE_DEFS) {
    const [ai, bi, ci] = def.indices;
    const pa = landmarks[ai];
    const pb = landmarks[bi];
    const pc = landmarks[ci];
    if (
      pa && pb && pc &&
      (pa.visibility ?? 0) >= VISIBILITY_THRESHOLD &&
      (pb.visibility ?? 0) >= VISIBILITY_THRESHOLD &&
      (pc.visibility ?? 0) >= VISIBILITY_THRESHOLD
    ) {
      result[def.key] = calculateJointAngle(pa, pb, pc);
    }
  }

  return result;
}

// ─── Frame conversion ─────────────────────────────────────────────────────────

/**
 * Convert one FrameRecord (live buffer entry from usePose) into a FrameData
 * record ready for JSONL storage.
 *
 * The conversion:
 * - maps raw PoseLandmark[] → LandmarkData[] (normalised precision)
 * - merges core 8 angles with 4 extended angles (wrist + ankle)
 * - preserves pre-computed velocity and acceleration channels
 */
export function frameRecordToFrameData(record: FrameRecord): FrameData {
  const rawLandmarks = record.landmarks ?? [];
  const landmarks: LandmarkData[] = rawLandmarks.map(toLandmarkData);

  const extended =
    rawLandmarks.length >= 33
      ? computeExtendedAngles(rawLandmarks)
      : { leftWrist: null, rightWrist: null, leftAnkle: null, rightAnkle: null };

  const angles: JointAngleData = {
    leftElbow:     record.angles.leftElbow,
    rightElbow:    record.angles.rightElbow,
    leftShoulder:  record.angles.leftShoulder,
    rightShoulder: record.angles.rightShoulder,
    leftHip:       record.angles.leftHip,
    rightHip:      record.angles.rightHip,
    leftKnee:      record.angles.leftKnee,
    rightKnee:     record.angles.rightKnee,
    leftWrist:     extended.leftWrist,
    rightWrist:    extended.rightWrist,
    leftAnkle:     extended.leftAnkle,
    rightAnkle:    extended.rightAnkle,
  };

  return {
    frame: record.frameIndex,
    timestamp: Math.round((record.timestampMs / 1000) * 1000) / 1000,
    posePresent: record.posePresent,
    poseScore: record.poseScore,
    landmarks,
    angles,
    velocities: record.velocities,
    accelerations: record.accelerations,
  };
}

/** Convert the full frame buffer into FrameData array for API submission. */
export function frameBufferToFrameData(records: FrameRecord[]): FrameData[] {
  return records.map(frameRecordToFrameData);
}
