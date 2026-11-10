"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileJson2,
  Pause,
  Play,
  RotateCcw,
  Save,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

const MOVEMENT_TYPES = ["N/A", "Carry", "Core", "Hinge", "Jump", "Lunge", "Locomotion", "Pull", "Push", "Rotate", "Squat"] as const;
const EXERCISES_BY_MOVEMENT: Record<string, string[]> = {
  "N/A": ["N/A"],
  Carry: ["FarmersCarry", "SuitcaseCarry", "OverheadCarry"],
  Core: ["Plank", "SidePlank", "DeadBug"],
  Hinge: ["RomanianDeadlift", "ConventionalDeadlift", "GoodMorning"],
  Jump: ["JumpSquat", "JumpingJack", "BroadJump"],
  Lunge: ["ForwardLunge", "ReverseLunge", "LateralLunge"],
  Locomotion: ["Walking", "RunningInPlace", "MountainClimber"],
  Pull: ["BicepsCurl", "BentOverRow", "PullUp"],
  Push: ["PushUp", "ShoulderPress", "BenchPress", "Dip"],
  Rotate: ["RussianTwist", "Woodchopper", "StandingTorsoRotation"],
  Squat: ["BodyweightSquat", "GobletSquat", "SumoSquat"],
};
const JOINTS = [
  "N/A", "Nose", "Left eye", "Right eye", "Left ear", "Right ear", "Mouth left", "Mouth right",
  "Left shoulder", "Right shoulder", "Left elbow", "Right elbow", "Left wrist", "Right wrist",
  "Left hip", "Right hip", "Left knee", "Right knee", "Left ankle", "Right ankle",
  "Left heel", "Right heel", "Left foot index", "Right foot index",
];
const ISSUE_TYPES = ["N/A", "Tracking quality", "Alignment", "Range of motion", "Tempo", "Stability", "Equipment", "Camera", "Other"];
const ISSUE_CATEGORIES = ["N/A", "Occlusion", "Low confidence", "Joint misalignment", "Excessive speed", "Insufficient range", "Compensation", "Setup", "Transition", "Other"];
const NUMBER_OPTIONS = ["N/A", ...Array.from({ length: 30 }, (_, index) => String(index + 1))];
const LAYER_ORDER = { activity: 0, set: 1, repetition: 2, phase: 3, form: 4, other: 5 } as const;
const LAYER_LABELS = {
  activity: "Activity Interval",
  set: "Set Interval",
  repetition: "Repetition Interval",
  phase: "Phase Interval",
  form: "Form Interval",
  other: "Other Interval",
} as const;
const LAYER_HINTS = {
  activity: "Broad movement activity; set values are inherited.",
  set: "Labels movement, exercise, and set number.",
  repetition: "Labels the repetition inside the selected set.",
  phase: "Labels eccentric, concentric, or hold.",
  form: "Labels observed form or tracking issues only.",
  other: "Setup, idle time, camera adjustment, or unrelated time.",
} as const;

type Layer = keyof typeof LAYER_LABELS;
type Boundary = "frame_interval" | "single_frame";
type FrameRow = Record<string, unknown>;

type Annotation = {
  annotationId: string;
  layer: Layer;
  boundary: Boundary;
  activity: string;
  movementType: string;
  exercise: string;
  setNumber: string;
  repNumber: string;
  phase: string;
  formState: string;
  issueTypes: string[];
  issueCategories: string[];
  affectedJoints: string[];
  notes: string;
  startFrame: number;
  endFrameExclusive: number;
  startTimeS: number;
  endTimeS: number;
  provenance: string;
  annotationVersion: string;
  updatedAt?: string;
};

type EditorForm = Pick<
  Annotation,
  "layer" | "boundary" | "activity" | "movementType" | "exercise" | "setNumber" | "repNumber" | "phase" | "formState" | "issueTypes" | "issueCategories" | "affectedJoints" | "notes"
>;

const EMPTY_FORM: EditorForm = {
  layer: "activity",
  boundary: "frame_interval",
  activity: "N/A",
  movementType: "N/A",
  exercise: "N/A",
  setNumber: "N/A",
  repNumber: "N/A",
  phase: "N/A",
  formState: "N/A",
  issueTypes: ["N/A"],
  issueCategories: ["N/A"],
  affectedJoints: ["N/A"],
  notes: "",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toFrame(value: unknown) {
  return Math.max(0, Math.floor(readNumber(value)));
}

function normalizeNA(value: unknown) {
  return value == null || value === "" || value === -1 || value === "-1" ? "N/A" : String(value);
}

function normalizeMulti(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.map(String) : ["N/A"];
  if (value == null || value === "") return ["N/A"];
  const values = String(value).split(",").map((item) => item.trim()).filter(Boolean);
  return values.length ? values : ["N/A"];
}

function normalizeLayer(value: unknown): Layer {
  const normalized = String(value || "other").toLowerCase().replace(/[\s/]+/g, "_");
  if (normalized.includes("activity")) return "activity";
  if (normalized.includes("set")) return "set";
  if (normalized.includes("repetition") || normalized === "rep") return "repetition";
  if (normalized.includes("phase")) return "phase";
  if (normalized.includes("form") || normalized.includes("error")) return "form";
  return "other";
}

function normalizeAnnotations(value: unknown): Annotation[] {
  if (!Array.isArray(value)) return [];
  return value.map((raw, index) => {
    const item = asRecord(raw);
    const start = toFrame(item.startFrame ?? item.start_frame ?? item.start ?? 0);
    const endRaw = item.endFrameExclusive ?? item.end_frame_exclusive ?? item.endFrame ?? item.end_frame ?? start + 1;
    const end = Math.max(start + 1, toFrame(endRaw));
    return {
      annotationId: String(item.annotationId || item.annotation_id || `A${String(index + 1).padStart(5, "0")}`),
      layer: normalizeLayer(item.layer || item.annotationType || item.annotation_type),
      boundary: (item.boundary === "single_frame" || end - start === 1) ? "single_frame" : "frame_interval",
      activity: String(item.activity || item.activityState || item.activity_state || "N/A"),
      movementType: String(item.movementType || item.movement_type || "N/A"),
      exercise: String(item.exercise || item.exerciseName || item.exercise_name || "N/A"),
      setNumber: normalizeNA(item.setNumber ?? item.set_id ?? item.set),
      repNumber: normalizeNA(item.repNumber ?? item.rep_id ?? item.rep),
      phase: String(item.phase || "N/A"),
      formState: String(item.formState || item.form || item.form_label || "N/A"),
      issueTypes: normalizeMulti(item.issueTypes || item.issue_type),
      issueCategories: normalizeMulti(item.issueCategories || item.issue_category || item.error_category),
      affectedJoints: normalizeMulti(item.affectedJoints || item.affected_joints),
      notes: String(item.notes || ""),
      startFrame: start,
      endFrameExclusive: end,
      startTimeS: readNumber(item.startTimeS ?? item.start_time_s),
      endTimeS: readNumber(item.endTimeS ?? item.end_time_s),
      provenance: String(item.provenance || "web-import"),
      annotationVersion: String(item.annotationVersion || "web.v1"),
      updatedAt: typeof item.updatedAt === "string" ? item.updatedAt : undefined,
    };
  });
}

function normalizeSelection(values: string[]) {
  const filtered = values.length > 1 ? values.filter((value) => value !== "N/A") : values;
  return filtered.length ? filtered : ["N/A"];
}

function formatExercise(value: string) {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <span className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{children}</span>;
}

const inputClass = "w-full rounded-2xl border border-black/10 bg-background/70 px-4 py-3 text-sm text-foreground outline-none transition focus:border-primary/50 focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-55";

export default function AnnotationStudio() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const videoUrlRef = useRef<string | null>(null);
  const [videoName, setVideoName] = useState("");
  const [fps, setFps] = useState(30);
  const [frameCount, setFrameCount] = useState(0);
  const [durationS, setDurationS] = useState(0);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [frameRows, setFrameRows] = useState<FrameRow[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [sessionMetadata, setSessionMetadata] = useState<Record<string, unknown>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rangeStart, setRangeStart] = useState<number | null>(null);
  const [jumpFrames, setJumpFrames] = useState(50);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [timelineFilter, setTimelineFilter] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState("No video loaded. Select a custom video to begin.");
  const [form, setForm] = useState<EditorForm>(EMPTY_FORM);

  const sortedAnnotations = useMemo(
    () => [...annotations].sort((left, right) => left.startFrame - right.startFrame || LAYER_ORDER[left.layer] - LAYER_ORDER[right.layer] || left.endFrameExclusive - right.endFrameExclusive),
    [annotations],
  );

  const frameRowsByFrame = useMemo(() => new Map(frameRows.map((row, index) => [toFrame(row.frameIndex ?? row.frame_id ?? index), row])), [frameRows]);
  const timeSortedRows = useMemo(
    () => [...frameRows].sort((left, right) => readNumber(left.timeElapsedS ?? left.timestampS ?? left.timestamp_s) - readNumber(right.timeElapsedS ?? right.timestampS ?? right.timestamp_s)),
    [frameRows],
  );
  const visibleAnnotations = useMemo(() => {
    const query = timelineFilter.trim().toLowerCase();
    if (!query) return sortedAnnotations;
    return sortedAnnotations.filter((annotation) => [
      annotation.annotationId, LAYER_LABELS[annotation.layer], annotation.boundary, annotation.activity,
      annotation.movementType, annotation.exercise, annotation.setNumber, annotation.repNumber,
      annotation.phase, ...annotation.issueTypes, ...annotation.issueCategories, ...annotation.affectedJoints, annotation.notes,
    ].join(" ").toLowerCase().includes(query));
  }, [sortedAnnotations, timelineFilter]);

  const currentContext = useMemo(() => {
    const context = { activity: "N/A", movementType: "N/A", exercise: "N/A", setNumber: "N/A", repNumber: "N/A", phase: "N/A" };
    const candidates = sortedAnnotations.filter((annotation) => annotation.startFrame <= currentFrame && currentFrame < annotation.endFrameExclusive);
    for (const item of candidates) {
      if (item.activity !== "N/A") context.activity = item.activity;
      if (item.movementType !== "N/A") context.movementType = item.movementType;
      if (item.exercise !== "N/A") context.exercise = item.exercise;
      if (item.setNumber !== "N/A") context.setNumber = item.setNumber;
      if (item.repNumber !== "N/A") context.repNumber = item.repNumber;
      if (item.phase !== "N/A") context.phase = item.phase;
    }
    return context;
  }, [currentFrame, sortedAnnotations]);

  const frameTime = useCallback((frame: number) => {
    const row = frameRowsByFrame.get(toFrame(frame));
    if (row) return readNumber(row.timeElapsedS ?? row.timestampS ?? row.timestamp_s, frame / fps);
    return frame / fps;
  }, [fps, frameRowsByFrame]);

  const seekFrame = useCallback((requested: number) => {
    const maxFrame = Math.max(0, frameCount - 1 || Math.floor(durationS * fps));
    const bounded = Math.max(0, Math.min(Math.floor(requested || 0), maxFrame));
    setCurrentFrame(bounded);
    if (videoRef.current?.readyState) {
      videoRef.current.currentTime = Math.min(frameTime(bounded), videoRef.current.duration || frameTime(bounded));
    }
  }, [durationS, fps, frameCount, frameTime]);

  const resetForm = useCallback(() => {
    setSelectedId(null);
    setRangeStart(null);
    setForm(EMPTY_FORM);
  }, []);

  const nextAnnotationId = useCallback(() => {
    const used = new Set(annotations.map((item) => item.annotationId));
    let index = annotations.length + 1;
    while (used.has(`A${String(index).padStart(5, "0")}`)) index += 1;
    return `A${String(index).padStart(5, "0")}`;
  }, [annotations]);

  const setField = useCallback(<K extends keyof EditorForm>(key: K, value: EditorForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }, []);

  const loadAnnotation = useCallback((annotation: Annotation) => {
    setSelectedId(annotation.annotationId);
    setRangeStart(annotation.startFrame);
    setForm({
      layer: annotation.layer,
      boundary: annotation.boundary,
      activity: annotation.activity,
      movementType: annotation.movementType,
      exercise: annotation.exercise,
      setNumber: annotation.setNumber,
      repNumber: annotation.repNumber,
      phase: annotation.phase,
      formState: annotation.formState,
      issueTypes: annotation.issueTypes,
      issueCategories: annotation.issueCategories,
      affectedJoints: annotation.affectedJoints,
      notes: annotation.notes,
    });
    seekFrame(annotation.startFrame);
  }, [seekFrame]);

  const saveRange = useCallback(() => {
    if (!videoName && !durationS) {
      setStatus("Load a custom video before saving an annotation.");
      return;
    }
    const start = rangeStart ?? currentFrame;
    const end = form.boundary === "single_frame" ? start + 1 : Math.max(start + 1, currentFrame + 1);
    const existing = selectedId ? annotations.find((item) => item.annotationId === selectedId) : undefined;
    const annotation: Annotation = {
      ...(existing || {
        annotationId: nextAnnotationId(),
        provenance: "web-created",
        annotationVersion: "web.v1",
      }),
      ...form,
      startFrame: Math.min(start, end - 1),
      endFrameExclusive: end,
      startTimeS: frameTime(Math.min(start, end - 1)),
      endTimeS: frameTime(Math.max(start, end - 1)),
      updatedAt: new Date().toISOString(),
    };
    setAnnotations((current) => existing ? current.map((item) => item.annotationId === existing.annotationId ? annotation : item) : [...current, annotation]);
    setSelectedId(annotation.annotationId);
    setRangeStart(annotation.startFrame);
    setDirty(true);
    setStatus(`${existing ? "Updated" : "Saved"} ${annotation.annotationId}.`);
  }, [annotations, currentFrame, durationS, form, frameTime, nextAnnotationId, rangeStart, selectedId, videoName]);

  const exportPayload = useCallback((includeFrames: boolean) => ({
    schemaVersion: "aihumo.web.annotation.v1",
    compatibleWith: "aihumo.mobile.annotation.v1",
    generatedAt: new Date().toISOString(),
    source: "AIHuMo Web Annotation Studio",
    recording: { ...sessionMetadata, videoName, durationS, fps },
    annotations: sortedAnnotations,
    ...(includeFrames && frameRows.length ? { frames: frameRows } : {}),
  }), [durationS, fps, frameRows, sessionMetadata, sortedAnnotations, videoName]);

  const downloadJson = useCallback((includeFrames: boolean) => {
    const payload = exportPayload(includeFrames);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const name = (videoName || "aihumo_session").replace(/\.[^.]+$/, "");
    link.href = url;
    link.download = `${name}_${includeFrames ? "web_session" : "annotations"}.json`;
    link.click();
    URL.revokeObjectURL(url);
    setDirty(false);
    setStatus(`Downloaded ${link.download}.`);
  }, [exportPayload, videoName]);

  const importPayload = useCallback((payload: unknown, sourceName: string) => {
    const data = asRecord(payload);
    const metadata = asRecord(data.recording ?? data.metadata ?? data.session);
    const timing = asRecord(data.frameTiming ?? data.timing);
    const importedFps = readNumber(timing.effectiveFps ?? timing.sourceFps ?? metadata.effectiveFps ?? metadata.sourceFps ?? data.fps, fps);
    const rows = data.frames ?? data.frameFeatures ?? data.featureRows;
    const nextRows = Array.isArray(rows) ? rows.map(asRecord) : [];
    const nextAnnotations = normalizeAnnotations(data.annotations ?? data);
    setSessionMetadata(metadata);
    setFps(importedFps || 30);
    setFrameRows(nextRows);
    setAnnotations(nextAnnotations);
    resetForm();
    setDirty(true);
    setStatus(`Loaded ${sourceName}: ${nextAnnotations.length} annotations and ${nextRows.length || "no explicit"} frame timing rows.`);
  }, [fps, resetForm]);

  const readJsonFile = useCallback(async (file: File, annotationsOnly: boolean) => {
    try {
      const payload: unknown = JSON.parse(await file.text());
      if (annotationsOnly) {
        const data = asRecord(payload);
        const nextAnnotations = normalizeAnnotations(data.annotations ?? payload);
        setAnnotations(nextAnnotations);
        resetForm();
        setDirty(true);
        setStatus(`Loaded ${nextAnnotations.length} annotations from ${file.name}.`);
      } else {
        importPayload(payload, file.name);
      }
    } catch (error) {
      setStatus(`Could not read ${file.name}: ${error instanceof Error ? error.message : "invalid JSON"}`);
    }
  }, [importPayload, resetForm]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editingText = target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);
      if (editingText && !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); seekFrame(currentFrame - 1); }
      if (event.key === "ArrowRight") { event.preventDefault(); seekFrame(currentFrame + 1); }
      if (event.key === "ArrowUp") { event.preventDefault(); seekFrame(currentFrame - jumpFrames); }
      if (event.key === "ArrowDown") { event.preventDefault(); seekFrame(currentFrame + jumpFrames); }
      if (event.key.toLowerCase() === "w") { event.preventDefault(); setRangeStart(currentFrame); setStatus(`Range start captured at frame ${currentFrame}.`); }
      if (event.key.toLowerCase() === "s") { event.preventDefault(); saveRange(); }
      if (event.key === " ") {
        event.preventDefault();
        if (videoRef.current?.paused) {
          videoRef.current.playbackRate = playbackSpeed;
          void videoRef.current.play();
        } else videoRef.current?.pause();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [currentFrame, jumpFrames, playbackSpeed, saveRange, seekFrame]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = playbackSpeed;
  }, [playbackSpeed]);

  useEffect(() => () => {
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
  }, []);

  useEffect(() => {
    if (!videoName || !annotations.length) return;
    const key = `aihumo:web-annotation:${videoName}`;
    try { localStorage.setItem(key, JSON.stringify(exportPayload(true))); } catch { /* local quota is optional */ }
  }, [annotations, exportPayload, videoName]);

  const handleVideoFile = useCallback((file?: File) => {
    if (!file) return;
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
    const url = URL.createObjectURL(file);
    videoUrlRef.current = url;
    setVideoName(file.name);
    setStatus(`${file.name} loaded locally. Add a session JSON to continue existing annotations.`);
    setDirty(true);
    if (videoRef.current) {
      videoRef.current.src = url;
      videoRef.current.load();
    }
    try {
      const autosave = localStorage.getItem(`aihumo:web-annotation:${file.name}`);
      if (autosave) importPayload(JSON.parse(autosave), "browser autosave");
    } catch { /* ignore invalid browser autosaves */ }
  }, [importPayload]);

  const handleMetadata = useCallback(() => {
    const duration = Number(videoRef.current?.duration) || 0;
    setDurationS(duration);
    const highestFrame = frameRows.reduce((highest, row, index) => Math.max(highest, toFrame(row.frameIndex ?? row.frame_id ?? index)), -1);
    setFrameCount(highestFrame >= 0 ? highestFrame + 1 : Math.max(1, Math.ceil(duration * fps)));
    setCurrentFrame(0);
  }, [fps, frameRows]);

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const time = Number(video.currentTime) || 0;
    if (frameRows.length) {
      let low = 0;
      let high = timeSortedRows.length - 1;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (readNumber(timeSortedRows[middle].timeElapsedS ?? timeSortedRows[middle].timestampS ?? timeSortedRows[middle].timestamp_s) < time) low = middle + 1;
        else high = middle;
      }
      const before = timeSortedRows[Math.max(0, low - 1)];
      const after = timeSortedRows[low];
      const nearest = before && Math.abs(readNumber(before.timeElapsedS ?? before.timestampS ?? before.timestamp_s) - time) <= Math.abs(readNumber(after.timeElapsedS ?? after.timestampS ?? after.timestamp_s) - time) ? before : after;
      setCurrentFrame(toFrame(nearest.frameIndex ?? nearest.frame_id ?? 0));
    } else {
      setCurrentFrame(Math.max(0, Math.round(time * fps)));
    }
  }, [fps, frameRows.length, timeSortedRows]);

  const resetWorkspace = useCallback(() => {
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
    videoUrlRef.current = null;
    if (videoRef.current) { videoRef.current.removeAttribute("src"); videoRef.current.load(); }
    setVideoName(""); setFrameRows([]); setAnnotations([]); setSessionMetadata({});
    setFrameCount(0); setDurationS(0); setCurrentFrame(0); setDirty(false); setIsPlaying(false);
    resetForm(); setStatus("Workspace reset. Select a custom video to begin.");
  }, [resetForm]);

  const formRules = useMemo(() => ({
    movementType: form.layer === "set",
    exercise: form.layer === "set",
    setNumber: form.layer === "set",
    repNumber: form.layer === "repetition",
    phase: form.layer === "phase",
    formState: form.layer === "form",
    formDetails: form.layer === "form",
  }), [form.layer]);

  const effectiveForm = useMemo(() => ({
    ...form,
    movementType: formRules.movementType ? form.movementType : currentContext.movementType,
    exercise: formRules.exercise ? form.exercise : currentContext.exercise,
    setNumber: formRules.setNumber ? form.setNumber : currentContext.setNumber,
    repNumber: formRules.repNumber ? form.repNumber : currentContext.repNumber,
    phase: formRules.phase ? form.phase : currentContext.phase,
    activity: form.layer === "form" ? currentContext.activity : form.activity,
  }), [currentContext, form, formRules]);

  useEffect(() => {
    if (selectedId) return;
    setForm((current) => ({ ...current, ...effectiveForm }));
    // Only inherit context when the selected layer changes or timeline context changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentContext, form.layer, selectedId]);

  const inputStyle = inputClass;
  const metric = (label: string, value: string) => (
    <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">{value}</div>
    </div>
  );

  return (
    <div className="space-y-6">
      <section className="surface-card px-5 py-6 md:px-8">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Local source files</div>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">Load a workout and continue where you left off.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-muted-foreground">Your video remains local. Optional session and annotation JSON files restore timing, context, and previous labels.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="button-secondary gap-2" onClick={() => downloadJson(false)} disabled={!annotations.length}><Save className="h-4 w-4" /> Save JSON</button>
            <button type="button" className="button-secondary gap-2" onClick={() => downloadJson(true)} disabled={!annotations.length}><Download className="h-4 w-4" /> Export session</button>
            <button type="button" className="button-secondary gap-2" onClick={resetWorkspace}><RotateCcw className="h-4 w-4" /> Reset</button>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          <label className="grid gap-2"><FieldLabel>Custom video</FieldLabel><span className={`${inputStyle} flex cursor-pointer items-center gap-2`}><Upload className="h-4 w-4 text-primary" /><span className="truncate">{videoName || "Choose video"}</span><input className="sr-only" type="file" accept="video/*" onChange={(event) => handleVideoFile(event.target.files?.[0])} /></span></label>
          <label className="grid gap-2"><FieldLabel>Session or feature JSON</FieldLabel><span className={`${inputStyle} flex cursor-pointer items-center gap-2`}><FileJson2 className="h-4 w-4 text-primary" /><span>Choose optional session</span><input className="sr-only" type="file" accept=".json,application/json" onChange={(event) => event.target.files?.[0] && void readJsonFile(event.target.files[0], false)} /></span></label>
          <label className="grid gap-2"><FieldLabel>Existing annotations JSON</FieldLabel><span className={`${inputStyle} flex cursor-pointer items-center gap-2`}><FileJson2 className="h-4 w-4 text-primary" /><span>Choose optional annotations</span><input className="sr-only" type="file" accept=".json,application/json" onChange={(event) => event.target.files?.[0] && void readJsonFile(event.target.files[0], true)} /></span></label>
        </div>
        <div className="mt-4 rounded-2xl border border-black/10 bg-background/65 px-4 py-3 text-sm text-muted-foreground">{status}</div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        {metric("Frame", frameCount ? `${currentFrame} / ${Math.max(0, frameCount - 1)}` : "—")}
        {metric("Annotations", String(annotations.length).padStart(2, "0"))}
        {metric("FPS", fps.toFixed(3))}
        {metric("Save state", dirty ? "Unsaved" : "Saved locally")}
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(380px,.85fr)] xl:items-start">
        <div className="surface-card min-w-0 px-5 py-6 md:px-7">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Video and frame navigation</div><h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">Review each movement precisely.</h2></div>
            <span className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-accent-foreground">Frame {frameCount ? currentFrame : "—"}</span>
          </div>
          <div className="relative mt-5 grid min-h-72 place-items-center overflow-hidden rounded-[24px] bg-slate-950">
            <video ref={videoRef} className="max-h-[62vh] w-full bg-slate-950" playsInline preload="metadata" onLoadedMetadata={handleMetadata} onTimeUpdate={handleTimeUpdate} onPlay={() => setIsPlaying(true)} onPause={() => setIsPlaying(false)} />
            {!videoName ? <div className="absolute inset-0 grid place-content-center gap-2 px-6 text-center text-white/70"><Play className="mx-auto h-10 w-10 text-primary" /><strong className="text-white">Select a custom video to begin</strong><span className="text-sm">The video stays local to this browser.</span></div> : null}
          </div>

          <input className="mt-5 w-full accent-[hsl(var(--primary))]" type="range" min={0} max={Math.max(0, frameCount - 1)} value={Math.min(currentFrame, Math.max(0, frameCount - 1))} onChange={(event) => seekFrame(Number(event.target.value))} disabled={!frameCount} />
          <div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>{frameTime(currentFrame).toFixed(3)}s</span><span>{durationS ? `${durationS.toFixed(2)}s total` : "Duration —"}</span></div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" className="button-secondary !px-4 !py-2" onClick={() => seekFrame(currentFrame - 1)}><ChevronLeft className="h-4 w-4" /></button>
            <button type="button" className="button-primary gap-2 !px-5 !py-2" onClick={() => videoRef.current?.paused ? void videoRef.current.play() : videoRef.current?.pause()} disabled={!videoName}>{isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}{isPlaying ? "Pause" : "Play"}</button>
            <button type="button" className="button-secondary !px-4 !py-2" onClick={() => seekFrame(currentFrame + 1)}><ChevronRight className="h-4 w-4" /></button>
            <label className="ml-0 flex items-center gap-2 text-sm text-muted-foreground sm:ml-2">Jump<input className="w-20 rounded-xl border border-black/10 bg-background/70 px-3 py-2 text-foreground outline-none" type="number" min={1} value={jumpFrames} onChange={(event) => setJumpFrames(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">Speed<select className="rounded-xl border border-black/10 bg-background/70 px-3 py-2 text-foreground outline-none" value={playbackSpeed} onChange={(event) => setPlaybackSpeed(Math.max(0.1, Math.min(5, Number(event.target.value) || 1)))}><option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={3}>3×</option><option value={5}>5×</option></select></label>
            <button type="button" className="button-secondary !px-4 !py-2" onClick={() => seekFrame(currentFrame - jumpFrames)}>− Jump</button>
            <button type="button" className="button-secondary !px-4 !py-2" onClick={() => seekFrame(currentFrame + jumpFrames)}>+ Jump</button>
          </div>
          <p className="mt-4 text-xs leading-6 text-muted-foreground">Arrow keys step one frame. Up/Down step by the jump value. W starts a range, S saves it, and Space toggles playback.</p>

          <div className="mt-5 grid gap-3 rounded-[22px] border border-black/10 bg-background/65 px-4 py-4 sm:grid-cols-6">
            {Object.entries(currentContext).map(([key, value]) => <div key={key}><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{key.replace(/([A-Z])/g, " $1")}</div><div className="mt-1 truncate text-sm font-semibold text-foreground">{formatExercise(value)}</div></div>)}
          </div>
        </div>

        <div className="surface-card px-5 py-6 md:px-7 xl:sticky xl:top-28">
          <div className="flex items-start justify-between gap-3"><div><div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Annotation menu</div><h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">{selectedId ? `Editing ${selectedId}` : "Create a new annotation"}</h2></div><span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">{LAYER_LABELS[form.layer]}</span></div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">{LAYER_HINTS[form.layer]}</p>

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2"><FieldLabel>Layer</FieldLabel><select className={inputStyle} value={form.layer} onChange={(event) => setField("layer", event.target.value as Layer)}>{Object.entries(LAYER_LABELS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="grid gap-2"><FieldLabel>Boundary</FieldLabel><select className={inputStyle} value={form.boundary} onChange={(event) => setField("boundary", event.target.value as Boundary)}><option value="frame_interval">Frame interval</option><option value="single_frame">Single frame</option></select></label>
            <label className="grid gap-2"><FieldLabel>Activity</FieldLabel><select className={inputStyle} value={effectiveForm.activity} disabled={form.layer === "form"} onChange={(event) => setField("activity", event.target.value)}><option>N/A</option><option>active</option><option>idle</option><option>transition</option></select></label>
            <label className="grid gap-2"><FieldLabel>Movement type</FieldLabel><select className={inputStyle} value={effectiveForm.movementType} disabled={!formRules.movementType} onChange={(event) => { setField("movementType", event.target.value); setField("exercise", "N/A"); }}>{MOVEMENT_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="grid gap-2"><FieldLabel>Exercise name</FieldLabel><select className={inputStyle} value={effectiveForm.exercise} disabled={!formRules.exercise} onChange={(event) => setField("exercise", event.target.value)}>{(EXERCISES_BY_MOVEMENT[effectiveForm.movementType] || ["N/A"]).map((value) => <option key={value} value={value}>{formatExercise(value)}</option>)}</select></label>
            <label className="grid gap-2"><FieldLabel>Set number</FieldLabel><select className={inputStyle} value={effectiveForm.setNumber} disabled={!formRules.setNumber} onChange={(event) => setField("setNumber", event.target.value)}>{NUMBER_OPTIONS.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="grid gap-2"><FieldLabel>Rep number</FieldLabel><select className={inputStyle} value={effectiveForm.repNumber} disabled={!formRules.repNumber} onChange={(event) => setField("repNumber", event.target.value)}>{NUMBER_OPTIONS.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="grid gap-2"><FieldLabel>Phase</FieldLabel><select className={inputStyle} value={effectiveForm.phase} disabled={!formRules.phase} onChange={(event) => setField("phase", event.target.value)}><option>N/A</option><option>eccentric</option><option>concentric</option><option>hold</option></select></label>
            <label className="grid gap-2"><FieldLabel>Form state</FieldLabel><select className={inputStyle} value={form.formState} disabled={!formRules.formState} onChange={(event) => setField("formState", event.target.value)}><option>N/A</option><option>unlabeled</option><option>observed</option><option>absent</option><option>unknown</option></select></label>
            <MultiSelect label="Issue type" options={ISSUE_TYPES} value={form.issueTypes} disabled={!formRules.formDetails} onChange={(value) => setField("issueTypes", value)} />
            <MultiSelect label="Issue category" options={ISSUE_CATEGORIES} value={form.issueCategories} disabled={!formRules.formDetails} onChange={(value) => setField("issueCategories", value)} />
            <MultiSelect label="Affected joints" options={JOINTS} value={form.affectedJoints} disabled={!formRules.formDetails} onChange={(value) => setField("affectedJoints", value)} />
            <label className="grid gap-2 sm:col-span-2"><FieldLabel>Notes</FieldLabel><textarea className={`${inputStyle} min-h-24 resize-y`} value={form.notes} onChange={(event) => setField("notes", event.target.value)} placeholder="Evidence, context, or annotation notes" /></label>
          </div>

          <div className="mt-5 rounded-[22px] border border-black/10 bg-background/65 px-4 py-4">
            <div className="text-sm font-semibold text-foreground">Range</div>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{rangeStart == null ? "Press Start / reset, navigate, then Save range." : `${selectedId ? `Editing ${selectedId}. ` : ""}Start ${rangeStart}; current ${currentFrame}.`}</p>
            <div className="mt-4 flex flex-wrap gap-2"><button type="button" className="button-secondary !px-4 !py-2" onClick={() => { setRangeStart(currentFrame); setStatus(`Range start captured at frame ${currentFrame}.`); }}>Start / reset (W)</button><button type="button" className="button-primary !px-4 !py-2" onClick={saveRange}>Save range (S)</button><button type="button" className="button-secondary gap-2 !px-4 !py-2" onClick={() => { if (!selectedId) return setStatus("Select an annotation row first."); setAnnotations((current) => current.filter((item) => item.annotationId !== selectedId)); setStatus(`${selectedId} removed.`); setDirty(true); resetForm(); }}><Trash2 className="h-4 w-4" /> Clear selected</button></div>
          </div>
        </div>
      </section>

      <section className="surface-card px-5 py-6 md:px-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Temporal annotations</div><h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-foreground">Review and edit the timeline.</h2></div><div className="flex flex-wrap items-center gap-2"><label className="flex items-center gap-2 rounded-full border border-black/10 bg-background/70 px-3 py-2 text-sm text-muted-foreground"><Search className="h-4 w-4" /><input className="w-36 bg-transparent text-foreground outline-none placeholder:text-muted-foreground sm:w-52" value={timelineFilter} onChange={(event) => setTimelineFilter(event.target.value)} placeholder="Filter timeline" aria-label="Filter timeline" /></label><span className="text-sm text-muted-foreground">{visibleAnnotations.length} shown</span></div></div>
        <div className="mt-5 max-h-[55vh] overflow-auto rounded-[22px] border border-black/10">
          <table className="min-w-[1240px] w-full border-collapse text-left text-xs">
            <thead className="sticky top-0 z-10 bg-secondary text-muted-foreground"><tr>{["ID","Layer","Boundary","Frames","Activity","Movement","Exercise","Set","Rep","Phase","Issue type","Affected joints","Notes"].map((heading) => <th key={heading} className="border-b border-black/10 px-3 py-3 font-semibold uppercase tracking-[0.12em]">{heading}</th>)}</tr></thead>
            <tbody>{visibleAnnotations.length ? visibleAnnotations.map((annotation) => <tr key={annotation.annotationId} onClick={() => loadAnnotation(annotation)} className={`cursor-pointer transition-colors hover:bg-primary/5 ${selectedId === annotation.annotationId ? "bg-primary/10 shadow-[inset_3px_0_0_hsl(var(--primary))]" : ""}`}>{[
              annotation.annotationId, LAYER_LABELS[annotation.layer], annotation.boundary === "single_frame" ? "Single frame" : "Frame interval", `${annotation.startFrame}–${annotation.endFrameExclusive - 1}`, annotation.activity, annotation.movementType, formatExercise(annotation.exercise), annotation.setNumber, annotation.repNumber, annotation.phase, annotation.issueTypes.join(", "), annotation.affectedJoints.join(", "), annotation.notes,
            ].map((value,index) => <td key={`${annotation.annotationId}-${index}`} className="whitespace-nowrap border-b border-black/10 px-3 py-3 text-foreground/80">{value || ""}</td>)}</tr>) : <tr><td colSpan={13} className="px-5 py-10 text-center text-sm text-muted-foreground">{annotations.length ? "No annotations match this filter." : "No annotations yet. Load a video, mark a range, and save the first layer."}</td></tr>}</tbody>
          </table>
        </div>
      </section>

      <section className="rounded-[24px] border border-black/10 bg-background/65 px-5 py-5 text-sm leading-7 text-muted-foreground">
        <strong className="text-foreground">Data note.</strong> This browser workspace preserves the mobile annotation workflow without changing feature Parquet files. MediaPipe processing and canonical Parquet generation remain desktop/server tasks; exported annotations stay separate as the source of truth.
      </section>
    </div>
  );
}

function MultiSelect({ label, options, value, disabled, onChange }: { label: string; options: string[]; value: string[]; disabled: boolean; onChange: (value: string[]) => void }) {
  return (
    <label className="grid gap-2">
      <FieldLabel>{label}</FieldLabel>
      <select
        multiple
        size={3}
        className={`${inputClass} min-h-28`}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(normalizeSelection(Array.from(event.currentTarget.selectedOptions, (option) => option.value)))}
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      <span className="rounded-xl bg-accent/70 px-3 py-2 text-xs text-accent-foreground">{value.join(", ")}</span>
    </label>
  );
}
