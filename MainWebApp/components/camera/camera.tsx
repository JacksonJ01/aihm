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
    >
      <div className="relative aspect-[4/3] w-full bg-slate-950">
        <video
          ref={videoRef}
          className={`absolute inset-0 h-full w-full object-contain ${isVisible ? "opacity-100" : "opacity-0"}`}
          playsInline
          muted
        />

        <canvas
          ref={canvasRef}
          className={`pointer-events-none absolute inset-0 h-full w-full ${isVisible ? "opacity-100" : "opacity-0"}`}
        />

        {!isVisible ? (
          <div className="absolute inset-0 flex items-center justify-center text-center text-sm font-medium text-white/65">
            Capture preview
          </div>
        ) : null}
      </div>
    </div>
  );
}