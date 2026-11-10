"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import Camera from "@/components/camera/camera";
import Controls from "@/components/controls";
import PoseEstimation from "@/components/pose/poseEstimation";
import { Button } from "@/components/ui/button";
import { useCamera } from "@/bodyCam/useCamera";
import { usePose } from "@/bodyCam/usePose";
import type { WorkoutExerciseKey } from "@/lib/workout-taxonomy";
import { WORKOUT_EXERCISE_CATALOG } from "../../lib/workout-taxonomy";
import { buildSessionDocument, downloadSessionJSON } from "../../lib/session-export";
import { saveToDataset } from "../../lib/dataset/client";

const POSE_SCRIPT_ID = "mediapipe-pose-script";
const POSE_SCRIPT_SRC = "/@mediapipe/pose/pose.js";

// Patch Module.arguments before MediaPipe loads to prevent Emscripten WASM errors
// MediaPipe's WASM binary tries to access deprecated Module.arguments property
if (typeof window !== "undefined" && typeof (window as any).Module === "undefined") {
  (window as any).Module = {
    arguments: [],
    onRuntimeInitialized: () => {}
  };
}

type WorkoutsSessionProps = {
  canTrainModel?: boolean;
};

type LoggedWorkoutParams = {
  exerciseName: string;
  customExerciseName: string;
  uploadVideoMode: "no" | "yes" | "yes-preview";
  cameraViewpoint: string;
  movementSpeed: string;
  formQuality: string;
  recordingLengthSeconds: number;
  setNumber: number;
  repTarget: number;
  saveMp4: boolean;
};

const DEFAULT_LOGGED_WORKOUT_PARAMS: LoggedWorkoutParams = {
  exerciseName: "--Select--",
  customExerciseName: "",
  uploadVideoMode: "no",
  cameraViewpoint: "center-mid",
  movementSpeed: "normal",
  formQuality: "good",
  recordingLengthSeconds: 10,
  setNumber: 1,
  repTarget: 0,
  saveMp4: false,
};

export default function WorkoutsSession({ canTrainModel = false }: WorkoutsSessionProps) {
  const { videoRef, isCameraOn, startCamera, stopCamera } = useCamera();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [shouldLoadPose, setShouldLoadPose] = useState(false);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [, setScriptError] = useState<string | null>(null);
  const [isSavingExercise, setIsSavingExercise] = useState(false);
  const [isPanelExpanded, setIsPanelExpanded] = useState(false);
  const [isTelemetryExpanded, setIsTelemetryExpanded] = useState(true);
  const [loggedWorkoutParams, setLoggedWorkoutParams] = useState<LoggedWorkoutParams>(DEFAULT_LOGGED_WORKOUT_PARAMS);
  const [isRecording, setIsRecording] = useState(false);
  const [lastExportedName, setLastExportedName] = useState<string | null>(null);
  const [isSavingToDataset, setIsSavingToDataset] = useState(false);
  const [datasetSaveMessage, setDatasetSaveMessage] = useState<string | null>(null);
  const [customVideoFile, setCustomVideoFile] = useState<File | null>(null);
  const [uploadedVideoUrl, setUploadedVideoUrl] = useState<string | null>(null);
  const [isUploadedVideoReady, setIsUploadedVideoReady] = useState(false);
  const loadedUploadSourceRef = useRef<string | null>(null);
  const [frozenTelemetry, setFrozenTelemetry] = useState<{
    elapsed: string;
    fps: string;
    frames: number;
    currentSet: number;
    poseScore: string;
    status: string;
  } | null>(null);

  const isUploadedVideoModeEnabled = loggedWorkoutParams.uploadVideoMode !== "no";
  const isUploadedVideoPreviewMode = loggedWorkoutParams.uploadVideoMode === "yes-preview";
  const isPoseSourceActive = isCameraOn || (isUploadedVideoModeEnabled && isUploadedVideoReady);
  const showVideoPreview = isCameraOn || (isUploadedVideoPreviewMode && isUploadedVideoReady);

  const handleStartCamera = async () => {
    setLoggedWorkoutParams((current) => ({
      ...current,
      uploadVideoMode: "no",
    }));
    setCustomVideoFile(null);
    setUploadedVideoUrl((currentUrl) => {
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
      }

      return null;
    });
    setIsUploadedVideoReady(false);
    setFrozenTelemetry(null);
    clearFrameBuffer();
    setIsRecording(false);
    setLastExportedName(null);
    setDatasetSaveMessage(null);
    setShouldLoadPose(true);
    await startCamera();
  };

  const handleStopCamera = () => {
    const buf = frameBufferRef.current;
    const lastFrame = buf.length > 0 ? buf[buf.length - 1] : null;
    const frozenElapsed = lastFrame ? lastFrame.timestampMs / 1000 : 0;
    const frozenFps = buf.length > 1 && frozenElapsed > 0 ? (buf.length - 1) / frozenElapsed : 0;
    const frozenScores = buf.map((f) => f.poseScore).filter((s): s is number => s !== null);
    const frozenPoseScore = frozenScores.length > 0
      ? frozenScores.reduce((sum, s) => sum + s, 0) / frozenScores.length
      : null;
    setFrozenTelemetry({
      elapsed: `${frozenElapsed.toFixed(2)}s`,
      fps: frozenFps.toFixed(1),
      frames: buf.length,
      currentSet,
      poseScore: frozenPoseScore !== null ? frozenPoseScore.toFixed(3) : "--",
      status: isRecording ? "Recording" : "Camera active",
    });
    stopCamera();
    clearFrameBuffer();
    setIsRecording(false);
  };

  useEffect(() => {
    if (typeof window === "undefined" || !shouldLoadPose) {
      return;
    }

    let isMounted = true;

    // Ensure Module object exists and prevent WASM abort on arguments access
    if (!(window as any).Module) {
      (window as any).Module = {
        arguments: [],
        onRuntimeInitialized: () => {},
        preloadedWasm: {}
      };
    }

    // Override arguments property to prevent Emscripten abort
    try {
      Object.defineProperty((window as any).Module, "arguments", {
        value: [],
        writable: true,
        configurable: true,
      });
    } catch {
      // Silent fail if property can't be defined
    }

    const onScriptLoad = () => {
      if (!isMounted) {
        return;
      }

      setScriptLoaded(true);
      setScriptError(null);
    };

    const onScriptError = () => {
      if (!isMounted) {
        return;
      }

      setScriptError("MediaPipe script failed to load.");
      setScriptLoaded(false);
    };

    if (typeof window.Pose !== "undefined") {
      setScriptLoaded(true);
      setScriptError(null);
      return () => {
        isMounted = false;
      };
    }

    let scriptEl = document.getElementById(POSE_SCRIPT_ID) as HTMLScriptElement | null;

    if (!scriptEl) {
      scriptEl = document.createElement("script");
      scriptEl.id = POSE_SCRIPT_ID;
      scriptEl.src = POSE_SCRIPT_SRC;
      scriptEl.async = true;
      scriptEl.addEventListener("load", onScriptLoad);
      scriptEl.addEventListener("error", onScriptError);
      document.body.appendChild(scriptEl);
    } else {
      scriptEl.addEventListener("load", onScriptLoad);
      scriptEl.addEventListener("error", onScriptError);

      if (typeof window.Pose !== "undefined") {
        onScriptLoad();
      }
    }

    return () => {
      isMounted = false;

      if (scriptEl) {
        scriptEl.removeEventListener("load", onScriptLoad);
        scriptEl.removeEventListener("error", onScriptError);
      }
    };
  }, [shouldLoadPose]);

  const { trackerReady, poseDetected, jointAngles, workoutDetections, activeWorkout, frameBufferRef, clearFrameBuffer } = usePose(videoRef, canvasRef, isPoseSourceActive, scriptLoaded);

  // Display only 4 selected exercises (not computing, just showing as dataset labels)
  const DISPLAY_EXERCISES = ["barbellBicepsCurl", "squat", "shoulderPress", "pullUp"] as const;
  const workoutDetectionCards = DISPLAY_EXERCISES.map(
    (exerciseKey) => {
      const detection = workoutDetections[exerciseKey as WorkoutExerciseKey];
      // Return static version (not tracked/updating)
      return {
        ...detection,
        isTracked: false,
        state: "untracked" as const,
        metric: null,
        stateDifference: null,
      };
    }
  );

  const handleTrainModelPanelOpen = () => {
    setIsSavingExercise((current) => {
      if (current) {
        return false;
      }

      setLoggedWorkoutParams(DEFAULT_LOGGED_WORKOUT_PARAMS);
      setCustomVideoFile(null);
      setUploadedVideoUrl((currentUrl) => {
        if (currentUrl) {
          URL.revokeObjectURL(currentUrl);
        }

        return null;
      });
      setIsUploadedVideoReady(false);
      setIsPanelExpanded(true);
      return true;
    });
  };

  const handleStartRecording = () => {
    clearFrameBuffer();
    setLastExportedName(null);

    if (!isCameraOn && isUploadedVideoModeEnabled && isUploadedVideoReady && videoRef.current) {
      videoRef.current.currentTime = 0;
      void videoRef.current.play().catch(() => {
        setDatasetSaveMessage("Unable to play uploaded video. Re-select the file and try again.");
      });
    }

    setIsRecording(true);
  };

  const handleStopAndExport = () => {
    setIsRecording(false);
    const frames = frameBufferRef.current;
    if (frames.length === 0) {
      setLastExportedName("No frames captured — start the camera or upload a video before recording.");
      return;
    }
    const selectedExercise =
      loggedWorkoutParams.exerciseName === "custom"
        ? loggedWorkoutParams.customExerciseName.trim()
        : loggedWorkoutParams.exerciseName.trim();
    const exerciseDef = WORKOUT_EXERCISE_CATALOG.find((exercise) => exercise.label === selectedExercise);
    const exerciseKey = exerciseDef?.key ?? (selectedExercise && selectedExercise !== "--Select--"
      ? selectedExercise.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")
      : "unlabeled");

    const doc = buildSessionDocument({
      ...loggedWorkoutParams,
      exerciseKey,
      subjectId: "unknown",
      includeAngles: true,
      includeVelocity: true,
      includeAcceleration: true,
      includeRangeStats: true,
      includeInterJointDistances: true,
      includeGlobalFeatures: true,
    }, frames);
    downloadSessionJSON(doc);
    setLastExportedName(
      `Exported ${frames.length} frames → session_${doc.metadata.exerciseKey}_${doc.metadata.sessionId.slice(0, 8)}.json`,
    );
  };

  const handleSaveToDataset = async () => {
    const frames = frameBufferRef.current;
    if (frames.length === 0) {
      setDatasetSaveMessage("No frames captured — start the camera or upload a video and record first.");
      return;
    }

    const viewParts = loggedWorkoutParams.cameraViewpoint.split("-");
    const camera_angle = viewParts[0] ?? "center";
    const camera_height = viewParts[1] ?? "mid";
    const selectedExercise =
      loggedWorkoutParams.exerciseName === "custom"
        ? loggedWorkoutParams.customExerciseName.trim()
        : loggedWorkoutParams.exerciseName.trim();
    const exerciseDef = WORKOUT_EXERCISE_CATALOG.find((exercise) => exercise.label === selectedExercise);
    const exerciseLabel = selectedExercise && selectedExercise !== "--Select--" ? selectedExercise : "Unlabeled exercise";
    const exerciseKey = exerciseDef?.key ?? (selectedExercise && selectedExercise !== "--Select--"
      ? selectedExercise.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")
      : "unlabeled");
    const durationS = frames.length > 1 ? frames[frames.length - 1].timestampMs / 1000 : 0;
    const fps = frames.length > 1 && durationS > 0 ? Math.round((frames.length - 1) / durationS) : 30;

    setIsSavingToDataset(true);
    setDatasetSaveMessage("Saving to dataset…");

    try {
      const result = await saveToDataset(
        {
          exercise: exerciseLabel,
          exerciseKey,
          subject: "unknown",
          camera_angle,
          camera_height,
          speed: loggedWorkoutParams.movementSpeed,
          form: loggedWorkoutParams.formQuality,
          fps,
          duration: durationS,
          set_number: loggedWorkoutParams.setNumber,
          rep_target: loggedWorkoutParams.repTarget,
          save_mp4: loggedWorkoutParams.saveMp4,
          frame_count: frames.length,
          included_channels: {
            angles: true,
            velocities: true,
            accelerations: true,
            rangeStats: true,
            interJointDistances: true,
            globalFeatures: true,
          },
        },
        frames,
      );
      setDatasetSaveMessage(
        `Saved ${result.recording_id} — ${result.frame_count} frames, ${result.duration.toFixed(1)}s @ ${result.fps} fps  → ${result.path}`,
      );
    } catch (error) {
      setDatasetSaveMessage(
        error instanceof Error ? `Save failed: ${error.message}` : "Save failed.",
      );
    } finally {
      setIsSavingToDataset(false);
    }
  };

  const updateLoggedWorkoutParams = <K extends keyof LoggedWorkoutParams>(field: K, value: LoggedWorkoutParams[K]) => {
    setLoggedWorkoutParams((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleExerciseNameChange = (exerciseName: string) => {
    updateLoggedWorkoutParams("exerciseName", exerciseName);
  };

  const handleUploadVideoModeChange = (mode: LoggedWorkoutParams["uploadVideoMode"]) => {
    updateLoggedWorkoutParams("uploadVideoMode", mode);
    setShouldLoadPose(true);

    if (mode === "no") {
      if (videoRef.current && !isCameraOn) {
        videoRef.current.pause();
        videoRef.current.removeAttribute("src");
        videoRef.current.load();
      }
      loadedUploadSourceRef.current = null;

      setCustomVideoFile(null);
      setUploadedVideoUrl((currentUrl) => {
        if (currentUrl) {
          URL.revokeObjectURL(currentUrl);
        }

        return null;
      });
      setIsUploadedVideoReady(false);
      setFrozenTelemetry(null);
      clearFrameBuffer();
      setIsRecording(false);
    }
  };

  const handleUploadedVideoFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files && event.target.files.length > 0
      ? event.target.files[0]
      : null;

    setCustomVideoFile(selectedFile);
    setShouldLoadPose(true);
    setIsUploadedVideoReady(false);
    setFrozenTelemetry(null);
    clearFrameBuffer();
    setIsRecording(false);

    setUploadedVideoUrl((currentUrl) => {
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
      }

      return selectedFile ? URL.createObjectURL(selectedFile) : null;
    });
  };

  useEffect(() => {
    const videoEl = videoRef.current;

    if (!videoEl || !isUploadedVideoModeEnabled) {
      return;
    }

    const handleLoadedMetadata = () => {
      setIsUploadedVideoReady(true);
      setFrozenTelemetry(null);
      void videoEl.play().catch(() => {
        setDatasetSaveMessage("Unable to autoplay uploaded video preview. Click Start Recording to begin.");
      });
    };

    const handleEnded = () => {
      setFrozenTelemetry(null);
      clearFrameBuffer();

      videoEl.currentTime = 0;
      void videoEl.play().catch(() => {
        setDatasetSaveMessage("Unable to continue video loop preview.");
      });
    };

    videoEl.loop = false;
    videoEl.muted = true;
    videoEl.playsInline = true;

    if (uploadedVideoUrl && loadedUploadSourceRef.current !== uploadedVideoUrl) {
      videoEl.srcObject = null;
      videoEl.src = uploadedVideoUrl;
      videoEl.load();
      loadedUploadSourceRef.current = uploadedVideoUrl;
    }

    videoEl.addEventListener("loadedmetadata", handleLoadedMetadata);
    videoEl.addEventListener("ended", handleEnded);

    return () => {
      videoEl.removeEventListener("loadedmetadata", handleLoadedMetadata);
      videoEl.removeEventListener("ended", handleEnded);
    };
  }, [uploadedVideoUrl, isUploadedVideoModeEnabled, clearFrameBuffer]);

  // Check if any recording has frames (for Stop & Export button)
  const hasFrames = frameBufferRef.current.length > 0;

  useEffect(() => {
    return () => {
      if (uploadedVideoUrl) {
        URL.revokeObjectURL(uploadedVideoUrl);
      }
    };
  }, [uploadedVideoUrl]);

  const isCustomExerciseSelected = loggedWorkoutParams.exerciseName === "custom";

  const capturedFrames = frameBufferRef.current.length;
  const elapsedSeconds = capturedFrames > 0 ? frameBufferRef.current[capturedFrames - 1].timestampMs / 1000 : 0;
  const liveFps = capturedFrames > 1 && elapsedSeconds > 0 ? (capturedFrames - 1) / elapsedSeconds : 0;
  const visibleScores = frameBufferRef.current
    .map((frame) => frame.poseScore)
    .filter((score): score is number => score !== null);
  const averagePoseScore = visibleScores.length > 0
    ? visibleScores.reduce((sum, score) => sum + score, 0) / visibleScores.length
    : null;

  const selectedExercise =
    loggedWorkoutParams.exerciseName === "custom"
      ? loggedWorkoutParams.customExerciseName.trim()
      : loggedWorkoutParams.exerciseName.trim();
  const selectedTrackedExercise = WORKOUT_EXERCISE_CATALOG.find((exercise) => exercise.label === selectedExercise);
  const liveRepCount = selectedTrackedExercise ? workoutDetections[selectedTrackedExercise.key].reps : 0;
  const currentSet =
    loggedWorkoutParams.repTarget > 0
      ? loggedWorkoutParams.setNumber + Math.floor(liveRepCount / loggedWorkoutParams.repTarget)
      : loggedWorkoutParams.setNumber;

  return (
    <section className="space-y-6">
      <div className="rounded-[26px] border border-black/10 bg-white/70 px-5 py-5 shadow-[0_18px_40px_rgba(29,35,43,0.08)]">
        <Controls
          isCameraOn={isCameraOn}
          startCamera={handleStartCamera}
          stopCamera={handleStopCamera}
          canTrainModel={canTrainModel}
          onTrainModelClick={handleTrainModelPanelOpen}
          isTrainModelActive={isSavingExercise}
        />
      </div>

      {isSavingExercise && canTrainModel ? (
        <div className="rounded-[28px] border border-black/10 bg-white/78 px-4 py-4 shadow-[0_18px_40px_rgba(29,35,43,0.08)] sm:px-5 sm:py-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Logged workout parameters</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-foreground">Configure metadata and pose feature channels</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                This setup defines one labeled time-series sequence. Metadata tags the recording, and selected channels control what signals are captured per frame.
              </p>
            </div>
            <Button variant="outline" onClick={() => setIsPanelExpanded((current) => !current)} className="w-full sm:w-auto">
              {isPanelExpanded ? "Minimize" : "Expand"}
            </Button>
          </div>

          {isPanelExpanded ? (
            <>

          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Exercise name:</span>
              <select
                value={loggedWorkoutParams.exerciseName}
                onChange={(event) => handleExerciseNameChange(event.target.value)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="--Select--">--Select--</option>
                {WORKOUT_EXERCISE_CATALOG.map((exercise) => (
                  <option key={exercise.key} value={exercise.label}>{exercise.label}</option>
                ))}
                <option value="custom">Custom</option>
              </select>
            </label>

            {isCustomExerciseSelected ? (
              <label className="flex flex-col gap-2">
                <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Custom exercise name</span>
                <input
                  type="text"
                  value={loggedWorkoutParams.customExerciseName}
                  onChange={(event) => updateLoggedWorkoutParams("customExerciseName", event.target.value)}
                  className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
                  placeholder="Type custom exercise"
                />
              </label>
            ) : null}

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Upload video</span>
              <select
                value={loggedWorkoutParams.uploadVideoMode}
                onChange={(event) => handleUploadVideoModeChange(event.target.value as LoggedWorkoutParams["uploadVideoMode"])}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
                <option value="yes-preview">Yes - Preview</option>
              </select>
            </label>

            {isUploadedVideoModeEnabled ? (
              <label className="flex flex-col gap-2">
                <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Video file</span>
                <input
                  type="file"
                  accept="video/*,.mp4,.mov,.m4v,.webm,.avi,.mkv"
                  onChange={handleUploadedVideoFileChange}
                  className="h-10 rounded-xl border border-black/10 bg-white px-3 py-1 text-sm text-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-slate-950 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white"
                />
                {customVideoFile ? (
                  <span className="text-xs text-muted-foreground">Selected: {customVideoFile.name}</span>
                ) : null}
              </label>
            ) : null}

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Camera viewpoint</span>
              <select
                value={loggedWorkoutParams.cameraViewpoint}
                onChange={(event) => updateLoggedWorkoutParams("cameraViewpoint", event.target.value)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="left-high">Left high</option>
                <option value="left-mid">Left mid</option>
                <option value="left-low">Left low</option>
                <option value="center-high">Center high</option>
                <option value="center-mid">Center mid</option>
                <option value="center-low">Center low</option>
                <option value="right-high">Right high</option>
                <option value="right-mid">Right mid</option>
                <option value="right-low">Right low</option>
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Movement speed</span>
              <select
                value={loggedWorkoutParams.movementSpeed}
                onChange={(event) => updateLoggedWorkoutParams("movementSpeed", event.target.value)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="slow">Slow</option>
                <option value="normal">Normal</option>
                <option value="fast">Fast</option>
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Form quality</span>
              <select
                value={loggedWorkoutParams.formQuality}
                onChange={(event) => updateLoggedWorkoutParams("formQuality", event.target.value)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="good">Good</option>
                <option value="bad">Bad</option>
                <option value="alternate">Alternate</option>
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Recording length (seconds)</span>
              <select
                value={loggedWorkoutParams.recordingLengthSeconds}
                onChange={(event) => updateLoggedWorkoutParams("recordingLengthSeconds", Number(event.target.value) || 10)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={15}>15</option>
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Set number</span>
              <input
                type="number"
                min={1}
                max={20}
                value={loggedWorkoutParams.setNumber}
                onChange={(event) => updateLoggedWorkoutParams("setNumber", Number(event.target.value) || 1)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Rep target</span>
              <input
                type="number"
                min={0}
                max={200}
                value={loggedWorkoutParams.repTarget}
                onChange={(event) => updateLoggedWorkoutParams("repTarget", Number(event.target.value) || 0)}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-semibold tracking-[0.04em] text-muted-foreground whitespace-nowrap">Save .mp4</span>
              <select
                value={loggedWorkoutParams.saveMp4 ? "yes" : "no"}
                onChange={(event) => updateLoggedWorkoutParams("saveMp4", event.target.value === "yes")}
                className="h-10 rounded-xl border border-black/10 bg-white px-3 text-sm text-foreground"
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </label>
          </div>

          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={handleStartRecording}
                disabled={isRecording || !isPoseSourceActive}
                className="w-full sm:w-auto"
              >
                {isRecording ? "Recording…" : "Start Recording"}
              </Button>
              <Button
                onClick={handleStopAndExport}
                disabled={!isRecording && !hasFrames && !isPoseSourceActive}
                variant="secondary"
                className="w-full sm:w-auto"
              >
                {isRecording ? "Stop & Export JSON" : "Export JSON"}
              </Button>
              <Button
                onClick={() => { void handleSaveToDataset(); }}
                disabled={isRecording || isSavingToDataset || (!isPoseSourceActive && frameBufferRef.current.length === 0)}
                variant="outline"
                className="w-full sm:w-auto"
              >
                {isSavingToDataset ? "Saving…" : "Save to Dataset"}
              </Button>
            </div>
            <div className="flex flex-col gap-1">
              {lastExportedName ? (
                <p className="text-sm leading-5 text-muted-foreground">{lastExportedName}</p>
              ) : null}
              {datasetSaveMessage ? (
                <p className="text-sm leading-5 text-muted-foreground">{datasetSaveMessage}</p>
              ) : !isPoseSourceActive ? (
                <p className="text-sm leading-5 text-muted-foreground">Start the camera or choose an uploaded video source first, then begin recording.</p>
              ) : null}
            </div>
          </div>
            </>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-[30px] border border-black/10 bg-white/65 px-3 pb-3 pt-1 sm:px-4 sm:pb-4 sm:pt-2 md:px-6 md:pb-6 md:pt-2">
        <div className="mb-0 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Live tracking studio
            </div>
          </div>
          <div className="w-fit self-start rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-medium text-foreground md:self-auto">
            {!scriptLoaded
              ? "Loading tracker"
              : isPoseSourceActive
                ? poseDetected
                  ? "Tracking active"
                  : "Source live, finding pose"
                : trackerReady
                  ? "Tracker ready"
                  : "Warming tracker"}
          </div>
        </div>

        {activeWorkout ? (
          <div className="mb-4 rounded-[22px] border border-black/10 bg-slate-950 px-4 py-3 text-sm text-white shadow-[0_14px_30px_rgba(15,23,42,0.18)]">
            <div className="text-xs uppercase tracking-[0.18em] text-white/60">Current workout hypothesis</div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium">
              <span>{activeWorkout.label}</span>
              <span className="text-white/60">{activeWorkout.state}</span>
              <span className="text-white/60">
                {activeWorkout.stateDifference === null ? "state difference n/a" : `state difference ${(activeWorkout.stateDifference * 100).toFixed(0)}%`}
              </span>
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-[minmax(120px,0.48fr)_minmax(0,2.04fr)_minmax(120px,0.48fr)] md:items-start xl:gap-6">
          <div className="order-1 min-w-0 md:order-1 md:col-start-1">
            <PoseEstimation
              jointAngles={jointAngles}
              trackerReady={trackerReady}
              poseDetected={poseDetected}
              isCameraOn={isPoseSourceActive}
              side="left"
              className="md:h-[392px] lg:h-[432px]"
            />
          </div>

          <div className="order-2 flex min-w-0 md:order-2 md:col-start-2 md:h-full md:items-start md:justify-start">
            <div className="flex w-full flex-col gap-4">
              <Camera videoRef={videoRef} canvasRef={canvasRef} isVisible={showVideoPreview} />

              <div className="rounded-[22px] border border-black/10 bg-white/78 px-4 py-3 shadow-[0_10px_22px_rgba(29,35,43,0.06)]">
                <div className="flex items-start justify-between gap-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                    {frozenTelemetry ? "Past live telemetry" : "Live telemetry"}
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => setIsTelemetryExpanded((current) => !current)}
                    className="h-7 px-2.5 text-xs"
                  >
                    {isTelemetryExpanded ? "Minimize" : "Expand"}
                  </Button>
                </div>

                {isTelemetryExpanded ? (
                <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Recording status</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry
                        ? frozenTelemetry.status
                        : isPoseSourceActive
                          ? isRecording ? "Recording" : "Source active"
                          : "Idle"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Elapsed</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry ? frozenTelemetry.elapsed : `${elapsedSeconds.toFixed(2)}s`}
                    </div>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Live FPS</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry ? frozenTelemetry.fps : liveFps.toFixed(1)}
                    </div>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Captured frames</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry ? frozenTelemetry.frames : capturedFrames}
                    </div>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Current Set / Rep Target</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry ? `${frozenTelemetry.currentSet} / ${loggedWorkoutParams.repTarget}` : `${currentSet} / ${loggedWorkoutParams.repTarget}`}
                    </div>
                  </div>
                  <div className="rounded-lg border border-black/10 bg-background/70 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Pose score (avg)</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {frozenTelemetry ? frozenTelemetry.poseScore : averagePoseScore === null ? "0.000" : averagePoseScore.toFixed(3)}
                    </div>
                  </div>
                </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="order-3 min-w-0 md:order-3 md:col-start-3">
            <PoseEstimation
              jointAngles={jointAngles}
              trackerReady={trackerReady}
              poseDetected={poseDetected}
              isCameraOn={isPoseSourceActive}
              side="right"
              className="md:h-[392px] lg:h-[432px]"
            />
          </div>
        </div>

        <div className="mt-4 rounded-[28px] border border-black/10 bg-white/72 px-4 py-4 shadow-[0_18px_40px_rgba(29,35,43,0.08)] sm:px-5 sm:py-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Exercise reference</div>
              <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-foreground">Selected exercise labels (display only)</h3>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {workoutDetectionCards.map((detection) => (
              <article key={detection.key} className="rounded-[22px] border border-black/10 bg-background/70 px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">{detection.label}</div>
                    <div className="mt-1 text-xs uppercase tracking-[0.14em] text-muted-foreground">dataset label</div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
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