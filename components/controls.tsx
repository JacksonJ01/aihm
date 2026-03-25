"use client";

import React from "react";

type ControlsProps = {
  isCameraOn: boolean;
  startCamera: () => void;
  stopCamera: () => void;
};

export default function Controls({ isCameraOn, startCamera, stopCamera }: ControlsProps) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      {!isCameraOn ? (
        <button onClick={startCamera}>Start Camera</button>
      ) : (
        <button onClick={stopCamera}>Stop Camera</button>
      )}
    </div>
  );
}
