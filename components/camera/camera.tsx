"use client";

import React from "react";

type Props = {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  isVisible: boolean;
};

export default function Camera({ videoRef, canvasRef, isVisible }: Props) {
  return (
    <div
      className="relative mx-auto w-full max-w-[720px] overflow-hidden rounded-[28px] border border-black/10 bg-slate-950 shadow-[0_24px_60px_rgba(15,23,42,0.24)]"
      style={{ display: isVisible ? "block" : "none" }}
    >
      <div className="relative aspect-[4/3] w-full bg-slate-950">
        <video
          ref={videoRef}
          className="absolute inset-0 h-full w-full object-contain"
          playsInline
          muted
        />

        <canvas
          ref={canvasRef}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
          }}
        />
      </div>
    </div>
  );
}