/**
 * DatasetManager — server-side only (Node.js fs).
 * Call exclusively from Next.js API routes, never from client components.
 *
 * Folder layout:
 *   AIHM_Dataset/
 *     metadata.csv          ← one row per finalized recording
 *     {exerciseKey}/
 *       {recording_id}/
 *         metadata.json     ← immutable recording-level metadata
 *         frames.jsonl      ← one JSON object per line (append-only)
 */

import fs from "fs/promises";
import path from "path";

import { nextRecordingId } from "./recording-id";
import type {
  AppendFramesResponse,
  CreateRecordingResponse,
  FrameData,
  FinalizeRecordingResponse,
  RecordingMetadata,
  RecordingSummary,
} from "./types";

const DATASET_ROOT = path.join(process.cwd(), "AIHM_Dataset");

const CSV_HEADER =
  "recording_id,exercise,exerciseKey,subject,camera_angle,camera_height," +
  "speed,form,fps,duration,set_number,rep_target,save_mp4,frame_count,timestamp,status\n";

// ─── Internal helpers ─────────────────────────────────────────────────────────

function csvEscape(value: string | number | boolean): string {
  const s = String(value);
  return s.includes(",") || s.includes('"') || s.includes("\n")
    ? `"${s.replace(/"/g, '""')}"`
    : s;
}

function toCsvRow(m: RecordingMetadata): string {
  return (
    [
      m.recording_id,
      m.exercise,
      m.exerciseKey,
      m.subject,
      m.camera_angle,
      m.camera_height,
      m.speed,
      m.form,
      m.fps,
      m.duration,
      m.set_number,
      m.rep_target,
      m.save_mp4,
      m.frame_count,
      m.timestamp,
      m.status,
    ]
      .map(csvEscape)
      .join(",") + "\n"
  );
}

async function ensureDatasetRoot(): Promise<void> {
  await fs.mkdir(DATASET_ROOT, { recursive: true });
}

async function ensureMetadataCsv(): Promise<void> {
  const csvPath = path.join(DATASET_ROOT, "metadata.csv");
  try {
    await fs.access(csvPath);
  } catch {
    await fs.writeFile(csvPath, CSV_HEADER, "utf-8");
  }
}

function recordingFolder(exerciseKey: string, recording_id: string): string {
  return path.join(DATASET_ROOT, exerciseKey, recording_id);
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Create the recording folder and write an initial metadata.json.
 * Status is "partial" until finalizeRecording is called.
 */
export async function createRecording(
  partial: Omit<RecordingMetadata, "recording_id" | "timestamp" | "status">,
): Promise<CreateRecordingResponse> {
  await ensureDatasetRoot();

  const recording_id = await nextRecordingId();
  const folder = recordingFolder(partial.exerciseKey, recording_id);
  await fs.mkdir(folder, { recursive: true });

  const metadata: RecordingMetadata = {
    ...partial,
    recording_id,
    timestamp: new Date().toISOString(),
    status: "partial",
  };

  await fs.writeFile(
    path.join(folder, "metadata.json"),
    JSON.stringify(metadata, null, 2),
    "utf-8",
  );

  return {
    recording_id,
    folder: path.relative(process.cwd(), folder).replace(/\\/g, "/"),
  };
}

/**
 * Append a batch of FrameData objects to frames.jsonl (one JSON line each).
 * Safe to call multiple times — always appends, never overwrites.
 */
export async function appendFrames(
  recording_id: string,
  exerciseKey: string,
  frames: FrameData[],
): Promise<AppendFramesResponse> {
  if (frames.length === 0) {
    return { appended: 0, total_frames: 0 };
  }

  const jsonlPath = path.join(
    recordingFolder(exerciseKey, recording_id),
    "frames.jsonl",
  );

  // Count existing lines
  let existingCount = 0;
  try {
    const content = await fs.readFile(jsonlPath, "utf-8");
    existingCount = content.split("\n").filter((l) => l.trim().length > 0).length;
  } catch {
    // File doesn't exist yet — first write.
  }

  const lines = frames.map((f) => JSON.stringify(f)).join("\n") + "\n";
  await fs.appendFile(jsonlPath, lines, "utf-8");

  return {
    appended: frames.length,
    total_frames: existingCount + frames.length,
  };
}

/**
 * Finalize a recording:
 *   1. Count actual frames in frames.jsonl and compute real fps/duration.
 *   2. Rewrite metadata.json with final stats and status "complete".
 *   3. Append one row to AIHM_Dataset/metadata.csv.
 */
export async function finalizeRecording(
  recording_id: string,
  exerciseKey: string,
): Promise<FinalizeRecordingResponse> {
  const folder = recordingFolder(exerciseKey, recording_id);
  const metadataPath = path.join(folder, "metadata.json");
  const jsonlPath = path.join(folder, "frames.jsonl");

  // Read current metadata
  const raw = await fs.readFile(metadataPath, "utf-8");
  const metadata = JSON.parse(raw) as RecordingMetadata;

  // Compute real frame count and duration from the JSONL file
  let frameCount = 0;
  let durationSeconds = 0;

  try {
    const content = await fs.readFile(jsonlPath, "utf-8");
    const lines = content.split("\n").filter((l) => l.trim().length > 0);
    frameCount = lines.length;

    if (frameCount > 1) {
      const firstFrame = JSON.parse(lines[0]) as { timestamp: number };
      const lastFrame = JSON.parse(lines[frameCount - 1]) as { timestamp: number };
      durationSeconds =
        Math.round((lastFrame.timestamp - firstFrame.timestamp) * 1000) / 1000;
    }
  } catch {
    // frames.jsonl missing or unreadable
  }

  const fps =
    frameCount > 1 && durationSeconds > 0
      ? Math.round(((frameCount - 1) / durationSeconds) * 10) / 10
      : metadata.fps;

  const finalized: RecordingMetadata = {
    ...metadata,
    frame_count: frameCount,
    duration: durationSeconds || metadata.duration,
    fps,
    status: "complete",
  };

  // Rewrite metadata.json with final values
  await fs.writeFile(metadataPath, JSON.stringify(finalized, null, 2), "utf-8");

  // Append to global metadata.csv
  await ensureDatasetRoot();
  await ensureMetadataCsv();
  await fs.appendFile(
    path.join(DATASET_ROOT, "metadata.csv"),
    toCsvRow(finalized),
    "utf-8",
  );

  return {
    recording_id,
    frame_count: frameCount,
    duration: durationSeconds,
    fps,
    path: path.relative(process.cwd(), folder).replace(/\\/g, "/"),
  };
}

/**
 * Read all rows from metadata.csv and return lightweight summaries.
 * Does not read individual frames.jsonl files.
 */
export async function listRecordings(): Promise<RecordingSummary[]> {
  const csvPath = path.join(DATASET_ROOT, "metadata.csv");
  try {
    const content = await fs.readFile(csvPath, "utf-8");
    const rows = content.split("\n").filter((l) => l.trim().length > 0);
    if (rows.length < 2) return []; // only header or empty

    return rows.slice(1).map((row) => {
      const cols = row.split(",");
      return {
        recording_id: cols[0] ?? "",
        exercise:     cols[1] ?? "",
        exerciseKey:  cols[2] as RecordingMetadata["exerciseKey"],
        subject:      cols[3] ?? "",
        frame_count:  Number(cols[13] ?? 0),
        timestamp:    cols[14] ?? "",
        status:       (cols[15]?.trim() ?? "partial") as "complete" | "partial",
      };
    });
  } catch {
    return [];
  }
}

/** Read the metadata.json for a single recording. */
export async function getRecordingMetadata(
  recording_id: string,
  exerciseKey: string,
): Promise<RecordingMetadata> {
  const metadataPath = path.join(
    recordingFolder(exerciseKey, recording_id),
    "metadata.json",
  );
  const raw = await fs.readFile(metadataPath, "utf-8");
  return JSON.parse(raw) as RecordingMetadata;
}
