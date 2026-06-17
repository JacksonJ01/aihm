import type { FrameRecord, SessionChannelArrays, SessionDocument, SessionMetadata } from "@/lib/session-schema";
import { JOINT_ANGLE_KEYS } from "@/lib/angle-dynamics";
import { computeRangeStats } from "@/lib/angle-dynamics";

type ExportParams = {
  exerciseKey: string;
  cameraViewpoint: string;
  movementSpeed: string;
  formQuality: string;
  recordingLengthSeconds: number;
  setNumber: number;
  repTarget: number;
  subjectId: string;
  includeAngles: boolean;
  includeVelocity: boolean;
  includeAcceleration: boolean;
  includeRangeStats: boolean;
  includeInterJointDistances: boolean;
  includeGlobalFeatures: boolean;
};

/**
 * Build a SessionDocument from the live frame buffer and panel parameters.
 * Channel arrays are filtered by the includedChannels flags.
 */
export function buildSessionDocument(params: ExportParams, frames: FrameRecord[]): SessionDocument {
  const durationSeconds = frames.length > 0 ? frames[frames.length - 1].timestampMs / 1000 : 0;

  const metadata: SessionMetadata = {
    schemaVersion: 4,
    sessionId: crypto.randomUUID(),
    recordedAt: new Date().toISOString(),
    durationSeconds: Math.round(durationSeconds * 1000) / 1000,
    frameCount: frames.length,
    exerciseKey: params.exerciseKey,
    cameraViewpoint: params.cameraViewpoint,
    movementSpeed: params.movementSpeed,
    formQuality: params.formQuality,
    recordingLengthSeconds: params.recordingLengthSeconds,
    setNumber: params.setNumber,
    repTarget: params.repTarget,
    subjectId: params.subjectId,
    includedChannels: {
      angles: params.includeAngles,
      velocities: params.includeVelocity,
      accelerations: params.includeAcceleration,
      rangeStats: params.includeRangeStats,
      interJointDistances: params.includeInterJointDistances,
      globalFeatures: params.includeGlobalFeatures,
    },
  };

  const data: SessionChannelArrays = {
    timestampsMs: frames.map((f) => Math.round(f.timestampMs * 10) / 10),
  };

  // Core angle channels
  if (params.includeAngles) {
    for (const key of JOINT_ANGLE_KEYS) {
      data[key] = frames.map((f) => f.angles[key] ?? null);
    }
  }

  // Velocity channels
  if (params.includeVelocity) {
    for (const key of JOINT_ANGLE_KEYS) {
      const channelKey = `${key}Velocity`;
      data[channelKey] = frames.map((f) => {
        const v = f.velocities[key] ?? null;
        return v !== null ? Math.round(v * 100) / 100 : null;
      });
    }
  }

  // Acceleration channels
  if (params.includeAcceleration) {
    for (const key of JOINT_ANGLE_KEYS) {
      const channelKey = `${key}Acceleration`;
      data[channelKey] = frames.map((f) => {
        const a = f.accelerations[key] ?? null;
        return a !== null ? Math.round(a * 100) / 100 : null;
      });
    }
  }

  // ROM / stats — scalar summary per joint appended as metadata arrays of length 1
  if (params.includeRangeStats && frames.length > 1) {
    const stats = computeRangeStats(frames);
    for (const key of JOINT_ANGLE_KEYS) {
      data[`${key}Mean`] = [stats[key].mean];
      data[`${key}Variance`] = [stats[key].variance];
      data[`${key}PeakToPeak`] = [stats[key].peakToPeak];
    }
  }

  return { metadata, data };
}

/**
 * Trigger a client-side JSON download.
 * Filename is derived from exercise key and session ID prefix.
 */
export function downloadSessionJSON(doc: SessionDocument): void {
  const json = JSON.stringify(doc, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `session_${doc.metadata.exerciseKey}_${doc.metadata.sessionId.slice(0, 8)}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
