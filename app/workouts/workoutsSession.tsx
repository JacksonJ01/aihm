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

  usePose(videoRef, canvasRef, isCameraOn, scriptLoaded);

  return (
    <section>
      <Script
        src="/@mediapipe/pose/pose.js"
        onLoad={() => {
          console.log(" MediaPipe Script Loaded");
          setScriptLoaded(true);
        }}
      />

      <div style={{ marginTop: 12 }}>
        <Controls isCameraOn={isCameraOn} startCamera={startCamera} stopCamera={stopCamera} />
      </div>

      <div style={{ marginTop: 20, position: "relative" }}>
        <Camera videoRef={videoRef} canvasRef={canvasRef} />
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