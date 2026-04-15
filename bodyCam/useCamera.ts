"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useCamera() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isCameraOn, setIsCameraOn] = useState(false);

  const resetVideoElement = useCallback(() => {
    if (!videoRef.current) {
      return;
    }

    videoRef.current.pause();
    videoRef.current.srcObject = null;
    videoRef.current.removeAttribute("src");
    videoRef.current.load();
  }, []);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    resetVideoElement();
    setIsCameraOn(false);
  }, [resetVideoElement]);

  // 🎥 Start camera
  const startCamera = useCallback(async () => {
    try {
      stopCamera();

      const isMobile = /Mobi|Android|iPhone|iPad|iPod|Windows Phone/.test(navigator.userAgent);
      const videoConstraints: MediaTrackConstraints = isMobile
        ? {
            width: { ideal: 480 },
            height: { ideal: 360 },
            aspectRatio: { ideal: 4 / 3 },
            facingMode: "user",
          }
        : {
            width: { ideal: 640 },
            height: { ideal: 480 },
            aspectRatio: { ideal: 4 / 3 },
          };

      const stream = await navigator.mediaDevices.getUserMedia({
        video: videoConstraints,
      });

      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      setIsCameraOn(true);
    } catch (error) {
      console.error("Camera error:", error);
      stopCamera();
    }
  }, [stopCamera]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopCamera();
      }
    };

    window.addEventListener("pagehide", stopCamera);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", stopCamera);
      stopCamera();
    };
  }, [stopCamera]);

  return {
    videoRef,
    isCameraOn,
    startCamera,
    stopCamera,
  };
}