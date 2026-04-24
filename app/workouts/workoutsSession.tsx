"use client";

import { useEffect, useRef, useState } from "react";
import Camera from "@/components/camera/camera";
import Controls from "@/components/controls";
import PoseEstimation from "@/components/pose/poseEstimation";
import { useCamera } from "@/bodyCam/useCamera";
import { usePose } from "@/bodyCam/usePose";
import { WORKOUT_DETECTION_ORDER } from "@/lib/workout-detections";

const POSE_SCRIPT_ID = "mediapipe-pose-script";
const POSE_SCRIPT_SRC = "/@mediapipe/pose/pose.js";

export default function WorkoutsSession() {
  const { videoRef, isCameraOn, startCamera, stopCamera } = useCamera();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [scriptError, setScriptError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    let isMounted = true;
    let scriptAddedByThisComponent = false;

    const onScriptLoad = () => {
      if (!isMounted) {
        return;
      }

      setScriptLoaded(true);
      setScriptError(null);
    };

    const onScriptError = () => {
      if (!isMounted) {
        return;
      }

      setScriptError("MediaPipe script failed to load.");
      setScriptLoaded(false);
    };

    if (typeof window.Pose !== "undefined") {
      setScriptLoaded(true);
      setScriptError(null);
      return () => {
        isMounted = false;
      };
    }

    let scriptEl = document.getElementById(POSE_SCRIPT_ID) as HTMLScriptElement | null;

    if (!scriptEl) {
      scriptEl = document.createElement("script");
      scriptEl.id = POSE_SCRIPT_ID;
      scriptEl.src = POSE_SCRIPT_SRC;
      scriptEl.async = true;
      scriptEl.setAttribute("data-managed-by", "workouts-session");
      scriptEl.addEventListener("load", onScriptLoad);
      scriptEl.addEventListener("error", onScriptError);
      document.body.appendChild(scriptEl);
      scriptAddedByThisComponent = true;
    } else {
      scriptEl.addEventListener("load", onScriptLoad);
      scriptEl.addEventListener("error", onScriptError);

      if (typeof window.Pose !== "undefined") {
        onScriptLoad();
      }
    }

    return () => {
      isMounted = false;

      if (scriptEl) {
        scriptEl.removeEventListener("load", onScriptLoad);
        scriptEl.removeEventListener("error", onScriptError);
      }

      if (scriptAddedByThisComponent && scriptEl?.parentNode) {
        scriptEl.parentNode.removeChild(scriptEl);
      }

      // Release the global constructor when leaving the workout page so the tab owns the asset lifecycle.
      if (typeof window !== "undefined" && scriptAddedByThisComponent) {
        delete window.Pose;
      }

      setScriptLoaded(false);
      setScriptError(null);
    };
  }, []);

  const { trackerReady, poseDetected, jointAngles, workoutDetections } = usePose(videoRef, canvasRef, isCameraOn, scriptLoaded);

  const workoutDetectionCards = WORKOUT_DETECTION_ORDER.map((exerciseKey) => workoutDetections[exerciseKey]);

  return (
    <section className="space-y-6">
      <div className="rounded-[26px] border border-black/10 bg-white/70 px-5 py-5 shadow-[0_18px_40px_rgba(29,35,43,0.08)]">
        <Controls isCameraOn={isCameraOn} startCamera={startCamera} stopCamera={stopCamera} />
      </div>

      <div className="rounded-[30px] border border-black/10 bg-white/65 p-3 sm:p-4 md:p-6">
        <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Live tracking studio
            </div>
          </div>
          <div className="w-fit self-start rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-medium text-foreground md:self-auto">
            {!scriptLoaded
              ? "Loading tracker"
              : isCameraOn
                ? poseDetected
                  ? "Tracking active"
                  : "Camera live, finding pose"
                : trackerReady
                  ? "Tracker ready"
                  : "Warming tracker"}
          </div>
        </div>

        <div className="space-y-4 lg:hidden">
          <div className="space-y-4 min-w-0">
            <Camera videoRef={videoRef} canvasRef={canvasRef} isVisible={isCameraOn} />
            {scriptError ? (
              <div className="rounded-2xl border border-dashed border-red-300/70 bg-red-50 px-4 py-4 text-sm leading-6 text-red-700">
                {scriptError} Check the browser console and verify that /@mediapipe/pose/pose.js is accessible.
              </div>
            ) : null}
            {isCameraOn && !poseDetected ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                The camera is running, but the tracker has not found a clear full-body pose yet. Step back slightly, keep your full body in frame, and face the camera.
              </div>
            ) : null}
            {!isCameraOn ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                The preview area remains inactive until camera access is enabled for the session.
              </div>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <PoseEstimation
              jointAngles={jointAngles}
              trackerReady={trackerReady}
              poseDetected={poseDetected}
              isCameraOn={isCameraOn}
              side="left"
              className="min-w-0"
            />

            <PoseEstimation
              jointAngles={jointAngles}
              trackerReady={trackerReady}
              poseDetected={poseDetected}
              isCameraOn={isCameraOn}
              side="right"
              className="min-w-0"
            />
          </div>
        </div>

        <div className="hidden lg:grid gap-4 lg:grid-cols-[minmax(150px,0.58fr)_minmax(0,1.54fr)_minmax(150px,0.58fr)] lg:items-start xl:gap-6">
          <PoseEstimation
            jointAngles={jointAngles}
            trackerReady={trackerReady}
            poseDetected={poseDetected}
            isCameraOn={isCameraOn}
            side="left"
            className="min-w-0"
          />

          <div className="space-y-4 min-w-0">
            <Camera videoRef={videoRef} canvasRef={canvasRef} isVisible={isCameraOn} />
            {scriptError ? (
              <div className="rounded-2xl border border-dashed border-red-300/70 bg-red-50 px-4 py-4 text-sm leading-6 text-red-700">
                {scriptError} Check the browser console and verify that /@mediapipe/pose/pose.js is accessible.
              </div>
            ) : null}
            {isCameraOn && !poseDetected ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                The camera is running, but the tracker has not found a clear full-body pose yet. Step back slightly, keep your full body in frame, and face the camera.
              </div>
            ) : null}
            {!isCameraOn ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                The preview area remains inactive until camera access is enabled for the session.
              </div>
            ) : null}
          </div>

          <PoseEstimation
            jointAngles={jointAngles}
            trackerReady={trackerReady}
            poseDetected={poseDetected}
            isCameraOn={isCameraOn}
            side="right"
            className="min-w-0"
          />
        </div>

        <div className="mt-4 rounded-[28px] border border-black/10 bg-white/72 px-4 py-4 shadow-[0_18px_40px_rgba(29,35,43,0.08)] sm:px-5 sm:py-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Hard-coded detections</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-foreground">Twenty-two workout labels aligned to the dataset taxonomy</h3>
            </div>
            <div className="text-sm text-muted-foreground">Only the exercises with hard-coded rules count reps right now; the rest are dataset labels ready for model training.</div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {workoutDetectionCards.map((detection) => (
              <article key={detection.key} className="rounded-[22px] border border-black/10 bg-background/70 px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">{detection.label}</div>
                    <div className="mt-1 text-xs uppercase tracking-[0.14em] text-muted-foreground">
                      {detection.isTracked ? detection.stage : "dataset label"}
                    </div>
                  </div>
                  <div className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">{String(detection.reps).padStart(2, "0")}</div>
                </div>
                <div className="mt-3 text-sm leading-6 text-muted-foreground">
                  Metric: {detection.metric === null ? "--" : `${detection.metric}°`}
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
// "use client";

// import { useRef, useState } from "react";
// import Script from "next/script";
// import Camera from "@/components/camera/camera";
// import Controls from "@/components/controls";
// import { useCamera } from "@/bodyCam/useCamera";
// import { usePose } from "@/bodyCam/usePose";

// export default function WorkoutsSession() {
//   const { videoRef, isCameraOn, startCamera, stopCamera } = useCamera();
//   const canvasRef = useRef<HTMLCanvasElement | null>(null);
//   const [scriptLoaded, setScriptLoaded] = useState(false);

//   usePose(videoRef, canvasRef, isCameraOn, scriptLoaded);

//   return (
//     <>
//       <Script src="/@mediapipe/pose/pose.js" onLoad={() => setScriptLoaded(true)} />
//       <Controls isCameraOn={isCameraOn} startCamera={startCamera} stopCamera={stopCamera} />
//       <div style={{ marginTop: 20 }}>
//         <Camera videoRef={videoRef} canvasRef={canvasRef} />
//       </div>
//     </>
//   );
// }