"use client";

import React from "react";

type Props = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
};

export default function Camera({ videoRef, canvasRef }: Props) {
  return (
    <div style={{ position: "relative", width: 500 }}>
      <video
        ref={videoRef}
        style={{ width: 500 }}
        playsInline
        muted
      />

      <canvas
        ref={canvasRef}
        width={500}
        height={375}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
        }}
      />
    </div>
  );
}