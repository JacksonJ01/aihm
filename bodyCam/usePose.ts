"use client";

import { useEffect } from "react";

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
  send: (input: { image: HTMLVideoElement }) => Promise<void>;
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
) {
  useEffect(() => {
    if (!isCameraOn || !scriptLoaded || !videoRef.current || !canvasRef.current) return;
    if (!window.Pose) return;
    let cancelled = false;
    let animationFrameId = 0;
    let isSending = false;
    let hasProcessedFrame = false;

    const pose = new window.Pose({
      locateFile: (file: string) => `/@mediapipe/pose/${file}`,
    });

    // Detect mobile devices (use userAgentData when available)
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

    clearCanvas();
    setCanvasVisibility(false);

    pose.onResults((results: PoseResults) => {
      if (cancelled) return;

      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!ctx || !canvas) return;

      // Clearing Previous Frame
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!results.poseLandmarks) {
        setCanvasVisibility(false);
        return;
      }

      setCanvasVisibility(true);

      // Drawing Landmark Points
      results.poseLandmarks.forEach((point: PoseLandmark, index: number) => {
        const isTargetJoint = EXERCISE_LANDMARKS.includes(index);
        const isVisible = (point.visibility ?? 0) > 0.6;

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

      // Avoid closing during an in-flight initialization/send, which can abort the wasm module.
      if (hasProcessedFrame && !isSending && typeof pose.close === "function") {
        try {
          pose.close();
        } catch (error) {
          console.error("Pose cleanup error:", error);
        }
      }

      clearCanvas();
      setCanvasVisibility(false);
    };
  }, [isCameraOn, scriptLoaded, videoRef, canvasRef]);
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

