"use client";

import { useRef, useState } from "react";
import Script from "next/script";
import Camera from "@/components/camera/camera";
import Controls from "@/components/controls";
import { useCamera } from "@/bodyCam/useCamera";
import { usePose } from "@/bodyCam/usePose";

export default function WorkoutsSession() {
  const { videoRef, isCameraOn, startCamera, stopCamera } = useCamera();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);

  const { trackerReady, poseDetected } = usePose(videoRef, canvasRef, isCameraOn, scriptLoaded);

  return (
    <section className="space-y-6">
      <Script
        src="/@mediapipe/pose/pose.js"
        strategy="afterInteractive"
        onLoad={() => {
          console.log(" MediaPipe Script Loaded");
          setScriptLoaded(true);
        }}
      />

      <div className="rounded-[26px] border border-black/10 bg-white/70 px-5 py-5 shadow-[0_18px_40px_rgba(29,35,43,0.08)]">
        <Controls isCameraOn={isCameraOn} startCamera={startCamera} stopCamera={stopCamera} />
      </div>

      <div className="rounded-[30px] border border-black/10 bg-white/65 p-3 sm:p-4 md:p-6">
        <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Live tracking canvas
            </div>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              When the camera is active, pose landmarks render directly on top of the session feed.
            </p>
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
        <Camera videoRef={videoRef} canvasRef={canvasRef} isVisible={isCameraOn} />
        {isCameraOn && !poseDetected ? (
          <div className="mt-4 rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
            The camera is running, but the tracker has not found a clear full-body pose yet. Step back slightly, keep your full body in frame, and face the camera.
          </div>
        ) : null}
        {!isCameraOn ? (
          <div className="mt-4 rounded-2xl border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
            The preview area remains inactive until camera access is enabled for the session.
          </div>
        ) : null}
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