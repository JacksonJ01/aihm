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

export function usePose(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  isCameraOn: boolean,
  scriptLoaded: boolean,
): PoseTrackerState {
  const poseRef = useRef<PoseInstance | null>(null);
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
        } catch (e) {
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
    let isSending = false;
    let hasProcessedFrame = false;
    const pose = poseRef.current;

    const clearCanvas = () => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");

      if (ctx && canvas) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    };

    const setCanvasVisibility = (isVisible: boolean) => {
      if (canvasRef.current) {
        canvasRef.current.style.opacity = isVisible ? "1" : "0";
      }
    };

    const syncCanvasSize = () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;

      if (!video || !canvas || !video.videoWidth || !video.videoHeight) {
        return;
      }

      if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
      }
    };

    clearCanvas();
    setCanvasVisibility(false);
    setPoseDetected(false);

    pose.onResults((results: PoseResults) => {
      if (cancelled) return;

      syncCanvasSize();

      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!ctx || !canvas) return;

      // Clearing Previous Frame
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!results.poseLandmarks) {
        setPoseDetected(false);
        setCanvasVisibility(false);
        return;
      }

      const visibleExerciseLandmarks = results.poseLandmarks.filter((point, index) => {
        return EXERCISE_LANDMARKS.includes(index) && (point.visibility ?? 0) > LANDMARK_VISIBILITY_THRESHOLD;
      });

      const hasVisiblePose = visibleExerciseLandmarks.length > 0;
      setPoseDetected(hasVisiblePose);
      setCanvasVisibility(hasVisiblePose);

      if (!hasVisiblePose) {
        return;
      }

      // Drawing Landmark Points
      results.poseLandmarks.forEach((point: PoseLandmark, index: number) => {
        const isTargetJoint = EXERCISE_LANDMARKS.includes(index);
        const isVisible = (point.visibility ?? 0) > LANDMARK_VISIBILITY_THRESHOLD;

        if (isTargetJoint && isVisible) {
          ctx.beginPath();
          ctx.arc(
            point.x * canvas.width,
            point.y * canvas.height,
            10,
            0,
            2 * Math.PI,
          );
          ctx.fillStyle = "rgba(255, 47, 0, 0.5)";
          ctx.fill();

          ctx.beginPath();
          ctx.arc(
            point.x * canvas.width,
            point.y * canvas.height,
            5,
            0,
            2 * Math.PI,
          );
          ctx.fillStyle = "rgba(255, 47, 0, 0.5)";
          ctx.fill();
        }
      });
    });

    const run = async () => {
      if (cancelled) return;

      if (
        !isSending &&
        videoRef.current &&
        isCameraOn &&
        videoRef.current.readyState >= 2
      ) {
        isSending = true;

        try {
          await pose.send({ image: videoRef.current });
          hasProcessedFrame = true;
        } catch (error) {
          if (!cancelled) {
            console.error("Pose send error:", error);
          }
        } finally {
          isSending = false;
        }
      }

      if (!cancelled) {
        animationFrameId = requestAnimationFrame(run);
      }
    };

    animationFrameId = requestAnimationFrame(run);

    return () => {
      cancelled = true;
      cancelAnimationFrame(animationFrameId);
      setPoseDetected(false);

      clearCanvas();
      setCanvasVisibility(false);
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

