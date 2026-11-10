const MOVEMENT_TYPES = ["N/A", "Carry", "Core", "Hinge", "Jump", "Lunge", "Locomotion", "Pull", "Push", "Rotate", "Squat"];
const EXERCISES_BY_MOVEMENT = {
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
  Squat: ["BodyweightSquat", "GobletSquat", "SumoSquat"]
};
const JOINTS = [
  "N/A", "Nose", "Left eye", "Right eye", "Left ear", "Right ear", "Mouth left", "Mouth right",
  "Left shoulder", "Right shoulder", "Left elbow", "Right elbow", "Left wrist", "Right wrist",
  "Left hip", "Right hip", "Left knee", "Right knee", "Left ankle", "Right ankle",
  "Left heel", "Right heel", "Left foot index", "Right foot index"
];
const ISSUE_TYPES = ["N/A", "Tracking quality", "Alignment", "Range of motion", "Tempo", "Stability", "Equipment", "Camera", "Other"];
const ISSUE_CATEGORIES = ["N/A", "Occlusion", "Low confidence", "Joint misalignment", "Excessive speed", "Insufficient range", "Compensation", "Setup", "Transition", "Other"];
const LAYER_ORDER = { activity: 0, set: 1, repetition: 2, phase: 3, form: 4, other: 5 };
const LAYER_LABELS = {
  activity: "Activity Interval",
  set: "Set Interval",
  repetition: "Repetition Interval",
  phase: "Phase Interval",
  form: "Form Interval",
  other: "Other Interval"
};
const LAYER_HINTS = {
  activity: "Broad movement activity; set values are inherited.",
  set: "Labels movement, exercise, and set number.",
  repetition: "Labels the repetition inside the selected set.",
  phase: "Labels eccentric, concentric, or hold.",
  form: "Labels observed form or tracking issues only.",
  other: "Setup, idle time, camera adjustment, or unrelated time."
};
const MOBILE_PREFERENCES_KEY = "aihumo:mobile:preferences:v1";
const MOBILE_WORKSPACES_KEY = "aihumo:mobile:workspaces:v1";
const DEFAULT_PREFERENCES = {
  jumpFrames: 50,
  playbackSpeed: 1,
  theme: "light",
  loopVideo: false,
  arrowKeysNavigate: true,
  autosave: true,
  frameColor: "#16a765",
  annotationColor: "#136fdb"
};

const state = {
  videoUrl: null,
  videoName: "",
  fps: 30,
  frameCount: 0,
  durationS: 0,
  frameRows: [],
  annotations: [],
  selectedAnnotationId: null,
  rangeStart: null,
  sessionMetadata: {},
  installPrompt: null,
  dirty: false,
  thumbnailVideo: null,
  thumbnailRenderToken: 0,
  frameRowsByFrame: new Map(),
  preferences: loadPreferences(),
  workspaceKey: "",
  resumeRecords: [],
  pendingResume: null,
  filterText: "",
  autosaveTimer: null
};

const $ = (id) => document.getElementById(id);
const video = $("video");

function loadPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(MOBILE_PREFERENCES_KEY) || "{}");
    return { ...DEFAULT_PREFERENCES, ...stored };
  } catch (_) {
    return { ...DEFAULT_PREFERENCES };
  }
}

function savePreferences() {
  try { localStorage.setItem(MOBILE_PREFERENCES_KEY, JSON.stringify(state.preferences)); } catch (_) {}
}

function clampSpeed(value) {
  return Math.max(0.1, Math.min(5, Number(value) || 1));
}

function applyPreferences() {
  const preferences = state.preferences;
  document.body.dataset.theme = preferences.theme || "light";
  document.documentElement.style.setProperty("--frame-accent", preferences.frameColor || DEFAULT_PREFERENCES.frameColor);
  document.documentElement.style.setProperty("--annotation-accent", preferences.annotationColor || DEFAULT_PREFERENCES.annotationColor);
  $("jumpFramesInput").value = String(Math.max(1, Math.floor(Number(preferences.jumpFrames) || DEFAULT_PREFERENCES.jumpFrames)));
  $("playbackSpeedSelect").value = String(clampSpeed(preferences.playbackSpeed));
  video.playbackRate = clampSpeed(preferences.playbackSpeed);
}

function openSettings() {
  $("settingsJumpInput").value = String(state.preferences.jumpFrames);
  $("settingsSpeedSelect").value = String(clampSpeed(state.preferences.playbackSpeed));
  $("settingsThemeSelect").value = state.preferences.theme;
  $("settingsLoopInput").checked = Boolean(state.preferences.loopVideo);
  $("settingsArrowInput").checked = Boolean(state.preferences.arrowKeysNavigate);
  $("settingsAutosaveInput").checked = Boolean(state.preferences.autosave);
  $("settingsFrameColorInput").value = state.preferences.frameColor;
  $("settingsAnnotationColorInput").value = state.preferences.annotationColor;
  $("settingsDialog").showModal();
}

function saveSettingsFromDialog(event) {
  event.preventDefault();
  state.preferences = {
    ...state.preferences,
    jumpFrames: Math.max(1, Math.min(5000, Math.floor(Number($("settingsJumpInput").value) || DEFAULT_PREFERENCES.jumpFrames))),
    playbackSpeed: clampSpeed($("settingsSpeedSelect").value),
    theme: $("settingsThemeSelect").value,
    loopVideo: $("settingsLoopInput").checked,
    arrowKeysNavigate: $("settingsArrowInput").checked,
    autosave: $("settingsAutosaveInput").checked,
    frameColor: $("settingsFrameColorInput").value || DEFAULT_PREFERENCES.frameColor,
    annotationColor: $("settingsAnnotationColorInput").value || DEFAULT_PREFERENCES.annotationColor
  };
  savePreferences();
  applyPreferences();
  $("settingsDialog").close();
  toast("Mobile settings saved.");
}

function resetSettings() {
  state.preferences = { ...DEFAULT_PREFERENCES };
  savePreferences();
  applyPreferences();
  openSettings();
  toast("Mobile settings reset.");
}

function togglePlayback() {
  if (video.paused) {
    video.playbackRate = clampSpeed(state.preferences.playbackSpeed);
    video.play().catch(() => toast("Playback could not start. Tap the video once, then try again."));
  } else {
    video.pause();
  }
}

function init() {
  applyPreferences();
  populateSelect($("movementTypeSelect"), MOVEMENT_TYPES);
  populateSelect($("exerciseSelect"), ["N/A"]);
  populateNumberSelect($("setSelect"));
  populateNumberSelect($("repSelect"));
  populateSelect($("issueTypeSelect"), ISSUE_TYPES);
  populateSelect($("issueCategorySelect"), ISSUE_CATEGORIES);
  populateSelect($("affectedJointsSelect"), JOINTS);
  bindEvents();
  resetEditor();
  updateTransport();
  renderAnnotations();
  renderResumeHistory();
  updateContextSummary();
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  }
}

function bindEvents() {
  $("videoInput").addEventListener("change", handleVideoInput);
  $("sessionInput").addEventListener("change", handleSessionInput);
  $("annotationInput").addEventListener("change", handleAnnotationInput);
  $("movementTypeSelect").addEventListener("change", () => {
    populateSelect($("exerciseSelect"), EXERCISES_BY_MOVEMENT[$("movementTypeSelect").value] || ["N/A"]);
    markDirty();
  });
  $("jumpFramesInput").addEventListener("change", () => { state.preferences.jumpFrames = getJump(); savePreferences(); });
  $("playbackSpeedSelect").addEventListener("change", () => { video.playbackRate = clampSpeed($("playbackSpeedSelect").value); state.preferences.playbackSpeed = video.playbackRate; savePreferences(); });
  ["layerSelect", "boundarySelect", "activitySelect", "exerciseSelect", "setSelect", "repSelect", "phaseSelect", "formStateSelect", "notesInput"]
    .forEach((id) => $(id).addEventListener("change", () => { applyLayerRules(); markDirty(); }));
  ["issueTypeSelect", "issueCategorySelect", "affectedJointsSelect"].forEach((id) => {
    $(id).addEventListener("change", () => { updateMultiSummaries(); markDirty(); });
  });
  $("previousFrameButton").addEventListener("click", () => stepFrames(-1));
  $("nextFrameButton").addEventListener("click", () => stepFrames(1));
  $("backJumpButton").addEventListener("click", () => stepFrames(-getJump()));
  $("forwardJumpButton").addEventListener("click", () => stepFrames(getJump()));
  $("playButton").addEventListener("click", togglePlayback);
  $("frameInput").addEventListener("change", () => seekFrame(Number($("frameInput").value)));
  $("timeInput").addEventListener("change", () => seekTime(Number($("timeInput").value)));
  $("startRangeButton").addEventListener("click", startRange);
  $("saveRangeButton").addEventListener("click", saveRange);
  $("clearButton").addEventListener("click", clearSelectedAnnotation);
  $("saveJsonButton").addEventListener("click", () => downloadJson(false));
  $("downloadSessionButton").addEventListener("click", () => downloadJson(true));
  $("resetWorkspaceButton").addEventListener("click", resetWorkspace);
  $("settingsButton").addEventListener("click", openSettings);
  $("settingsForm").addEventListener("submit", saveSettingsFromDialog);
  $("resetSettingsButton").addEventListener("click", resetSettings);
  $("annotationFilterInput").addEventListener("input", (event) => { state.filterText = event.target.value.trim().toLowerCase(); renderAnnotations(); });
  $("resumeNavButton").addEventListener("click", () => {
    if ($("resumeCard").classList.contains("hidden")) $("resumeCard").classList.remove("hidden");
    $("resumeCard").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("clearResumeButton").addEventListener("click", () => {
    state.resumeRecords = [];
    writeResumeRecords([]);
    renderResumeHistory();
    toast("Resume history cleared from this device.");
  });
  document.querySelectorAll("[data-scroll-target]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".mobile-nav-button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  video.addEventListener("loadedmetadata", handleVideoMetadata);
  video.addEventListener("timeupdate", updateTransport);
  video.addEventListener("seeked", updateTransport);
  video.addEventListener("play", updateTransport);
  video.addEventListener("pause", updateTransport);
  video.addEventListener("ended", () => {
    if (state.preferences.loopVideo) { video.currentTime = 0; void togglePlayback(); }
  });
  window.addEventListener("keydown", handleKeyboard);
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.installPrompt = event;
    $("installButton").classList.remove("hidden");
  });
  $("installButton").addEventListener("click", async () => {
    if (!state.installPrompt) return;
    state.installPrompt.prompt();
    await state.installPrompt.userChoice;
    state.installPrompt = null;
    $("installButton").classList.add("hidden");
  });
}

function populateSelect(select, values) {
  const current = select.value;
  select.replaceChildren(...values.map((value) => new Option(value, value)));
  if (values.includes(current)) select.value = current;
}

function populateNumberSelect(select) {
  const values = ["N/A", ...Array.from({ length: 30 }, (_, index) => String(index + 1))];
  populateSelect(select, values);
}

function handleVideoInput(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = URL.createObjectURL(file);
  state.videoName = file.name;
  state.workspaceKey = workspaceKeyFor(file.name, state.sessionMetadata);
  state.pendingResume = findResumeRecord(state.workspaceKey);
  video.src = state.videoUrl;
  video.load();
  if (state.thumbnailVideo) state.thumbnailVideo.removeAttribute("src");
  state.thumbnailVideo = document.createElement("video");
  state.thumbnailVideo.muted = true;
  state.thumbnailVideo.preload = "metadata";
  state.thumbnailVideo.src = state.videoUrl;
  state.thumbnailVideo.load();
  $("videoPlaceholder").classList.add("hidden");
  $("importStatus").textContent = state.pendingResume
    ? `${file.name} loaded locally. A saved mobile workspace is available below.`
    : `${file.name} loaded locally. Add a session JSON if you want to continue existing annotations.`;
  if (state.pendingResume) showResumeCard();
  state.dirty = true;
  updateSaveState();
}

async function handleSessionInput(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    applySessionData(data, file.name);
    toast(`Loaded ${file.name}`);
  } catch (error) {
    toast(`Could not read session JSON: ${error.message}`);
  }
}

async function handleAnnotationInput(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const annotations = normalizeAnnotations(data.annotations || data);
    state.annotations = annotations;
    state.selectedAnnotationId = null;
    resetEditor();
    renderAnnotations();
    updateContextSummary();
    markDirty();
    toast(`Loaded ${annotations.length} annotations`);
  } catch (error) {
    toast(`Could not read annotation JSON: ${error.message}`);
  }
}

function applySessionData(data, sourceName) {
  const metadata = data.recording || data.metadata || data.session || {};
  state.sessionMetadata = metadata;
  const timing = data.frameTiming || data.timing || {};
  state.fps = Number(timing.effectiveFps || timing.sourceFps || metadata.effectiveFps || metadata.sourceFps || data.fps || state.fps) || 30;
  const rows = data.frames || data.frameFeatures || data.featureRows || [];
  if (Array.isArray(rows)) setFrameRows(rows);
  state.annotations = normalizeAnnotations(data.annotations || []);
  state.selectedAnnotationId = null;
  resetEditor();
  renderAnnotations();
  updateTransport();
  $("importStatus").textContent = `Loaded ${sourceName}. ${state.annotations.length} annotations and ${state.frameRows.length || "no explicit"} frame timing rows available.`;
  state.workspaceKey = workspaceKeyFor(state.videoName || sourceName, state.sessionMetadata);
  state.pendingResume = findResumeRecord(state.workspaceKey);
  if (state.pendingResume) showResumeCard();
  markDirty();
}

function setFrameRows(rows) {
  state.frameRows = rows
    .filter((row) => row && Number.isFinite(Number(row.frameIndex ?? row.frame_id ?? row.sourceFrameIndex ?? 0)))
    .sort((left, right) => toFrame(left.frameIndex ?? left.frame_id ?? left.sourceFrameIndex) - toFrame(right.frameIndex ?? right.frame_id ?? right.sourceFrameIndex));
  state.frameRowsByFrame = new Map(state.frameRows.map((row) => [toFrame(row.frameIndex ?? row.frame_id ?? row.sourceFrameIndex), row]));
}

function workspaceKeyFor(name, metadata = {}) {
  const identity = [metadata.participantId || metadata.participant_id || "", metadata.sessionId || metadata.session_id || "", metadata.recordingId || metadata.recording_id || "", name || ""];
  return identity.join("|").toLowerCase();
}

function readResumeRecords() {
  try { return JSON.parse(localStorage.getItem(MOBILE_WORKSPACES_KEY) || "[]"); } catch (_) { return []; }
}

function writeResumeRecords(records) {
  try { localStorage.setItem(MOBILE_WORKSPACES_KEY, JSON.stringify(records.slice(0, 12))); } catch (_) {}
}

function findResumeRecord(key) {
  if (!key) return null;
  return state.resumeRecords.find((record) => record.workspaceKey === key) || null;
}

function showResumeCard() {
  $("resumeCard").classList.remove("hidden");
  renderResumeHistory();
}

function renderResumeHistory() {
  state.resumeRecords = readResumeRecords();
  const list = $("resumeList");
  if (!list) return;
  list.replaceChildren();
  if (!state.resumeRecords.length) {
    $("resumeCard").classList.add("hidden");
    return;
  }
  $("resumeCard").classList.remove("hidden");
  for (const record of state.resumeRecords) {
    const item = document.createElement("div");
    item.className = "resume-item";
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = record.videoName || "Unnamed mobile workspace";
    const meta = document.createElement("small");
    meta.textContent = `${record.annotations?.length || 0} annotations · frame ${record.currentFrame ?? 0} · ${new Date(record.updatedAt).toLocaleString()}`;
    details.append(title, meta);
    const button = document.createElement("button");
    button.className = "secondary-button";
    button.type = "button";
    button.textContent = "Resume after choosing video";
    button.addEventListener("click", () => restoreResumeRecord(record));
    item.append(details, button);
    list.appendChild(item);
  }
}

function restoreResumeRecord(record) {
  state.pendingResume = record;
  if (state.videoName && workspaceKeyFor(state.videoName, state.sessionMetadata) === record.workspaceKey) {
    state.annotations = normalizeAnnotations(record.annotations || []);
    setFrameRows(record.frameRows || []);
    if (record.currentFrame != null) seekFrame(record.currentFrame);
    renderAnnotations();
    updateContext();
    updateContextSummary();
    toast(`Resumed ${record.videoName}`);
  } else {
    toast(`Choose ${record.videoName || "the saved video"} to restore this workspace.`);
  }
}

function saveLocalWorkspace() {
  if (!state.videoName || !state.preferences.autosave) return;
  const record = {
    workspaceKey: state.workspaceKey || workspaceKeyFor(state.videoName, state.sessionMetadata),
    videoName: state.videoName,
    sessionMetadata: state.sessionMetadata,
    annotations: state.annotations,
    // Resume state keeps timing only; it must not duplicate a canonical feature dataset.
    frameRows: state.frameRows.map((row) => ({
      frameIndex: row.frameIndex ?? row.frame_id ?? row.sourceFrameIndex,
      sourceFrameIndex: row.sourceFrameIndex,
      timeElapsedS: row.timeElapsedS ?? row.timestampS ?? row.timestamp_s ?? row.time_s,
      deltaTimeS: row.deltaTimeS ?? row.delta_time_s,
      timestampSource: row.timestampSource ?? row.timestamp_source
    })),
    currentFrame: currentFrame(),
    updatedAt: new Date().toISOString()
  };
  const records = [record, ...state.resumeRecords.filter((item) => item.workspaceKey !== record.workspaceKey)];
  state.resumeRecords = records.slice(0, 12);
  writeResumeRecords(state.resumeRecords);
  renderResumeHistory();
}

function normalizeAnnotations(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const start = toFrame(item.startFrame ?? item.start_frame ?? item.start ?? 0);
    const endRaw = item.endFrameExclusive ?? item.end_frame_exclusive ?? item.endFrame ?? item.end_frame ?? start + 1;
    const end = Math.max(start + 1, toFrame(endRaw));
    return {
      annotationId: item.annotationId || item.annotation_id || `A${String(index + 1).padStart(5, "0")}`,
      layer: normalizeLayer(item.layer || item.annotationType || item.annotation_type),
      boundary: item.boundary || (end - start === 1 ? "single_frame" : "frame_interval"),
      activity: item.activity || item.activityState || item.activity_state || "N/A",
      movementType: item.movementType || item.movement_type || "N/A",
      exercise: item.exercise || item.exerciseName || item.exercise_name || "N/A",
      setNumber: normalizeNA(item.setNumber ?? item.set_id ?? item.set),
      repNumber: normalizeNA(item.repNumber ?? item.rep_id ?? item.rep),
      phase: item.phase || "N/A",
      formState: item.formState || item.form || "N/A",
      issueTypes: normalizeMulti(item.issueTypes || item.issue_type),
      issueCategories: normalizeMulti(item.issueCategories || item.issue_category),
      affectedJoints: normalizeMulti(item.affectedJoints || item.affected_joints),
      notes: item.notes || "",
      startFrame: start,
      endFrameExclusive: end,
      startTimeS: Number(item.startTimeS ?? item.start_time_s ?? 0),
      endTimeS: Number(item.endTimeS ?? item.end_time_s ?? 0),
      provenance: item.provenance || "mobile-import",
      annotationVersion: item.annotationVersion || "mobile.v1"
    };
  });
}

function normalizeLayer(value) {
  const normalized = String(value || "other").toLowerCase().replace(/[\s/]+/g, "_");
  if (normalized.includes("activity")) return "activity";
  if (normalized.includes("set")) return "set";
  if (normalized.includes("repetition") || normalized === "rep") return "repetition";
  if (normalized.includes("phase")) return "phase";
  if (normalized.includes("form") || normalized.includes("error")) return "form";
  return "other";
}

function normalizeMulti(value) {
  if (Array.isArray(value)) return value.length ? value : ["N/A"];
  if (value == null || value === "") return ["N/A"];
  return String(value).split(",").map((item) => item.trim()).filter(Boolean);
}

function normalizeNA(value) {
  return value == null || value === "" || value === -1 || value === "-1" ? "N/A" : String(value);
}

function toFrame(value) {
  const frame = Number(value);
  return Number.isFinite(frame) && frame >= 0 ? Math.floor(frame) : 0;
}

function handleVideoMetadata() {
  state.durationS = Number(video.duration) || 0;
  if (!state.frameRows.length) state.frameCount = Math.max(0, Math.ceil(state.durationS * state.fps));
  else state.frameCount = Math.max(...state.frameRows.map((row) => toFrame(row.frameIndex ?? row.frame_id ?? row.sourceFrameIndex)), 0);
  renderThumbnails();
  updateTransport();
}

function currentFrame() {
  const time = Number(video.currentTime) || 0;
  if (state.frameRows.length) {
    let low = 0;
    let high = state.frameRows.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (rowTime(state.frameRows[middle]) < time) low = middle + 1;
      else high = middle;
    }
    const before = state.frameRows[Math.max(0, low - 1)];
    const after = state.frameRows[low];
    const nearest = before && Math.abs(rowTime(before) - time) <= Math.abs(rowTime(after) - time) ? before : after;
    return toFrame(nearest.frameIndex ?? nearest.frame_id ?? 0);
  }
  return Math.max(0, Math.round(time * state.fps));
}

function frameTime(frame) {
  const row = state.frameRowsByFrame.get(toFrame(frame));
  if (row) return rowTime(row);
  return frame / state.fps;
}

function rowTime(row) {
  return Number(row?.timeElapsedS ?? row?.timestampS ?? row?.timestamp_s ?? row?.time_s ?? 0) || 0;
}

function seekFrame(frame) {
  if (!Number.isFinite(frame)) return;
  const maxFrame = Math.max(0, state.frameCount || Math.floor((state.durationS || 0) * state.fps));
  const bounded = Math.max(0, Math.min(Math.floor(frame), maxFrame));
  if (video.readyState >= 1) video.currentTime = Math.min(frameTime(bounded), Math.max(0, video.duration || frameTime(bounded)));
  updateTransport();
}

function seekTime(time) {
  const bounded = Math.max(0, Math.min(Number(time) || 0, video.duration || Number(time) || 0));
  if (video.readyState >= 1) video.currentTime = bounded;
  updateTransport();
}

function stepFrames(amount) { seekFrame(currentFrame() + amount); }
function getJump() { return Math.max(1, Math.floor(Number($("jumpFramesInput").value) || 15)); }

function updateTransport() {
  const frame = currentFrame();
  const time = Number(video.currentTime) || 0;
  $("frameInput").value = frame;
  $("timeInput").value = time.toFixed(3);
  $("frameBadge").textContent = `Frame ${frame}${state.frameCount ? ` / ${state.frameCount}` : ""}`;
  $("videoMeta").textContent = `FPS ${state.fps.toFixed(3)} · Duration ${state.durationS ? state.durationS.toFixed(2) : "—"} s · Frames ${state.frameCount || "—"}`;
  $("playButton").textContent = video.paused ? "Play" : "Pause";
  updateContext();
  updateContextSummary();
  updateRangeStatus();
  updateThumbnailSelection(frame);
}

function handleKeyboard(event) {
  const tag = event.target?.tagName?.toLowerCase();
  const textEditing = tag === "input" || tag === "textarea" || tag === "select" || event.target?.isContentEditable;
  if (textEditing && !state.preferences.arrowKeysNavigate) return;
  if (textEditing && !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  if (event.key === "ArrowLeft") { event.preventDefault(); stepFrames(-1); }
  if (event.key === "ArrowRight") { event.preventDefault(); stepFrames(1); }
  if (event.key === "ArrowUp") { event.preventDefault(); stepFrames(-getJump()); }
  if (event.key === "ArrowDown") { event.preventDefault(); stepFrames(getJump()); }
  if (event.key.toLowerCase() === "w") { event.preventDefault(); startRange(); }
  if (event.key.toLowerCase() === "s") { event.preventDefault(); saveRange(); }
  if (event.key === " ") { event.preventDefault(); void togglePlayback(); }
}

function startRange() {
  state.rangeStart = currentFrame();
  updateRangeStatus();
  toast(`Range start captured at frame ${state.rangeStart}`);
}

function saveRange() {
  if (!state.videoName && !state.durationS) {
    toast("Load a custom video before saving an annotation.");
    return;
  }
  const start = state.rangeStart == null ? currentFrame() : state.rangeStart;
  const boundary = $("boundarySelect").value;
  const end = boundary === "single_frame" ? start + 1 : Math.max(start + 1, currentFrame() + 1);
  const form = readEditorForm();
  const existing = state.selectedAnnotationId ? state.annotations.find((item) => item.annotationId === state.selectedAnnotationId) : null;
  const annotation = {
    ...(existing || { annotationId: nextAnnotationId(), provenance: "mobile-created", annotationVersion: "mobile.v1" }),
    ...form,
    startFrame: Math.min(start, end - 1),
    endFrameExclusive: end,
    startTimeS: frameTime(Math.min(start, end - 1)),
    endTimeS: frameTime(Math.max(start, end - 1)),
    updatedAt: new Date().toISOString()
  };
  if (existing) {
    Object.assign(existing, annotation);
    toast(`Updated ${existing.annotationId}`);
  } else {
    state.annotations.push(annotation);
    state.selectedAnnotationId = annotation.annotationId;
    toast(`Saved ${annotation.annotationId}`);
  }
  state.rangeStart = annotation.startFrame;
  state.dirty = true;
  renderAnnotations();
  updateContext();
  updateContextSummary();
  updateRangeStatus();
  saveLocalWorkspace();
  updateSaveState();
}

function readEditorForm() {
  const multi = (id) => selectedValues($(id));
  return {
    layer: $("layerSelect").value,
    boundary: $("boundarySelect").value,
    activity: $("activitySelect").value,
    movementType: $("movementTypeSelect").value || "N/A",
    exercise: $("exerciseSelect").value || "N/A",
    setNumber: $("setSelect").value || "N/A",
    repNumber: $("repSelect").value || "N/A",
    phase: $("phaseSelect").value || "N/A",
    formState: $("formStateSelect").value || "N/A",
    issueTypes: multi("issueTypeSelect"),
    issueCategories: multi("issueCategorySelect"),
    affectedJoints: multi("affectedJointsSelect"),
    notes: $("notesInput").value.trim()
  };
}

function selectedValues(select) {
  let values = Array.from(select.selectedOptions).map((option) => option.value);
  if (values.length > 1 && values.includes("N/A")) {
    values = values.filter((value) => value !== "N/A");
    Array.from(select.options).forEach((option) => { if (option.value === "N/A") option.selected = false; });
  }
  if (!values.length) {
    const na = Array.from(select.options).find((option) => option.value === "N/A");
    if (na) na.selected = true;
    return ["N/A"];
  }
  return values;
}

function selectValues(select, values) {
  const normalized = new Set(normalizeMulti(values));
  Array.from(select.options).forEach((option) => { option.selected = normalized.has(option.value); });
}

function loadAnnotationIntoEditor(annotation) {
  state.selectedAnnotationId = annotation.annotationId;
  $("layerSelect").value = annotation.layer;
  $("boundarySelect").value = annotation.boundary;
  $("activitySelect").value = annotation.activity || "N/A";
  populateSelect($("movementTypeSelect"), MOVEMENT_TYPES);
  $("movementTypeSelect").value = MOVEMENT_TYPES.includes(annotation.movementType) ? annotation.movementType : "N/A";
  populateSelect($("exerciseSelect"), EXERCISES_BY_MOVEMENT[$("movementTypeSelect").value] || ["N/A"]);
  $("exerciseSelect").value = Array.from($("exerciseSelect").options).some((option) => option.value === annotation.exercise) ? annotation.exercise : "N/A";
  $("setSelect").value = optionOrNA($("setSelect"), annotation.setNumber);
  $("repSelect").value = optionOrNA($("repSelect"), annotation.repNumber);
  $("phaseSelect").value = optionOrNA($("phaseSelect"), annotation.phase);
  $("formStateSelect").value = optionOrNA($("formStateSelect"), annotation.formState);
  selectValues($("issueTypeSelect"), annotation.issueTypes);
  selectValues($("issueCategorySelect"), annotation.issueCategories);
  selectValues($("affectedJointsSelect"), annotation.affectedJoints);
  $("notesInput").value = annotation.notes || "";
  state.rangeStart = annotation.startFrame;
  seekFrame(annotation.startFrame);
  $("editModeLabel").textContent = `Editing ${annotation.annotationId}`;
  applyLayerRules();
  updateMultiSummaries();
  updateRangeStatus();
}

function optionOrNA(select, value) {
  const normalized = normalizeNA(value);
  return Array.from(select.options).some((option) => option.value === normalized) ? normalized : "N/A";
}

function resetEditor() {
  state.selectedAnnotationId = null;
  state.rangeStart = null;
  $("layerSelect").value = "activity";
  $("boundarySelect").value = "frame_interval";
  $("activitySelect").value = "N/A";
  $("movementTypeSelect").value = "N/A";
  populateSelect($("exerciseSelect"), ["N/A"]);
  $("setSelect").value = "N/A";
  $("repSelect").value = "N/A";
  $("phaseSelect").value = "N/A";
  $("formStateSelect").value = "N/A";
  selectValues($("issueTypeSelect"), ["N/A"]);
  selectValues($("issueCategorySelect"), ["N/A"]);
  selectValues($("affectedJointsSelect"), ["N/A"]);
  $("notesInput").value = "";
  $("editModeLabel").textContent = "Creating a new annotation";
  applyLayerRules();
  updateMultiSummaries();
  updateRangeStatus();
}

function contextForFrame(frame) {
  const candidates = state.annotations
    .filter((annotation) => annotation.startFrame <= frame && frame < annotation.endFrameExclusive)
    .sort((a, b) => (LAYER_ORDER[a.layer] - LAYER_ORDER[b.layer]) || (a.startFrame - b.startFrame));
  const context = { activity: "N/A", movementType: "N/A", exercise: "N/A", setNumber: "N/A", repNumber: "N/A", phase: "N/A" };
  for (const item of candidates) {
    for (const key of Object.keys(context)) {
      if (item[key] && item[key] !== "N/A") context[key] = item[key];
    }
  }
  return context;
}

function updateContext() {
  const frame = currentFrame();
  const context = contextForFrame(frame);
  const selected = state.selectedAnnotationId ? state.annotations.find((item) => item.annotationId === state.selectedAnnotationId) : null;
  const effective = selected || context;
  $("layerHint").textContent = selected ? `Editing ${LAYER_LABELS[selected.layer]}` : LAYER_HINTS[$("layerSelect").value];
  const disabledFields = ["movementTypeSelect", "exerciseSelect", "setSelect", "repSelect", "phaseSelect"];
  for (const id of disabledFields) {
    const key = ({ movementTypeSelect: "movementType", exerciseSelect: "exercise", setSelect: "setNumber", repSelect: "repNumber", phaseSelect: "phase" })[id];
    if ($(id).disabled && effective[key] != null) {
      if (id === "exerciseSelect") {
        const movement = $("movementTypeSelect").value;
        populateSelect($(id), EXERCISES_BY_MOVEMENT[movement] || ["N/A"]);
      }
      $(id).value = optionOrNA($(id), effective[key]);
    }
  }
  if ($("activitySelect").disabled) $("activitySelect").value = effective.activity || "N/A";
}

function updateContextSummary() {
  if (!$('annotationCount')) return;
  const frame = currentFrame();
  const active = state.annotations.filter((annotation) => annotation.startFrame <= frame && frame < annotation.endFrameExclusive);
  const context = contextForFrame(frame);
  $('annotationCount').textContent = String(state.annotations.length);
  $('activeLayerCount').textContent = String(active.length);
  $('contextExercise').textContent = context.exercise || 'N/A';
  $('contextSet').textContent = context.setNumber || 'N/A';
  $('contextRep').textContent = context.repNumber || 'N/A';
  $('contextSummary').textContent = active.length
    ? `Frame ${frame}: ${active.map((item) => LAYER_LABELS[item.layer] || item.layer).join(' · ')}`
    : `Frame ${frame}: no saved annotation currently covers this frame.`;
}

function applyLayerRules() {
  const layer = $("layerSelect").value;
  const selected = state.selectedAnnotationId ? state.annotations.find((item) => item.annotationId === state.selectedAnnotationId) : null;
  const context = contextForFrame(currentFrame());
  const effective = selected || context;
  const enabled = {
    activitySelect: true,
    movementTypeSelect: layer === "set",
    exerciseSelect: layer === "set",
    setSelect: layer === "set",
    repSelect: layer === "repetition",
    phaseSelect: layer === "phase",
    formStateSelect: layer === "form",
    issueTypeSelect: layer === "form",
    issueCategorySelect: layer === "form",
    affectedJointsSelect: layer === "form",
    notesInput: true
  };
  Object.entries(enabled).forEach(([id, isEnabled]) => { $(id).disabled = !isEnabled; });
  $("activitySelect").disabled = layer === "form" ? true : false;
  if (layer === "form" || layer === "other") {
    $("activitySelect").disabled = layer === "form";
  }
  if (!selected) {
    if (layer !== "set") {
      $("movementTypeSelect").value = optionOrNA($("movementTypeSelect"), effective.movementType);
      populateSelect($("exerciseSelect"), EXERCISES_BY_MOVEMENT[$("movementTypeSelect").value] || ["N/A"]);
      $("exerciseSelect").value = optionOrNA($("exerciseSelect"), effective.exercise);
    }
    if (layer !== "set") $("setSelect").value = optionOrNA($("setSelect"), effective.setNumber);
    if (layer !== "repetition") $("repSelect").value = optionOrNA($("repSelect"), effective.repNumber);
    if (layer !== "phase") $("phaseSelect").value = optionOrNA($("phaseSelect"), effective.phase);
    if (layer === "form" || layer === "other") $("activitySelect").value = effective.activity || "N/A";
  }
  $("layerHint").textContent = LAYER_HINTS[layer];
}

function updateMultiSummaries() {
  const summary = (id, outputId) => {
    const values = selectedValues($(id));
    $(outputId).textContent = values.join(", ");
  };
  summary("issueTypeSelect", "issueTypeSummary");
  summary("issueCategorySelect", "issueCategorySummary");
  summary("affectedJointsSelect", "affectedJointsSummary");
}

function updateRangeStatus() {
  const frame = currentFrame();
  if (state.rangeStart == null) {
    $("rangeStatus").textContent = "Press Start / reset, navigate, then Save range.";
  } else {
    const selectedText = state.selectedAnnotationId ? `Editing ${state.selectedAnnotationId}. ` : "";
    $("rangeStatus").textContent = `${selectedText}Start ${state.rangeStart}; current ${frame}. Press S to save/update.`;
  }
}

function renderAnnotations() {
  const body = $("annotationsBody");
  body.replaceChildren();
  const sorted = [...state.annotations]
    .sort((a, b) => (a.startFrame - b.startFrame) || (LAYER_ORDER[a.layer] - LAYER_ORDER[b.layer]) || (a.endFrameExclusive - b.endFrameExclusive))
    .filter((annotation) => {
      if (!state.filterText) return true;
      const searchable = [annotation.annotationId, LAYER_LABELS[annotation.layer], annotation.boundary, annotation.activity, annotation.movementType, annotation.exercise, annotation.setNumber, annotation.repNumber, annotation.phase, ...annotation.issueTypes, ...annotation.issueCategories, ...annotation.affectedJoints, annotation.notes].join(" ").toLowerCase();
      return searchable.includes(state.filterText);
    });
  if (!sorted.length) {
    body.innerHTML = `<tr><td colspan="13" class="empty-row">${state.annotations.length ? "No annotations match this filter." : "No annotations yet."}</td></tr>`;
    return;
  }
  for (const annotation of sorted) {
    const row = document.createElement("tr");
    if (annotation.annotationId === state.selectedAnnotationId) row.classList.add("selected");
    const cells = [
      annotation.annotationId,
      LAYER_LABELS[annotation.layer] || annotation.layer,
      annotation.boundary === "single_frame" ? "Single frame" : "Frame interval",
      `${annotation.startFrame}–${annotation.endFrameExclusive - 1}`,
      annotation.activity,
      annotation.movementType,
      annotation.exercise,
      annotation.setNumber,
      annotation.repNumber,
      annotation.phase,
      annotation.issueTypes.join(", "),
      annotation.affectedJoints.join(", "),
      annotation.notes
    ];
    cells.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value || ""; row.appendChild(cell); });
    row.addEventListener("click", () => { loadAnnotationIntoEditor(annotation); renderAnnotations(); });
    body.appendChild(row);
  }
}

function clearSelectedAnnotation() {
  if (!state.selectedAnnotationId) {
    toast("Select a temporal annotation row first.");
    return;
  }
  const id = state.selectedAnnotationId;
  state.annotations = state.annotations.filter((annotation) => annotation.annotationId !== id);
  resetEditor();
  renderAnnotations();
  updateContextSummary();
  saveLocalWorkspace();
  markDirty();
  toast(`${id} cleared from temporal annotations.`);
}

function nextAnnotationId() {
  const used = new Set(state.annotations.map((item) => item.annotationId));
  let index = state.annotations.length + 1;
  while (used.has(`A${String(index).padStart(5, "0")}`)) index += 1;
  return `A${String(index).padStart(5, "0")}`;
}

function exportPayload(includeFrames) {
  const sorted = [...state.annotations].sort((a, b) => (a.startFrame - b.startFrame) || (LAYER_ORDER[a.layer] - LAYER_ORDER[b.layer]));
  const payload = {
    schemaVersion: "aihumo.mobile.annotation.v1",
    generatedAt: new Date().toISOString(),
    source: "AIHuMo Mobile Annotation Studio",
    recording: { ...state.sessionMetadata, videoName: state.videoName, durationS: state.durationS, fps: state.fps },
    annotations: sorted
  };
  if (includeFrames && state.frameRows.length) payload.frames = state.frameRows;
  return payload;
}

function downloadJson(includeFrames) {
  const name = (state.videoName || "aihumo_session").replace(/\.[^.]+$/, "");
  const payload = exportPayload(includeFrames);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name}_${includeFrames ? "mobile_session" : "annotations"}.json`;
  link.click();
  URL.revokeObjectURL(url);
  state.dirty = false;
  updateSaveState();
  toast(`Downloaded ${link.download}`);
}

function resetWorkspace() {
  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = null;
  state.videoName = "";
  setFrameRows([]);
  state.annotations = [];
  state.sessionMetadata = {};
  state.frameCount = 0;
  state.durationS = 0;
  state.workspaceKey = "";
  state.pendingResume = null;
  video.removeAttribute("src");
  video.load();
  if (state.thumbnailVideo) state.thumbnailVideo.removeAttribute("src");
  state.thumbnailVideo = null;
  state.thumbnailRenderToken += 1;
  $("videoPlaceholder").classList.remove("hidden");
  $("importStatus").textContent = "No video loaded. Select a video to begin.";
  $("videoInput").value = "";
  $("sessionInput").value = "";
  $("annotationInput").value = "";
  resetEditor();
  renderAnnotations();
  renderThumbnails();
  state.dirty = false;
  updateContextSummary();
  updateTransport();
  updateSaveState();
}

function markDirty() {
  state.dirty = true;
  updateSaveState();
  if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
  if (state.preferences.autosave) state.autosaveTimer = setTimeout(() => saveLocalWorkspace(), 900);
}
function updateSaveState() { $("saveState").textContent = state.dirty ? "Unsaved changes" : "Saved locally"; }

function renderThumbnails() {
  const strip = $("thumbnailStrip");
  strip.replaceChildren();
  for (let offset = -2; offset <= 2; offset += 1) {
    const card = document.createElement("div");
    card.className = "thumb-card";
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 180;
    const label = document.createElement("span");
    label.className = "thumb-label";
    label.dataset.offset = String(offset);
    card.append(canvas, label);
    card.addEventListener("click", () => seekFrame(currentFrame() + offset));
    strip.appendChild(card);
  }
  updateThumbnailSelection(currentFrame());
}

function updateThumbnailSelection(frame) {
  const cards = Array.from($("thumbnailStrip").children);
  cards.forEach((card, index) => {
    const offset = index - 2;
    const targetFrame = Math.max(0, frame + offset);
    card.classList.toggle("current", offset === 0);
    const label = card.querySelector(".thumb-label");
    if (label) label.textContent = `Frame ${targetFrame}`;
  });
  renderThumbnailFrames(frame);
}

async function renderThumbnailFrames(frame) {
  const thumbnailVideo = state.thumbnailVideo;
  if (!thumbnailVideo) return;
  const token = ++state.thumbnailRenderToken;
  try {
    await waitForVideoMetadata(thumbnailVideo);
    const cards = Array.from($("thumbnailStrip").children);
    for (let index = 0; index < cards.length; index += 1) {
      if (token !== state.thumbnailRenderToken) return;
      const targetFrame = Math.max(0, frame + index - 2);
      await seekVideo(thumbnailVideo, Math.max(0, Math.min(frameTime(targetFrame), thumbnailVideo.duration || frameTime(targetFrame))));
      if (token !== state.thumbnailRenderToken) return;
      drawVideoFrame(cards[index].querySelector("canvas"), thumbnailVideo);
    }
  } catch (_) {
    // A browser may reject a thumbnail seek while a file is still opening.
    // The main video remains usable; the next frame update retries it.
  }
}

function waitForVideoMetadata(source) {
  if (source.readyState >= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const onLoaded = () => { cleanup(); resolve(); };
    const onError = () => { cleanup(); reject(new Error("Video metadata unavailable")); };
    const cleanup = () => {
      source.removeEventListener("loadedmetadata", onLoaded);
      source.removeEventListener("error", onError);
    };
    source.addEventListener("loadedmetadata", onLoaded, { once: true });
    source.addEventListener("error", onError, { once: true });
  });
}

function seekVideo(source, time) {
  if (Math.abs((source.currentTime || 0) - time) < 0.001) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const onSeeked = () => { cleanup(); resolve(); };
    const onError = () => { cleanup(); reject(new Error("Video seek unavailable")); };
    const cleanup = () => {
      source.removeEventListener("seeked", onSeeked);
      source.removeEventListener("error", onError);
    };
    source.addEventListener("seeked", onSeeked, { once: true });
    source.addEventListener("error", onError, { once: true });
    source.currentTime = time;
  });
}

function drawVideoFrame(canvas, source) {
  const context = canvas?.getContext("2d");
  if (!context || !source.videoWidth) return;
  const scale = Math.min(canvas.width / source.videoWidth, canvas.height / source.videoHeight);
  const width = source.videoWidth * scale;
  const height = source.videoHeight * scale;
    context.fillStyle = "#dfe7ee";
    context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(source, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
}

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("visible"), 2800);
}

init();
