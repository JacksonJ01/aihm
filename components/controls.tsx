"use client";

import React from "react";

import { Button } from "@/components/ui/button";

type ControlsProps = {
  isCameraOn: boolean;
  startCamera: () => void;
  stopCamera: () => void;
};

export default function Controls({ isCameraOn, startCamera, stopCamera }: ControlsProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          Camera controls
        </div>
        <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
          Camera access, feed visibility, and cleanup behavior are managed here within the live session.
        </p>
      </div>
      {!isCameraOn ? (
        <Button onClick={startCamera} className="w-full sm:w-auto sm:shrink-0">
          Start Camera
        </Button>
      ) : (
        <Button onClick={stopCamera} variant="outline" className="w-full sm:w-auto sm:shrink-0">
          Stop Camera
        </Button>
      )}
    </div>
  );
}
