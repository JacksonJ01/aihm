import type { JointAngleKey, JointAngles } from "@/lib/pose";
import type { JointAngleDynamics } from "@/lib/session-schema";

export const JOINT_ANGLE_KEYS: JointAngleKey[] = [
  "leftElbow",
  "rightElbow",
  "leftShoulder",
  "rightShoulder",
  "leftHip",
  "rightHip",
  "leftKnee",
  "rightKnee",
];

/**
 * Compute per-joint velocity (deg/s) from two consecutive angle snapshots.
 * Returns null for any joint where either frame's angle was null,
 * or when the time delta is non-positive.
 */
export function computeVelocities(
  currentAngles: JointAngles,
  previousAngles: JointAngles | null,
  currentTimestampMs: number,
  previousTimestampMs: number | null,
): JointAngleDynamics {
  if (previousAngles === null || previousTimestampMs === null) {
    return Object.fromEntries(JOINT_ANGLE_KEYS.map((k) => [k, null]));
  }

  const dtMs = currentTimestampMs - previousTimestampMs;
  if (dtMs <= 0) {
    return Object.fromEntries(JOINT_ANGLE_KEYS.map((k) => [k, null]));
  }

  const dtSec = dtMs / 1000;

  return Object.fromEntries(
    JOINT_ANGLE_KEYS.map((key) => {
      const curr = currentAngles[key];
      const prev = previousAngles[key];
      const value = curr !== null && prev !== null ? (curr - prev) / dtSec : null;
      return [key, value];
    }),
  );
}

/**
 * Compute per-joint acceleration (deg/s²) from two consecutive velocity snapshots.
 * Returns null for any joint where either velocity was null,
 * or when the time delta is non-positive.
 */
export function computeAccelerations(
  currentVelocities: JointAngleDynamics,
  previousVelocities: JointAngleDynamics | null,
  currentTimestampMs: number,
  previousTimestampMs: number | null,
): JointAngleDynamics {
  if (previousVelocities === null || previousTimestampMs === null) {
    return Object.fromEntries(JOINT_ANGLE_KEYS.map((k) => [k, null]));
  }

  const dtMs = currentTimestampMs - previousTimestampMs;
  if (dtMs <= 0) {
    return Object.fromEntries(JOINT_ANGLE_KEYS.map((k) => [k, null]));
  }

  const dtSec = dtMs / 1000;

  return Object.fromEntries(
    JOINT_ANGLE_KEYS.map((key) => {
      const curr = currentVelocities[key] ?? null;
      const prev = previousVelocities[key] ?? null;
      const value = curr !== null && prev !== null ? (curr - prev) / dtSec : null;
      return [key, value];
    }),
  );
}

/**
 * Compute range-of-motion stats over a window of angle arrays.
 * Returns { mean, variance, peakToPeak } per joint, all null if fewer than 2 frames.
 */
export function computeRangeStats(frames: { angles: JointAngles }[]) {
  const result: Record<string, { mean: number | null; variance: number | null; peakToPeak: number | null }> = {};

  for (const key of JOINT_ANGLE_KEYS) {
    const values = frames.map((f) => f.angles[key]).filter((v): v is number => v !== null);

    if (values.length < 2) {
      result[key] = { mean: null, variance: null, peakToPeak: null };
      continue;
    }

    const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
    const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length;
    const peakToPeak = Math.max(...values) - Math.min(...values);

    result[key] = {
      mean: Math.round(mean * 100) / 100,
      variance: Math.round(variance * 100) / 100,
      peakToPeak: Math.round(peakToPeak * 100) / 100,
    };
  }

  return result;
}
