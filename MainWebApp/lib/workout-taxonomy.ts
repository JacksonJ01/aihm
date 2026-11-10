export type WorkoutExerciseKey =
  | "barbellBicepsCurl"
  | "benchPress"
  | "chestFlyMachine"
  | "deadlift"
  | "declineBenchPress"
  | "hammerCurl"
  | "hipThrust"
  | "inclineBenchPress"
  | "latPulldown"
  | "lateralRaise"
  | "legExtension"
  | "legRaises"
  | "plank"
  | "pullUp"
  | "pushUp"
  | "romanianDeadlift"
  | "russianTwist"
  | "shoulderPress"
  | "squat"
  | "tBarRow"
  | "tricepDips"
  | "tricepPushdown";

export type WorkoutExerciseDefinition = {
  key: WorkoutExerciseKey;
  folderName: string;
  label: string;
  aliases: string[];
};

export const WORKOUT_EXERCISE_CATALOG: WorkoutExerciseDefinition[] = [
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

const WORKOUT_FOLDER_LOOKUP = new Map(
  WORKOUT_EXERCISE_CATALOG.map((exercise) => [normalizeWorkoutFolderName(exercise.folderName), exercise]),
);

export function normalizeWorkoutFolderName(folderName: string) {
  return folderName.trim().toLowerCase().replace(/\s+/g, " ");
}

export function getWorkoutExerciseDefinition(folderName: string) {
  return WORKOUT_FOLDER_LOOKUP.get(normalizeWorkoutFolderName(folderName)) ?? null;
}

export function getWorkoutExerciseKeys() {
  return WORKOUT_EXERCISE_CATALOG.map((exercise) => exercise.key);
}