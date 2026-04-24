import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";

const datasetRoot = path.resolve(process.cwd(), "preprocessedWorkoutVideos");
const outputPath = path.resolve(process.cwd(), "generated", "workout-dataset-manifest.json");
const videoExtensions = new Set([".mp4", ".mov", ".m4v", ".webm"]);

const workoutExerciseCatalog = [
  { key: "barbellBicepsCurl", folderName: "barbell biceps curl", label: "Barbell biceps curl", aliases: ["biceps curl", "barbell curl"] },
  { key: "benchPress", folderName: "bench press", label: "Bench press", aliases: ["flat bench press"] },
  { key: "chestFlyMachine", folderName: "chest fly machine", label: "Chest fly machine", aliases: ["machine fly"] },
  { key: "deadlift", folderName: "deadlift", label: "Deadlift", aliases: [] },
  { key: "declineBenchPress", folderName: "decline bench press", label: "Decline bench press", aliases: ["dbp"] },
  { key: "hammerCurl", folderName: "hammer curl", label: "Hammer curl", aliases: [] },
  { key: "hipThrust", folderName: "hip thrust", label: "Hip thrust", aliases: [] },
  { key: "inclineBenchPress", folderName: "incline bench press", label: "Incline bench press", aliases: [] },
  { key: "latPulldown", folderName: "lat pulldown", label: "Lat pulldown", aliases: [] },
  { key: "lateralRaise", folderName: "lateral raise", label: "Lateral raise", aliases: [] },
  { key: "legExtension", folderName: "leg extension", label: "Leg extension", aliases: [] },
  { key: "legRaises", folderName: "leg raises", label: "Leg raises", aliases: [] },
  { key: "plank", folderName: "plank", label: "Plank", aliases: [] },
  { key: "pullUp", folderName: "pull Up", label: "Pull-up", aliases: ["pull up", "pullup"] },
  { key: "pushUp", folderName: "push-up", label: "Push-up", aliases: ["push up"] },
  { key: "romanianDeadlift", folderName: "romanian deadlift", label: "Romanian deadlift", aliases: ["rdl"] },
  { key: "russianTwist", folderName: "russian twist", label: "Russian twist", aliases: [] },
  { key: "shoulderPress", folderName: "shoulder press", label: "Shoulder press", aliases: [] },
  { key: "squat", folderName: "squat", label: "Squat", aliases: [] },
  { key: "tBarRow", folderName: "t bar row", label: "T-bar row", aliases: ["t-bar row"] },
  { key: "tricepDips", folderName: "tricep dips", label: "Tricep dips", aliases: ["dips"] },
  { key: "tricepPushdown", folderName: "tricep Pushdown", label: "Tricep pushdown", aliases: ["tricep pushdown"] },
];

function normalizeFolderName(folderName) {
  return folderName.trim().toLowerCase().replace(/\s+/g, " ");
}

function toPortablePath(inputPath) {
  return inputPath.split(path.sep).join("/");
}

async function main() {
  const rootEntries = await fs.readdir(datasetRoot, { withFileTypes: true });
  const folderLookup = new Map(
    workoutExerciseCatalog.map((exercise) => [normalizeFolderName(exercise.folderName), exercise]),
  );

  const exercises = [];
  let totalClips = 0;

  for (const entry of rootEntries) {
    if (!entry.isDirectory()) {
      continue;
    }

    const folderName = entry.name;
    const exercise = folderLookup.get(normalizeFolderName(folderName));

    if (!exercise) {
      throw new Error(`Unknown workout folder: ${folderName}`);
    }

    const folderPath = path.join(datasetRoot, folderName);
    const clipEntries = await fs.readdir(folderPath, { withFileTypes: true });
    const clips = [];

    for (const clipEntry of clipEntries) {
      if (!clipEntry.isFile()) {
        continue;
      }

      const extension = path.extname(clipEntry.name).toLowerCase();

      if (!videoExtensions.has(extension)) {
        continue;
      }

      const clipPath = path.join(folderPath, clipEntry.name);
      const clipStats = await fs.stat(clipPath);

      clips.push({
        fileName: clipEntry.name,
        relativePath: toPortablePath(path.relative(process.cwd(), clipPath)),
        extension,
        sizeBytes: clipStats.size,
        modifiedAt: clipStats.mtime.toISOString(),
      });
    }

    clips.sort((firstClip, secondClip) => firstClip.fileName.localeCompare(secondClip.fileName, undefined, { numeric: true }));

    exercises.push({
      exerciseKey: exercise.key,
      label: exercise.label,
      folderName: exercise.folderName,
      aliases: exercise.aliases,
      clipCount: clips.length,
      clips,
    });

    totalClips += clips.length;
  }

  exercises.sort((firstExercise, secondExercise) => firstExercise.folderName.localeCompare(secondExercise.folderName));

  const manifest = {
    generatedAt: new Date().toISOString(),
    datasetRoot: toPortablePath(path.relative(process.cwd(), datasetRoot)),
    totalExercises: exercises.length,
    totalClips,
    exercises,
  };

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

  console.log(`Wrote ${toPortablePath(path.relative(process.cwd(), outputPath))}`);
  console.table(
    exercises.map((exercise) => ({
      exerciseKey: exercise.exerciseKey,
      folderName: exercise.folderName,
      clips: exercise.clipCount,
    })),
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});