"use client";

import { useEffect } from "react";

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
  scriptLoaded: boolean
) {
  useEffect(() => {
    // ✅ CRITICAL GUARD
    if (!isCameraOn || !scriptLoaded || !videoRef.current || !canvasRef.current) return;
    if (!(window as any).Pose) return;
    
    console.log("Pose started");

    const pose = new (window as any).Pose({
        locateFile: (file: string) => `/@mediapipe/pose/${file}`,
    });

    // Detect mobile devices (use userAgentData when available)
    const isMobileDevice = typeof navigator !== "undefined" &&
      ((navigator as any).userAgentData?.mobile ?? /Mobi|Android|iPhone|iPad|iPod|Windows Phone/.test(navigator.userAgent));

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

    pose.onResults((results: PoseResults) => {
      const canvas = canvasRef.current;
      // if (!canvas) return;
      const ctx = canvas?.getContext("2d");
      if (!ctx || !results.poseLandmarks || !canvas) return;

      // Clearing Previous Frame
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Drawing Landmark Points
      results.poseLandmarks.forEach((point: PoseLandmark, index: number) => {
        const isTargetJoint = EXERCISE_LANDMARKS.includes(index);
        const isVisible = (point.visibility ?? 0) > 0.6
        
        if (isTargetJoint && isVisible) {

            ctx.beginPath();
            ctx.arc(
                point.x * canvas.width,
                point.y * canvas.height,
                10,
                0,
                2 * Math.PI
            );
            ctx.fillStyle = "rgba(255, 47, 0, 0.5)"; // Semi-transparent red
            ctx.fill();

            ctx.beginPath();
            ctx.arc(
                point.x * canvas.width,
                point.y * canvas.height,
                5,
                0,
                2 * Math.PI
            );
            ctx.fillStyle = "rgba(255, 47, 0, 0.5)"; // Semi-transparent red
            ctx.fill();

            // Label
            // ctx.fillStyle = "rgba(255, 47, 0, 0.8)";
            // ctx.font = "10px Arial;";
            // ctx.fillText(index.toString(), point.x * canvas.width + 10, point.y * canvas.height);
           
            console.log(results.poseLandmarks);
        }
      });
    });

    let animationFrameId: number;

    const run = async () => {
      if (videoRef.current && isCameraOn) {
        if (videoRef.current.readyState >= 2) { // 0 = HAVE_NOTHING, 1 = HAVE_METADATA, 2 = HAVE_CURRENT_DATA, 3 = HAVE_FUTURE_DATA, 4 = HAVE_ENOUGH_DATA
            await pose.send({ image: videoRef.current });
        }
      }

      animationFrameId = requestAnimationFrame(run);
    };

    run();

    return () => {
      cancelAnimationFrame(animationFrameId);
      // Free Up GPU Mem
      if (pose) pose.close();

      // Clear Canvas On Stop
      const canvas = canvasRef.current;
      if (canvas) {
          const ctx = canvas.getContext("2d")
          
          if (ctx) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
          } 
        
      }
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

