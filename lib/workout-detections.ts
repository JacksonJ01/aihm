import type { JointAngles } from "@/lib/pose";
import { WORKOUT_EXERCISE_CATALOG, type WorkoutExerciseKey } from "@/lib/workout-taxonomy";

export type WorkoutRepStage = "unknown" | "extended" | "contracted" | "untracked";

export type WorkoutDetectionState = {
  key: WorkoutExerciseKey;
  label: string;
  reps: number;
  stage: WorkoutRepStage;
  metric: number | null;
  lastRepAt: number;
  initialized: boolean;
  isTracked: boolean;
};

export type WorkoutDetections = Record<WorkoutExerciseKey, WorkoutDetectionState>;

type WorkoutDetectionRule = {
  key: WorkoutExerciseKey;
  label: string;
  contractedThreshold: number;
  extendedThreshold: number;
  cooldownMs: number;
  metric: (angles: JointAngles) => number | null;
  qualify?: (angles: JointAngles) => boolean;
};

const DEFAULT_COOLDOWN_MS = 650;

function average(values: Array<number | null | undefined>) {
  const filteredValues = values.filter((value): value is number => typeof value === "number");

  if (!filteredValues.length) {
    return null;
  }

  return filteredValues.reduce((sum, value) => sum + value, 0) / filteredValues.length;
}

function minimum(values: Array<number | null | undefined>) {
  const filteredValues = values.filter((value): value is number => typeof value === "number");

  if (!filteredValues.length) {
    return null;
  }

  return Math.min(...filteredValues);
}

const TRACKED_RULES: WorkoutDetectionRule[] = [
  { key: "barbellBicepsCurl", label: "Barbell biceps curl", contractedThreshold: 55, extendedThreshold: 160, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => minimum([angles.leftElbow, angles.rightElbow]) },
  { key: "hammerCurl", label: "Hammer curl", contractedThreshold: 55, extendedThreshold: 160, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => minimum([angles.leftElbow, angles.rightElbow]) },
  { key: "benchPress", label: "Bench press", contractedThreshold: 85, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  { key: "inclineBenchPress", label: "Incline bench press", contractedThreshold: 85, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  { key: "declineBenchPress", label: "Decline bench press", contractedThreshold: 85, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  { key: "chestFlyMachine", label: "Chest fly machine", contractedThreshold: 75, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftShoulder, angles.rightShoulder]) },
  { key: "latPulldown", label: "Lat pulldown", contractedThreshold: 70, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  {
    key: "lateralRaise",
    label: "Lateral raise",
    contractedThreshold: 85,
    extendedThreshold: 165,
    cooldownMs: DEFAULT_COOLDOWN_MS,
    metric: (angles) => average([angles.leftShoulder, angles.rightShoulder]),
    qualify: (angles) => {
      const shoulderAverage = average([angles.leftShoulder, angles.rightShoulder]);
      return shoulderAverage !== null && shoulderAverage < 150;
    },
  },
  { key: "shoulderPress", label: "Shoulder press", contractedThreshold: 92, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftShoulder, angles.rightShoulder]) },
  { key: "tricepPushdown", label: "Tricep pushdown", contractedThreshold: 70, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]), qualify: (angles) => (angles.leftShoulder ?? 180) > 95 || (angles.rightShoulder ?? 180) > 95 },
  { key: "tricepDips", label: "Tricep dips", contractedThreshold: 70, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]), qualify: (angles) => (angles.leftShoulder ?? 180) > 95 || (angles.rightShoulder ?? 180) > 95 },
  { key: "deadlift", label: "Deadlift", contractedThreshold: 120, extendedThreshold: 170, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftHip, angles.rightHip]) },
  { key: "romanianDeadlift", label: "Romanian deadlift", contractedThreshold: 120, extendedThreshold: 170, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftHip, angles.rightHip]) },
  { key: "hipThrust", label: "Hip thrust", contractedThreshold: 110, extendedThreshold: 170, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftHip, angles.rightHip]) },
  { key: "squat", label: "Squat", contractedThreshold: 95, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftKnee, angles.rightKnee]) },
  { key: "legExtension", label: "Leg extension", contractedThreshold: 95, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftKnee, angles.rightKnee]) },
  { key: "legRaises", label: "Leg raises", contractedThreshold: 95, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => minimum([angles.leftHip, angles.rightHip]) },
  { key: "pullUp", label: "Pull-up", contractedThreshold: 75, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  { key: "tBarRow", label: "T-bar row", contractedThreshold: 75, extendedThreshold: 165, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftElbow, angles.rightElbow]) },
  { key: "plank", label: "Plank", contractedThreshold: 150, extendedThreshold: 180, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftShoulder, angles.rightShoulder]) },
  { key: "russianTwist", label: "Russian twist", contractedThreshold: 100, extendedThreshold: 170, cooldownMs: DEFAULT_COOLDOWN_MS, metric: (angles) => average([angles.leftHip, angles.rightHip]) },
];

const TRACKED_RULE_LOOKUP = new Map<WorkoutExerciseKey, WorkoutDetectionRule>(TRACKED_RULES.map((rule) => [rule.key, rule] as const));

export const WORKOUT_DETECTION_ORDER = WORKOUT_EXERCISE_CATALOG.map((exercise) => exercise.key);

export const WORKOUT_DETECTION_LABELS = WORKOUT_EXERCISE_CATALOG.reduce(
  (labels, exercise) => ({
    ...labels,
    [exercise.key]: exercise.label,
  }),
  {} as Record<WorkoutExerciseKey, string>,
);

function getRule(key: WorkoutExerciseKey) {
  return TRACKED_RULE_LOOKUP.get(key) ?? null;
}

function resolveStage(metric: number, rule: WorkoutDetectionRule): WorkoutRepStage {
  if (metric <= rule.contractedThreshold) {
    return "contracted";
  }

  if (metric >= rule.extendedThreshold) {
    return "extended";
  }

  return "unknown";
}

export function createInitialWorkoutDetections(): WorkoutDetections {
  return WORKOUT_EXERCISE_CATALOG.reduce((detections, exercise) => {
    const rule = getRule(exercise.key);

    detections[exercise.key] = {
      key: exercise.key,
      label: exercise.label,
      reps: 0,
      stage: rule ? "unknown" : "untracked",
      metric: null,
      lastRepAt: 0,
      initialized: false,
      isTracked: Boolean(rule),
    };

    return detections;
  }, {} as WorkoutDetections);
}

export function detectWorkoutReps(
  angles: JointAngles,
  previousDetections: WorkoutDetections,
  now = Date.now(),
): WorkoutDetections {
  const nextDetections = createInitialWorkoutDetections();

  for (const exerciseKey of WORKOUT_DETECTION_ORDER) {
    const previousState = previousDetections[exerciseKey];
    const rule = getRule(exerciseKey);

    if (!rule) {
      nextDetections[exerciseKey] = {
        ...previousState,
        stage: "untracked",
        metric: null,
        isTracked: false,
      };
      continue;
    }

    const metric = rule.metric(angles);
    const nextState: WorkoutDetectionState = {
      ...previousState,
      metric,
      isTracked: true,
    };

    if (metric === null || (rule.qualify && !rule.qualify(angles))) {
      nextDetections[exerciseKey] = nextState;
      continue;
    }

    const stage = resolveStage(metric, rule);

    if (!previousState.initialized) {
      nextDetections[exerciseKey] = {
        ...nextState,
        stage,
        initialized: true,
      };
      continue;
    }

    let reps = previousState.reps;
    let lastRepAt = previousState.lastRepAt;

    if (
      previousState.stage === "contracted" &&
      stage === "extended" &&
      now - previousState.lastRepAt >= rule.cooldownMs
    ) {
      reps += 1;
      lastRepAt = now;
    }

    nextDetections[exerciseKey] = {
      ...nextState,
      reps,
      stage: stage === "unknown" ? previousState.stage : stage,
      lastRepAt,
      initialized: true,
    };
  }

  return nextDetections;
}
