"use client";

import { useEffect, useRef, useState } from "react";

import { calculateJointAngles, EMPTY_JOINT_ANGLES, type JointAngles, type PoseLandmark } from "@/lib/pose";
import { createInitialWorkoutDetections, detectWorkoutReps, type WorkoutDetections } from "@/lib/workout-detections";

type UserAgentData = {
  mobile?: boolean;
};

type NavigatorWithUserAgentData = Navigator & {
  userAgentData?: UserAgentData;
};

type PoseConstructorOptions = {
  locateFile: (file: string) => string;
};

type PoseOptions = {
  modelComplexity: number;
  smoothLandmarks: boolean;
  minDetectionConfidence: number;
  minTrackingConfidence: number;
};

type PoseInstance = {
  setOptions: (options: PoseOptions) => void;
  onResults: (callback: (results: PoseResults) => void) => void;
  send: (input: { image: HTMLVideoElement | HTMLCanvasElement }) => Promise<void>;
  close?: () => void;
};

type PoseConstructor = new (options: PoseConstructorOptions) => PoseInstance;

declare global {
  interface Window {
    Pose?: PoseConstructor;
  }
}

interface PoseResults {
  poseLandmarks?: PoseLandmark[];
  poseWorldLandmarks?: PoseLandmark[];
}

type PoseTrackerState = {
  trackerReady: boolean;
  poseDetected: boolean;
  jointAngles: JointAngles;
  workoutDetections: WorkoutDetections;
};

const LANDMARK_VISIBILITY_THRESHOLD = 0.35;
const MAX_MISSED_FRAMES = 4;
const EXERCISE_LANDMARK_INDICES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
const POSE_CONNECTIONS: [number, number][] = [
  [11, 13], [13, 15],
  [12, 14], [14, 16],
  [11, 12],
  [11, 23], [12, 24],
  [23, 24],
  [23, 25], [25, 27],
  [24, 26], [26, 28],
];

export function usePose(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  isCameraOn: boolean,
  scriptLoaded: boolean,
): PoseTrackerState {
  const poseRef = useRef<PoseInstance | null>(null);
  const lastStableAnglesRef = useRef<JointAngles>({ ...EMPTY_JOINT_ANGLES });
  const workoutDetectionsRef = useRef<WorkoutDetections>(createInitialWorkoutDetections());
  const missedFramesRef = useRef(0);
  const [trackerReady, setTrackerReady] = useState(false);
  const [poseDetected, setPoseDetected] = useState(false);
  const [jointAngles, setJointAngles] = useState<JointAngles>({ ...EMPTY_JOINT_ANGLES });
  const [workoutDetections, setWorkoutDetections] = useState<WorkoutDetections>(createInitialWorkoutDetections());

  useEffect(() => {
    if (!scriptLoaded || !window.Pose || poseRef.current) {
      return;
    }

    let cancelled = false;

    const pose = new window.Pose({
      locateFile: (file: string) => {
        try {
          if (typeof document !== "undefined") {
            const scriptEl = document.querySelector<HTMLScriptElement>(
              'script[src*="/@mediapipe/pose/"], script[src*="/mediapipe/pose/"]',
            );

            if (scriptEl?.src) {
              const base = scriptEl.src.substring(0, scriptEl.src.lastIndexOf("/") + 1);
              return base + file;
            }
          }
        } catch {
          // fall back to CDN below
        }

        return `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`;
      },
    });

    poseRef.current = pose;

    const navigatorWithUserAgentData = navigator as NavigatorWithUserAgentData;
    const isMobileDevice =
      typeof navigator !== "undefined" &&
      (navigatorWithUserAgentData.userAgentData?.mobile ?? /Mobi|Android|iPhone|iPad|iPod|Windows Phone/.test(navigator.userAgent));

    pose.setOptions(
      isMobileDevice
        ? {
            modelComplexity: 0,
            smoothLandmarks: true,
            minDetectionConfidence: 0.5,
            minTrackingConfidence: 0.5,
          }
        : {
            modelComplexity: 1,
            smoothLandmarks: true,
            minDetectionConfidence: 0.6,
            minTrackingConfidence: 0.6,
          },
    );

    const warmTracker = async () => {
      try {
        const warmupCanvas = document.createElement("canvas");
        warmupCanvas.width = 1;
        warmupCanvas.height = 1;
        await pose.send({ image: warmupCanvas });
      } catch (error) {
        if (!cancelled) {
          console.error("Pose warmup error:", error);
        }
      } finally {
        if (!cancelled) {
          setTrackerReady(true);
        }
      }
    };

    void warmTracker();

    return () => {
      cancelled = true;
      setTrackerReady(false);
      setPoseDetected(false);
      setJointAngles({ ...EMPTY_JOINT_ANGLES });
      setWorkoutDetections(createInitialWorkoutDetections());
      lastStableAnglesRef.current = { ...EMPTY_JOINT_ANGLES };
      workoutDetectionsRef.current = createInitialWorkoutDetections();
      missedFramesRef.current = 0;

      if (typeof pose.close === "function") {
        try {
          pose.close();
        } catch (error) {
          console.error("Pose cleanup error:", error);
        }
      }

      poseRef.current = null;
    };
  }, [scriptLoaded]);

  useEffect(() => {
    if (!isCameraOn || !scriptLoaded || !videoRef.current || !canvasRef.current) {
      return;
    }

    if (!poseRef.current) {
      return;
    }

    let cancelled = false;
    let animationFrameId = 0;
    const pose = poseRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");

    setPoseDetected(false);

    const clearCanvas = () => {
      if (!canvas || !context) {
        return;
      }

      context.clearRect(0, 0, canvas.width, canvas.height);
    };

    const syncCanvasSize = () => {
      if (!canvas) {
        return;
      }

      const clientWidth = canvas.clientWidth;
      const clientHeight = canvas.clientHeight;

      if (!clientWidth || !clientHeight) {
        return;
      }

      const dpr = window.devicePixelRatio || 1;
      const nextWidth = Math.round(clientWidth * dpr);
      const nextHeight = Math.round(clientHeight * dpr);

      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }
    };

    const drawPoseOverlay = (landmarks: PoseLandmark[]) => {
      if (!canvas || !context) {
        return;
      }

      syncCanvasSize();
      const width = canvas.width;
      const height = canvas.height;

      if (!width || !height) {
        return;
      }

      const video = videoRef.current;
      if (!video || !video.videoWidth || !video.videoHeight) {
        return;
      }

      const sourceWidth = video.videoWidth;
      const sourceHeight = video.videoHeight;
      const containScale = Math.min(width / sourceWidth, height / sourceHeight);
      const drawWidth = sourceWidth * containScale;
      const drawHeight = sourceHeight * containScale;
      const offsetX = (width - drawWidth) / 2;
      const offsetY = (height - drawHeight) / 2;

      const mapX = (x: number) => offsetX + x * drawWidth;
      const mapY = (y: number) => offsetY + y * drawHeight;

      context.clearRect(0, 0, width, height);
      context.lineCap = "round";
      context.lineJoin = "round";

      context.lineWidth = 3;
      context.strokeStyle = "rgba(255, 255, 255, 0.65)";

      for (const [startIndex, endIndex] of POSE_CONNECTIONS) {
        const startPoint = landmarks[startIndex];
        const endPoint = landmarks[endIndex];

        if (!startPoint || !endPoint) {
          continue;
        }

        if ((startPoint.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) continue;
        if ((endPoint.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) continue;

        context.beginPath();
        context.moveTo(mapX(startPoint.x), mapY(startPoint.y));
        context.lineTo(mapX(endPoint.x), mapY(endPoint.y));
        context.stroke();
      }

      for (const index of EXERCISE_LANDMARK_INDICES) {
        const point = landmarks[index];

        if (!point || (point.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) {
          continue;
        }

        const x = mapX(point.x);
        const y = mapY(point.y);

        context.beginPath();
        context.arc(x, y, 8, 0, 2 * Math.PI);
        context.fillStyle = "rgba(255, 94, 0, 0.9)";
        context.fill();

        context.beginPath();
        context.arc(x, y, 3, 0, 2 * Math.PI);
        context.fillStyle = "rgba(255, 255, 255, 0.95)";
        context.fill();
      }
    };

    const sendFrame = async () => {
      if (cancelled) {
        return;
      }

      const video = videoRef.current;
      if (!video || video.readyState < 2) {
        animationFrameId = requestAnimationFrame(sendFrame);
        return;
      }

      try {
        await pose.send({ image: video });
      } catch (error) {
        if (!cancelled) {
          console.error("Pose send error:", error);
          animationFrameId = requestAnimationFrame(sendFrame);
        }
      }
    };

    pose.onResults((results: PoseResults) => {
      if (cancelled) {
        return;
      }

      const landmarks = results.poseLandmarks;

      if (!landmarks?.length) {
        missedFramesRef.current += 1;

        if (missedFramesRef.current >= MAX_MISSED_FRAMES) {
          setJointAngles({ ...EMPTY_JOINT_ANGLES });
          lastStableAnglesRef.current = { ...EMPTY_JOINT_ANGLES };
          setWorkoutDetections((currentDetections) => {
            const nextDetections = createInitialWorkoutDetections();
            for (const key of Object.keys(currentDetections) as Array<keyof WorkoutDetections>) {
              nextDetections[key] = {
                ...currentDetections[key],
                metric: null,
              };
            }

            workoutDetectionsRef.current = nextDetections;
            return nextDetections;
          });
        } else {
          setJointAngles({ ...lastStableAnglesRef.current });
        }

        setPoseDetected(false);
        clearCanvas();
        animationFrameId = requestAnimationFrame(sendFrame);
        return;
      }

      const visibleLandmarkCount = landmarks.filter((point, index) =>
        EXERCISE_LANDMARK_INDICES.includes(index) && (point.visibility ?? 0) > LANDMARK_VISIBILITY_THRESHOLD,
      ).length;
      const hasVisiblePose = visibleLandmarkCount > 0;

      missedFramesRef.current = 0;
      setPoseDetected(hasVisiblePose);

      const nextAngles = calculateJointAngles(landmarks, {
        visibilityThreshold: LANDMARK_VISIBILITY_THRESHOLD,
      });
      lastStableAnglesRef.current = { ...nextAngles };
      setJointAngles(nextAngles);
      const nextWorkoutDetections = detectWorkoutReps(nextAngles, workoutDetectionsRef.current);
      workoutDetectionsRef.current = nextWorkoutDetections;
      setWorkoutDetections(nextWorkoutDetections);

      drawPoseOverlay(landmarks);

      animationFrameId = requestAnimationFrame(sendFrame);
    });

    animationFrameId = requestAnimationFrame(sendFrame);

    return () => {
      cancelled = true;
      cancelAnimationFrame(animationFrameId);
      setPoseDetected(false);
      setJointAngles({ ...EMPTY_JOINT_ANGLES });
      setWorkoutDetections(createInitialWorkoutDetections());
      clearCanvas();
    };
  }, [isCameraOn, scriptLoaded, videoRef, canvasRef]);

  return {
    trackerReady,
    poseDetected,
    jointAngles,
    workoutDetections,
  };
}
