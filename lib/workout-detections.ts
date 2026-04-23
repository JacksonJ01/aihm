import type { JointAngles } from "@/lib/pose";

export type WorkoutExerciseKey =
	| "bicepCurl"
	| "tricepExtension"
	| "pushup"
	| "squat"
	| "lunge"
	| "shoulderPress"
	| "lateralRaise"
	| "deadlift"
	| "crunch"
	| "kneeRaise";

export type WorkoutRepStage = "unknown" | "extended" | "contracted";

export type WorkoutDetectionState = {
	key: WorkoutExerciseKey;
	label: string;
	reps: number;
	stage: WorkoutRepStage;
	metric: number | null;
	lastRepAt: number;
	initialized: boolean;
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

function maximum(values: Array<number | null | undefined>) {
	const filteredValues = values.filter((value): value is number => typeof value === "number");
	if (!filteredValues.length) {
		return null;
	}

	return Math.max(...filteredValues);
}

const WORKOUT_DETECTION_RULES: WorkoutDetectionRule[] = [
	{
		key: "bicepCurl",
		label: "Bicep curl",
		contractedThreshold: 55,
		extendedThreshold: 160,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => minimum([angles.leftElbow, angles.rightElbow]),
	},
	{
		key: "tricepExtension",
		label: "Tricep extension",
		contractedThreshold: 70,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftElbow, angles.rightElbow]),
		qualify: (angles) => (angles.leftShoulder ?? 180) > 95 || (angles.rightShoulder ?? 180) > 95,
	},
	{
		key: "pushup",
		label: "Push-up",
		contractedThreshold: 85,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftElbow, angles.rightElbow]),
		qualify: (angles) => average([angles.leftHip, angles.rightHip]) !== null,
	},
	{
		key: "squat",
		label: "Squat",
		contractedThreshold: 95,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftKnee, angles.rightKnee]),
	},
	{
		key: "lunge",
		label: "Lunge",
		contractedThreshold: 92,
		extendedThreshold: 160,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => minimum([angles.leftKnee, angles.rightKnee]),
		qualify: (angles) => {
			const leftKnee = angles.leftKnee;
			const rightKnee = angles.rightKnee;

			if (leftKnee === null || rightKnee === null) {
				return false;
			}

			return Math.abs(leftKnee - rightKnee) >= 18;
		},
	},
	{
		key: "shoulderPress",
		label: "Shoulder press",
		contractedThreshold: 92,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftShoulder, angles.rightShoulder]),
	},
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
	{
		key: "deadlift",
		label: "Deadlift",
		contractedThreshold: 120,
		extendedThreshold: 170,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftHip, angles.rightHip]),
	},
	{
		key: "crunch",
		label: "Crunch",
		contractedThreshold: 110,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => average([angles.leftHip, angles.rightHip]),
		qualify: (angles) => {
			const shoulderAverage = average([angles.leftShoulder, angles.rightShoulder]);
			return shoulderAverage !== null && shoulderAverage < 145;
		},
	},
	{
		key: "kneeRaise",
		label: "Knee raise",
		contractedThreshold: 95,
		extendedThreshold: 165,
		cooldownMs: DEFAULT_COOLDOWN_MS,
		metric: (angles) => minimum([angles.leftKnee, angles.rightKnee]),
		qualify: (angles) => average([angles.leftHip, angles.rightHip]) !== null,
	},
];

export const WORKOUT_DETECTION_ORDER = WORKOUT_DETECTION_RULES.map((rule) => rule.key);

export const WORKOUT_DETECTION_LABELS = WORKOUT_DETECTION_RULES.reduce(
	(labels, rule) => ({
		...labels,
		[rule.key]: rule.label,
	}),
	{} as Record<WorkoutExerciseKey, string>,
);

export function createInitialWorkoutDetections(): WorkoutDetections {
	return WORKOUT_DETECTION_RULES.reduce((detections, rule) => {
		detections[rule.key] = {
			key: rule.key,
			label: rule.label,
			reps: 0,
			stage: "unknown",
			metric: null,
			lastRepAt: 0,
			initialized: false,
		};

		return detections;
	}, {} as WorkoutDetections);
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

export function detectWorkoutReps(
	angles: JointAngles,
	previousDetections: WorkoutDetections,
	now = Date.now(),
): WorkoutDetections {
	return WORKOUT_DETECTION_RULES.reduce((nextDetections, rule) => {
		const previousState = previousDetections[rule.key];
		const metric = rule.metric(angles);
		const nextState: WorkoutDetectionState = {
			...previousState,
			metric,
		};

		if (metric === null || (rule.qualify && !rule.qualify(angles))) {
			nextDetections[rule.key] = nextState;
			return nextDetections;
		}

		const stage = resolveStage(metric, rule);

		if (!previousState.initialized) {
			nextDetections[rule.key] = {
				...nextState,
				stage,
				initialized: true,
			};
			return nextDetections;
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

		nextDetections[rule.key] = {
			...nextState,
			reps,
			stage: stage === "unknown" ? previousState.stage : stage,
			lastRepAt,
			initialized: true,
		};

		return nextDetections;
	}, {} as WorkoutDetections);
}