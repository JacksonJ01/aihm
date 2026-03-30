"use client";

import { useEffect, useRef, useState } from "react";

export function useCamera() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isCameraOn, setIsCameraOn] = useState(false);

  const resetVideoElement = () => {
    if (!videoRef.current) {
      return;
    }

    videoRef.current.pause();
    videoRef.current.srcObject = null;
    videoRef.current.removeAttribute("src");
    videoRef.current.load();
  };

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    resetVideoElement();
    setIsCameraOn(false);
  };

  // 🎥 Start camera
  const startCamera = async () => {
    try {
      stopCamera();

      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
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
  };

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
  }, []);

  return {
    videoRef,
    isCameraOn,
    startCamera,
    stopCamera,
  };
}