import fs from "fs/promises";
import path from "path";

const DATASET_ROOT = path.join(process.cwd(), "AIHM_Dataset");
const ID_PATTERN = /^R(\d+)$/;
const MIN_PAD = 4; // R0001 → R9999; auto-widens beyond R9999

/**
 * Scan all exercise sub-directories for existing recording folders and return
 * the next available ID string (e.g. "R0042").
 *
 * IDs are globally unique across all exercises.
 * Not atomic — safe for local solo-use development.
 */
export async function nextRecordingId(): Promise<string> {
  let max = 0;

  try {
    const entries = await fs.readdir(DATASET_ROOT, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const exercisePath = path.join(DATASET_ROOT, entry.name);

      try {
        const recordings = await fs.readdir(exercisePath, { withFileTypes: true });
        for (const rec of recordings) {
          if (!rec.isDirectory()) continue;
          const match = ID_PATTERN.exec(rec.name);
          if (match) {
            const n = parseInt(match[1], 10);
            if (n > max) max = n;
          }
        }
      } catch {
        // Exercise folder unreadable — skip it.
      }
    }
  } catch {
    // Dataset root doesn't exist yet — start from 0.
  }

  const next = max + 1;
  const pad = Math.max(MIN_PAD, String(next).length);
  return `R${String(next).padStart(pad, "0")}`;
}
