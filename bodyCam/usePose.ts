"use client";

import { useEffect, useRef, useState } from "react";

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

interface PoseLandmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

interface PoseResults {
  poseLandmarks?: PoseLandmark[];
}

type PoseTrackerState = {
  trackerReady: boolean;
  poseDetected: boolean;
};

const LANDMARK_VISIBILITY_THRESHOLD = 0.35;

const EXERCISE_LANDMARKS = [
    11, 12, // Shoulders
    13, 14, // Elbows
    15, 16, // Wrists
    23, 24, // Hips
    25, 26, // Knees
    27, 28  // Ankles
];

const POSE_CONNECTIONS: [number, number][] = [
  [11, 13], [13, 15], // Left arm: shoulder → elbow → wrist
  [12, 14], [14, 16], // Right arm: shoulder → elbow → wrist
  [11, 12],           // Shoulders bar
  [11, 23], [12, 24], // Torso sides
  [23, 24],           // Hips bar
  [23, 25], [25, 27], // Left leg: hip → knee → ankle
  [24, 26], [26, 28], // Right leg: hip → knee → ankle
];

export function usePose(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  isCameraOn: boolean,
  scriptLoaded: boolean,
): PoseTrackerState {
  const poseRef = useRef<PoseInstance | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const [trackerReady, setTrackerReady] = useState(false);
  const [poseDetected, setPoseDetected] = useState(false);

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
              'script[src*="/@mediapipe/pose/"], script[src*="/mediapipe/pose/"]'
            );

            if (scriptEl && scriptEl.src) {
              const base = scriptEl.src.substring(0, scriptEl.src.lastIndexOf("/") + 1);
              return base + file;
            }
          }
        } catch {
          // ignore and fallback
        }

        // Fallback to jsdelivr CDN if local files are not available on the host
        return `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`;
      },
    });

    poseRef.current = pose;

    const navigatorWithUserAgentData = navigator as NavigatorWithUserAgentData;
    const isMobileDevice = typeof navigator !== "undefined" &&
      (navigatorWithUserAgentData.userAgentData?.mobile ?? /Mobi|Android|iPhone|iPad|iPod|Windows Phone/.test(navigator.userAgent));

    const poseOptions = isMobileDevice
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
        };

    pose.setOptions(poseOptions);

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
    if (!isCameraOn || !scriptLoaded || !videoRef.current || !canvasRef.current) return;
    if (!poseRef.current) return;

    let cancelled = false;
    let animationFrameId = 0;
    const pose = poseRef.current;
    const canvas = canvasRef.current;

    // Cache the 2D context — resizing canvas resets its state but the ref remains valid
    ctxRef.current = canvas.getContext("2d");

    const clearCanvas = () => {
      const ctx = ctxRef.current;
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    };

    const setCanvasVisibility = (isVisible: boolean) => {
      canvas.style.opacity = isVisible ? "1" : "0";
    };

    const syncCanvasSize = () => {
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
        // After a resize the canvas state resets — re-cache the context
        ctxRef.current = canvas.getContext("2d");
      }
    };

    clearCanvas();
    setCanvasVisibility(false);
    setPoseDetected(false);

    // Callback-driven pipeline: onResults schedules the next send so there is
    // no wasted RAF tick between when MediaPipe finishes and the next frame starts.
    const sendFrame = async () => {
      if (cancelled) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2) {
        // Video not ready yet — retry next tick
        animationFrameId = requestAnimationFrame(sendFrame);
        return;
      }
      try {
        await pose.send({ image: video });
        // onResults fires during the await and schedules the next RAF
      } catch (error) {
        if (!cancelled) console.error("Pose send error:", error);
        // onResults won't fire on error — keep the loop alive
        if (!cancelled) animationFrameId = requestAnimationFrame(sendFrame);
      }
    };

    pose.onResults((results: PoseResults) => {
      if (cancelled) return;

      syncCanvasSize();

      const ctx = ctxRef.current;
      if (!ctx) return;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!results.poseLandmarks) {
        setPoseDetected(false);
        setCanvasVisibility(false);
        animationFrameId = requestAnimationFrame(sendFrame);
        return;
      }

      const landmarks = results.poseLandmarks;
      const w = canvas.width;
      const h = canvas.height;
      const video = videoRef.current;

      if (!video || !video.videoWidth || !video.videoHeight) {
        animationFrameId = requestAnimationFrame(sendFrame);
        return;
      }

      const sourceWidth = video.videoWidth;
      const sourceHeight = video.videoHeight;
      const containScale = Math.min(w / sourceWidth, h / sourceHeight);
      const drawWidth = sourceWidth * containScale;
      const drawHeight = sourceHeight * containScale;
      const offsetX = (w - drawWidth) / 2;
      const offsetY = (h - drawHeight) / 2;

      const mapX = (x: number) => offsetX + x * drawWidth;
      const mapY = (y: number) => offsetY + y * drawHeight;

      const visibleExerciseCount = landmarks.filter((point, index) =>
        EXERCISE_LANDMARKS.includes(index) && (point.visibility ?? 0) > LANDMARK_VISIBILITY_THRESHOLD,
      ).length;

      const hasVisiblePose = visibleExerciseCount > 0;
      setPoseDetected(hasVisiblePose);
      setCanvasVisibility(hasVisiblePose);

      if (hasVisiblePose) {
        // Draw skeleton connection lines behind the joint dots
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = "rgba(255, 255, 255, 0.5)";
        for (const [a, b] of POSE_CONNECTIONS) {
          const pA = landmarks[a];
          const pB = landmarks[b];
          if (!pA || !pB) continue;
          if ((pA.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) continue;
          if ((pB.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) continue;
          ctx.beginPath();
          ctx.moveTo(mapX(pA.x), mapY(pA.y));
          ctx.lineTo(mapX(pB.x), mapY(pB.y));
          ctx.stroke();
        }

        // Draw joint dots on top of the lines
        for (const index of EXERCISE_LANDMARKS) {
          const point = landmarks[index];
          if (!point || (point.visibility ?? 0) <= LANDMARK_VISIBILITY_THRESHOLD) continue;
          const x = mapX(point.x);
          const y = mapY(point.y);

          // Outer filled circle
          ctx.beginPath();
          ctx.arc(x, y, 8, 0, 2 * Math.PI);
          ctx.fillStyle = "rgba(255, 60, 0, 0.9)";
          ctx.fill();

          // Inner white dot for contrast
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, 2 * Math.PI);
          ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
          ctx.fill();
        }
      }

      // Schedule the next frame immediately after drawing
      animationFrameId = requestAnimationFrame(sendFrame);
    });

    // Kick off the pipeline
    animationFrameId = requestAnimationFrame(sendFrame);

    return () => {
      cancelled = true;
      cancelAnimationFrame(animationFrameId);
      setPoseDetected(false);
      clearCanvas();
      setCanvasVisibility(false);
      ctxRef.current = null;
    };
  }, [isCameraOn, scriptLoaded, videoRef, canvasRef]);

  return {
    trackerReady,
    poseDetected,
  };
}

// "use client";

// import { useEffect } from "react";
// import { Pose } from "@mediapipe/pose";

// export function usePose(
//   videoRef: React.RefObject<HTMLVideoElement | null>,
//   isCameraOn: boolean
// ) {
//   useEffect(() => {
//     if (!isCameraOn || !videoRef.current) return;

//     const pose = new Pose({
//       locateFile: (file) =>
//         `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`,
//     });

//     pose.setOptions({
//       modelComplexity: 1,
//       smoothLandmarks: true,
//       enableSegmentation: false,
//       minDetectionConfidence: 0.5,
//       minTrackingConfidence: 0.5,
//     });

//     pose.onResults((results) => {
//       if (results.poseLandmarks) {
//         console.log(results.poseLandmarks); // 🔥 YOUR DATA
//       }
//     });

//     let animationFrameId: number;

//     const run = async () => {
//       if (videoRef.current) {
//         await pose.send({ image: videoRef.current });
//       }
//       animationFrameId = requestAnimationFrame(run);
//     };

//     run();

//     return () => cancelAnimationFrame(animationFrameId);
//   }, [isCameraOn, videoRef]);
// }

