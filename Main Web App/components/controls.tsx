"use client";

import React from "react";

import { Button } from "@/components/ui/button";

type ControlsProps = {
  isCameraOn: boolean;
  startCamera: () => void;
  stopCamera: () => void;
  canTrainModel: boolean;
  onTrainModelClick?: () => void;
  isTrainModelActive?: boolean;
};

export default function Controls({ isCameraOn, startCamera, stopCamera, canTrainModel, onTrainModelClick, isTrainModelActive = false }: ControlsProps) {
  const handleTrainModel = () => {
    onTrainModelClick?.();
  };

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          Camera controls
        </div>
      </div>
      <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
        {!isCameraOn ? (
          <Button onClick={startCamera} className="w-full sm:w-auto sm:shrink-0">
            Start Camera
          </Button>
        ) : (
          <Button onClick={stopCamera} variant="outline" className="w-full sm:w-auto sm:shrink-0">
            Stop Camera
          </Button>
        )}
        {canTrainModel ? (
          <Button
            onClick={handleTrainModel}
            variant={isTrainModelActive ? "default" : "secondary"}
            className="w-full sm:w-auto sm:shrink-0"
            aria-pressed={isTrainModelActive}
          >
            {isTrainModelActive ? "Saving Exercise" : "Save Exercise Data"}
          </Button>
        ) : null}
      </div>
      {!canTrainModel ? (
        <p className="w-full text-xs leading-5 text-muted-foreground sm:order-3">
          Sign in to access model training.
        </p>
      ) : null}
    </div>
  );
}
