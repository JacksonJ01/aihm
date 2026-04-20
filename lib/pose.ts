export type PoseLandmark = {
	x: number;
	y: number;
	z: number;
	visibility?: number;
};

export type JointAngleKey =
	| "leftElbow"
	| "rightElbow"
	| "leftShoulder"
	| "rightShoulder"
	| "leftHip"
	| "rightHip"
	| "leftKnee"
	| "rightKnee";

export type JointAngles = Record<JointAngleKey, number | null>;

export type JointAngleDefinition = {
	key: JointAngleKey;
	label: string;
	landmarkIndices: [number, number, number];
};

export type JointAngleOptions = {
	visibilityThreshold?: number;
};

export const EMPTY_JOINT_ANGLES: JointAngles = {
	leftElbow: null,
	rightElbow: null,
	leftShoulder: null,
	rightShoulder: null,
	leftHip: null,
	rightHip: null,
	leftKnee: null,
	rightKnee: null,
};

export const JOINT_ANGLE_DEFINITIONS: JointAngleDefinition[] = [
	{ key: "leftElbow", label: "Left elbow", landmarkIndices: [11, 13, 15] },
	{ key: "rightElbow", label: "Right elbow", landmarkIndices: [12, 14, 16] },
	{ key: "leftShoulder", label: "Left shoulder", landmarkIndices: [13, 11, 23] },
	{ key: "rightShoulder", label: "Right shoulder", landmarkIndices: [14, 12, 24] },
	{ key: "leftHip", label: "Left hip", landmarkIndices: [11, 23, 25] },
	{ key: "rightHip", label: "Right hip", landmarkIndices: [12, 24, 26] },
	{ key: "leftKnee", label: "Left knee", landmarkIndices: [23, 25, 27] },
	{ key: "rightKnee", label: "Right knee", landmarkIndices: [24, 26, 28] },
];

const DEFAULT_VISIBLE_THRESHOLD = 0.35;

function subtractPoints(a: PoseLandmark, b: PoseLandmark) {
	return {
		x: a.x - b.x,
		y: a.y - b.y,
	};
}

function vectorMagnitude(vector: { x: number; y: number }) {
	return Math.sqrt(vector.x * vector.x + vector.y * vector.y);
}

function crossProductMagnitude(
	firstVector: { x: number; y: number },
	secondVector: { x: number; y: number },
) {
	return Math.abs(firstVector.x * secondVector.y - firstVector.y * secondVector.x);
}

export function calculateJointAngle(
	firstPoint: PoseLandmark,
	jointPoint: PoseLandmark,
	thirdPoint: PoseLandmark,
) {
	const vectorA = subtractPoints(firstPoint, jointPoint);
	const vectorB = subtractPoints(thirdPoint, jointPoint);
	const magnitudeA = vectorMagnitude(vectorA);
	const magnitudeB = vectorMagnitude(vectorB);

	if (!magnitudeA || !magnitudeB) {
		return null;
	}

	const dotProduct = vectorA.x * vectorB.x + vectorA.y * vectorB.y;
	const crossMagnitude = crossProductMagnitude(vectorA, vectorB);

	return Math.round((Math.atan2(crossMagnitude, dotProduct) * 180) / Math.PI);
}

export function calculateJointAngles(
	landmarks: PoseLandmark[],
	options: JointAngleOptions = {},
): JointAngles {
	const {
		visibilityThreshold = DEFAULT_VISIBLE_THRESHOLD,
	} = options;
	const nextAngles: JointAngles = { ...EMPTY_JOINT_ANGLES };

	for (const definition of JOINT_ANGLE_DEFINITIONS) {
		const [firstIndex, jointIndex, thirdIndex] = definition.landmarkIndices;
		const firstPoint = landmarks[firstIndex];
		const jointPoint = landmarks[jointIndex];
		const thirdPoint = landmarks[thirdIndex];

		if (!firstPoint || !jointPoint || !thirdPoint) {
			continue;
		}

		if ((firstPoint.visibility ?? 0) <= visibilityThreshold) continue;
		if ((jointPoint.visibility ?? 0) <= visibilityThreshold) continue;
		if ((thirdPoint.visibility ?? 0) <= visibilityThreshold) continue;

		nextAngles[definition.key] = calculateJointAngle(firstPoint, jointPoint, thirdPoint);
	}

	return nextAngles;
}
