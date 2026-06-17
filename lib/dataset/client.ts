"use client";

/**
 * DatasetClient — browser-side API wrapper.
 *
 * Converts the live FrameRecord buffer → FrameData array, then drives the
 * three-step server pipeline:
 *   1. POST /api/dataset/recordings          → create folder + metadata.json
 *   2. POST /api/dataset/recordings/[id]/frames → write frames.jsonl
 *   3. POST /api/dataset/recordings/[id]/finalize → compute fps/duration, write CSV
 */

import type { FrameRecord } from "@/lib/session-schema";
import type { RecordingMetadata, FinalizeRecordingResponse } from "./types";
import { frameBufferToFrameData } from "./feature-extraction";

const FRAME_BATCH_SIZE = 100; // frames per POST to avoid oversized requests

export type DatasetSaveParams = Omit<
  RecordingMetadata,
  "recording_id" | "timestamp" | "status"
>;

export type DatasetSaveResult = {
  recording_id: string;
  frame_count: number;
  duration: number;
  fps: number;
  path: string;
};

/** Full save pipeline: create → append (batched) → finalize. */
export async function saveToDataset(
  params: DatasetSaveParams,
  frameBuffer: FrameRecord[],
): Promise<DatasetSaveResult> {
  if (frameBuffer.length === 0) {
    throw new Error("Frame buffer is empty — start the camera and record before saving.");
  }

  // ── Step 1: Create recording ────────────────────────────────────────────────
  const createRes = await fetch("/api/dataset/recordings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ metadata: params }),
  });

  if (!createRes.ok) {
    const err = await createRes.text();
    throw new Error(`Failed to create recording: ${err}`);
  }

  const { recording_id } = (await createRes.json()) as { recording_id: string };

  // ── Step 2: Convert buffer and append frames in batches ─────────────────────
  const frames = frameBufferToFrameData(frameBuffer);

  for (let offset = 0; offset < frames.length; offset += FRAME_BATCH_SIZE) {
    const batch = frames.slice(offset, offset + FRAME_BATCH_SIZE);

    const appendRes = await fetch(`/api/dataset/recordings/${recording_id}/frames`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        frames: batch,
        exerciseKey: params.exerciseKey,
      }),
    });

    if (!appendRes.ok) {
      const err = await appendRes.text();
      throw new Error(`Failed to append frames (offset ${offset}): ${err}`);
    }
  }

  // ── Step 3: Finalize ────────────────────────────────────────────────────────
  const finalizeRes = await fetch(
    `/api/dataset/recordings/${recording_id}/finalize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exerciseKey: params.exerciseKey }),
    },
  );

  if (!finalizeRes.ok) {
    const err = await finalizeRes.text();
    throw new Error(`Failed to finalize recording: ${err}`);
  }

  const result = (await finalizeRes.json()) as FinalizeRecordingResponse;

  return {
    recording_id: result.recording_id,
    frame_count: result.frame_count,
    duration: result.duration,
    fps: result.fps,
    path: result.path,
  };
}
