const $ = (id) => document.getElementById(id);
const unwrappedFetch = window.fetch.bind(window);
let lanEnabled = false, lanReady = false, lanCsrf = null;
window.fetch = (input, options = {}) => {
  const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
  const method = String(options.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (lanEnabled && lanCsrf && url.origin === window.location.origin && url.pathname.startsWith("/api/") && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.set("X-CSRF-Token", lanCsrf); options = { ...options, headers };
  }
  return unwrappedFetch(input, options);
};

const elements = {
  shell: $("app-shell"), sidebarToggle: $("sidebar-toggle"),
  pageTitle: $("page-title"), pageSubtitle: $("page-subtitle"),
  cameraPill: $("camera-pill"), modelPill: $("model-pill"), devicePill: $("device-pill"), liveModelSelector: $("live-model-selector"),
  alert: $("alert"), alertTitle: $("alert-title"), alertCopy: $("alert-copy"), alertDetails: $("alert-details"),
  liveBadge: $("live-badge"), inspectionState: $("inspection-state"), webcam: $("webcam-button"), start: $("start-button"), emptyStart: $("empty-start-button"), reset: $("reset-button"),
  video: $("video-feed"), placeholder: $("video-placeholder"), placeholderTitle: $("placeholder-title"), placeholderCopy: $("placeholder-copy"),
  feedFps: $("feed-fps"), feedResolution: $("feed-resolution"), previewMode: $("preview-mode-button"), previewDescription: $("preview-mode-description"),
  resultEmpty: $("result-empty"), resultActive: $("result-active"), resultEmptyTitle: $("result-empty-title"), resultEmptyCopy: $("result-empty-copy"),
  decision: $("decision"), resultFish: $("result-fish"), resultLabel: $("result-label"), confidence: $("confidence"), confidenceBar: $("confidence-bar"), resultProcessing: $("result-processing"), resultTime: $("result-time"), latestFeatures: $("latest-feature-list"), classificationPolicy: $("classification-policy"),
  latestVerdictDetails: $("latest-verdict-details"), latestVerdictStatus: $("latest-verdict-status"), latestVerdictReason: $("latest-verdict-reason"), latestDetectionConfidence: $("latest-detection-confidence"), latestModel2Evidence: $("latest-model2-evidence"), latestCoverage: $("latest-coverage"), latestEffectiveWeights: $("latest-effective-weights"),
  uploadMode: $("upload-mode-button"), closeUpload: $("close-upload-button"), uploadWorkspace: $("upload-workspace"), uploadInput: $("upload-input"), selectUpload: $("select-upload-button"), uploadFileName: $("upload-file-name"), analyze: $("analyze-button"), uploadStatus: $("upload-status"), uploadProgress: $("upload-analysis-progress"), uploadImage: $("upload-result-image"), uploadVideo: $("upload-result-video"), uploadResults: $("upload-results"),
  kpiGrid: $("kpi-grid"), featureCounterGrid: $("feature-counter-grid"), threshold: $("threshold"), openConfidence: $("open-confidence-button"),
  gradeChartEmpty: $("grade-chart-empty"), gradeChart: $("grade-chart"), gradeDonut: $("grade-donut"), gradeTotal: $("grade-total"), gradeLegend: $("grade-legend"),
  featureChartEmpty: $("feature-chart-empty"), featureChart: $("feature-chart"), throughputChartEmpty: $("throughput-chart-empty"), throughputChart: $("throughput-chart"), throughputLine: $("throughput-line"), throughputCaption: $("throughput-caption"),
  confidenceChartEmpty: $("confidence-chart-empty"), confidenceChart: $("confidence-chart"), averageGradeConfidence: $("average-grade-confidence"),
  recentEmpty: null, recentWrap: null, recentHistoryBody: null, viewAll: $("view-all-button"), resultsDashboard: $("recent-inspections"), resultsSource: $("results-source"), resultsCounts: $("results-counts"), resultsGroups: $("results-groups"), resultsSummary: $("results-summary"), resultsExportCsv: $("results-export-csv"), resultsExportPdf: $("results-export-pdf"),
  historyEmpty: $("history-empty"), historyWrap: $("history-table-wrap"), historyBody: $("history-body"), historySession: $("history-session"), historySearch: $("history-search"), historyGrade: $("history-grade"), historyFeature: $("history-feature"), historyConfidence: $("history-confidence"), historyFilter: $("history-filter-button"), historyPrev: $("history-prev"), historyNext: $("history-next"), historyPage: $("history-page"),
  reviewEmpty: $("review-empty"), reviewWrap: $("review-table-wrap"), reviewBody: $("review-body"), reviewPrev: $("review-prev"), reviewNext: $("review-next"), reviewPage: $("review-page"),
  exportButton: $("export-button"), sidebarExport: $("sidebar-export"), exportModal: $("export-modal"), exportForm: $("export-form"), closeExport: $("close-export-button"), cancelExport: $("cancel-export-button"), dateRange: $("date-range"), exportSessionRange: $("export-session-range"), exportSession: $("export-session"), exportSessionStatus: $("export-session-status"), exportStartDate: $("export-start-date"), exportEndDate: $("export-end-date"),
  settingsButton: $("settings-button"), sidebarSettings: $("sidebar-settings"), settingsDrawer: $("settings-drawer"), closeSettings: $("close-settings-button"), scrim: $("scrim"),
  cameraCalibrationDrawer: $("camera-calibration-drawer"), closeCameraCalibration: $("close-camera-calibration-button"),
  cameraDeviceName: $("camera-device-name"), cameraConnection: $("camera-connection"), cameraLockBadge: $("camera-lock-badge"), cameraCaptureResolution: $("camera-capture-resolution"), cameraProcessingResolution: $("camera-processing-resolution"), cameraHardwareFps: $("camera-hardware-fps"), cameraBackend: $("camera-backend"), cameraProfileName: $("camera-profile-name"), cameraLockState: $("camera-lock-state"),
  calibrationMode: $("calibration-mode-toggle"), cameraControlNote: $("camera-control-note"), cameraControlList: $("camera-control-list"), imageStatistics: $("image-statistics-section"), statFrameBrightness: $("stat-frame-brightness"), statFishBrightness: $("stat-fish-brightness"), statBackgroundBrightness: $("stat-background-brightness"), statContrast: $("stat-contrast"), cameraConditionWarning: $("camera-condition-warning"),
  cameraReset: $("camera-reset-button"), cameraLoadProfile: $("camera-load-profile-button"), cameraSaveProfile: $("camera-save-profile-button"), cameraLock: $("camera-lock-button"), cameraCalibrationMessage: $("camera-calibration-message"),
  cameraProfileConfirmation: $("camera-profile-confirmation"), cameraRecordEmptyReference: $("camera-record-empty-reference-button"), cameraRecordFishReference: $("camera-record-fish-reference-button"), cameraOperatorName: $("camera-operator-name"), cameraInstallationDeviceIdentity: $("camera-install-device-identity"), cameraInstallationHeight: $("camera-install-camera-height"), cameraInstallationAngle: $("camera-install-camera-angle"), cameraInstallationConveyor: $("camera-install-conveyor-position"), cameraInstallationLighting: $("camera-install-lighting-position"), cameraConfirmProfile: $("camera-confirm-profile-button"),
  slider: $("confidence-slider"), settingsThreshold: $("settings-threshold"), confidenceMinus: $("confidence-minus"), confidencePlus: $("confidence-plus"), resetConfidence: $("reset-confidence-button"),
  qualitySlider: $("quality-confidence-slider"), settingsQualityThreshold: $("settings-quality-threshold"), qualityConfidenceMinus: $("quality-confidence-minus"), qualityConfidencePlus: $("quality-confidence-plus"), resetQualityConfidence: $("reset-quality-confidence-button"),
  detectorModelName: $("detector-model-name"), detectorModelStatus: $("detector-model-status"), detectorCheckpoint: $("detector-checkpoint"), detectorDevice: $("detector-device"), detectorThreshold: $("detector-threshold"),
  segmenterModelName: $("segmenter-model-name"), segmenterModelStatus: $("segmenter-model-status"), segmenterCheckpoint: $("segmenter-checkpoint"), segmenterDevice: $("segmenter-device"), segmenterInference: $("segmenter-inference"), model2Selector: $("model2-selector"), model2SelectorStatus: $("model2-selector-status"),
  settingsResolution: $("settings-resolution"), settingsFps: $("settings-fps"), settingsQualityMode: $("settings-quality-mode"), settingsQualityInterval: $("settings-quality-interval"), settingsQualityRoiPadding: $("settings-quality-roi-padding"),
  runtimeDiagnostics: $("runtime-diagnostics"), runtimeDiagnosticsNote: $("runtime-diagnostics-note"), runtimeDiagnosticsValues: $("runtime-diagnostics-values"), debugRuntimeEnabled: $("debug-runtime-enabled"), debugPause: $("debug-pause-button"), hardNegativeList: $("hard-negative-list"),
  debugModel2Raw: $("debug-model2-raw"), debugModel2Associated: $("debug-model2-associated"), debugModel2Rejected: $("debug-model2-rejected"), debugModel2Labels: $("debug-model2-labels"), debugRoiBoundary: $("debug-roi-boundary"),
};

const overlayControls = {
  part_overlays: [$("toggle-part-overlays"), $("settings-part-overlays")], fish_ids: [$("toggle-fish-ids"), $("settings-fish-ids")],
  grades: [$("toggle-grades"), $("settings-grades")], confidence: [$("toggle-confidence"), $("settings-confidence")],
  features: [$("toggle-features"), $("settings-features")], outlines: [$("toggle-outlines"), $("settings-outlines")],
  model2_raw_boxes: [$("debug-model2-raw")], model2_associated_boxes: [$("debug-model2-associated")],
  model2_rejected_boxes: [$("debug-model2-rejected")], model2_labels: [$("debug-model2-labels")], roi_boundary: [$("debug-roi-boundary")],
};
const viewMeta = {
  live: ["Live Inspection", "Real-time Sardinella Lemuru quality inspection"],
  history: ["Inspection History", "Fish inspection records by session"],
  review: ["Review Queue", "Ungraded fish that need an operator decision"],
  model: ["Model", "Local inference availability and operator-safe configuration"],
};
const theme = getComputedStyle(document.documentElement);
const gradeColors = Object.fromEntries(
  [["Class A", "--success"], ["Class B", "--warning"], ["Class C", "--coral"], ["Rejected", "--danger"], ["Ungraded", "--neutral"]]
    .map(([name, token]) => [name, theme.getPropertyValue(token).trim()])
);
// The backend treats these as an exclusive partition of every counted fish.
const sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];

let latestStatus = null;
let analyticsSnapshot = null;
let analyticsSnapshotKey = null;
let analyticsRequestInFlight = false;
let analyticsController = null;
let streamAttached = false;
let streamReady = false;
let rawPreview = false;
let selectedUpload = null;
let uploadInFlight = false;
let uploadSelectionVersion = 0;
let uploadRequestVersion = 0;
let uploadPreviewUrl = null;
 let uploadFrameTimer = null;
let exportInFlight = false;
let exportSessionsLoading = false;
let exportSessionsError = "";
let exportSessionsRequestVersion = 0;
let selectedView = "live";
let historyState = { page: 1, totalPages: 1 };
let reviewState = { page: 1, totalPages: 1 };
let defaultConfidence = 0.5;
let defaultQualityConfidence = 0.25;
let partQualityChart = null;
let colorTrendChart = null;
let decisionTimingChart = null;
let statusRequestInFlight = false;
let statusController = null;
let cameraCalibrationStatus = null;
let controlRequestInFlight = false;
let controlRevision = 0;
let previewImageLoadTimes = [];
let activePanel = null;
let panelTrigger = null;
let historyRequestVersion = 0;
let reviewRequestVersion = 0;
let historyRequestKey = null;
let reviewRequestKey = null;
let historyController = null;
let reviewController = null;
let historyLoadedRevision = null;
let reviewLoadedRevision = null;
let renderedAnalytics = null;
let cameraRenderKey = null;
let alertRenderKey = null;
let latestEvidenceKey = null;
let recentHistoryKey = null;
let resultsFilter = "All";
let resultsEvents = [];
let resultsRenderedFilter = null;
let resultsSource = "live";
let renderedResultsSource = "live";
const resultDatasets = {live: {scope: "", rows: [], metadata: {}}, upload: {scope: "", rows: [], metadata: {}}};
const resultDisclosureStates = new Map();
const resultsHomeAnchor = document.createComment("Unified inspection results location");
elements.resultsDashboard.before(resultsHomeAnchor);
let historyRowsKey = null;
let reviewRowsKey = null;
let modelSelectorModels = [];
let modelSelectorLoading = false;
let modelSelectorChanging = false;
const cameraControlTimers = new Map();
const kpiCards = new Map();
const secondaryKpiCards = new Map();
const featureCards = new Map();
const PREVIEW_IMAGE_LOAD_WINDOW_MS = 5000;
const PREVIEW_IMAGE_LOAD_SAMPLE_LIMIT = 300;
// These are the three Model 2 checkpoints selected for the operator comparison.
// Display names, compatibility, and availability always come from the model registry.
const MODEL2_SELECTOR_IDS = ["yolo26m_partdet", "fasterrcnn_r50fpn_v2", "effnetv2m_retinanet"];
// Match the shipped Model 2 operating point before the first status refresh.
elements.qualitySlider.value = "25";
elements.settingsQualityThreshold.textContent = "25%";

function titleCase(value) { return String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function stateClass(value) {
  if (["healthy", "ready", "connected", "running"].includes(value)) return "healthy";
  if (["starting", "connecting", "checking", "attention"].includes(value)) return "warning";
  if (["errored", "error", "unavailable"].includes(value)) return "error";
  return "neutral";
}
function formatTime(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function formatPercent(value) { return value == null || Number.isNaN(Number(value)) ? "—" : `${Number(value).toFixed(1)}%`; }
function formatMs(value) { return value == null ? "—" : `${Number(value).toFixed(0)} ms`; }
function setCompactStatus(element, label, value, state) {
  element.className = `compact-status ${stateClass(state)}`;
  element.replaceChildren(document.createElement("i"), Object.assign(document.createElement("b"), { textContent: label }), Object.assign(document.createElement("em"), { textContent: value }));
}
function setText(id, value) { const element = $(id); if (element) element.textContent = value; }
function hasEvents(data) { return Number(data?.counters?.total || 0) > 0; }
function resetBrowserPreviewImageLoads() { previewImageLoadTimes = []; }
function pruneBrowserPreviewImageLoads(now) {
  const cutoff = now - PREVIEW_IMAGE_LOAD_WINDOW_MS;
  let firstCurrent = 0;
  while (firstCurrent < previewImageLoadTimes.length && previewImageLoadTimes[firstCurrent] < cutoff) firstCurrent += 1;
  if (firstCurrent) previewImageLoadTimes.splice(0, firstCurrent);
  if (previewImageLoadTimes.length > PREVIEW_IMAGE_LOAD_SAMPLE_LIMIT) previewImageLoadTimes.splice(0, previewImageLoadTimes.length - PREVIEW_IMAGE_LOAD_SAMPLE_LIMIT);
}
function recordBrowserPreviewImageLoad(now = performance.now()) {
  if (!Number.isFinite(now)) return;
  if (previewImageLoadTimes.length && now < previewImageLoadTimes.at(-1)) resetBrowserPreviewImageLoads();
  previewImageLoadTimes.push(now); pruneBrowserPreviewImageLoads(now);
}
function browserPreviewImageLoadFps(now = performance.now()) {
  if (!Number.isFinite(now)) return null;
  pruneBrowserPreviewImageLoads(now);
  if (previewImageLoadTimes.length < 2) return null;
  const duration = previewImageLoadTimes.at(-1) - previewImageLoadTimes[0];
  return duration > 0 ? ((previewImageLoadTimes.length - 1) * 1000) / duration : null;
}
function browserPreviewImageLoadText() {
  const fps = browserPreviewImageLoadFps();
  return fps == null ? "Not measured (waiting for recent image loads)" : `${fps.toFixed(1)} FPS (recent load events)`;
}
function detachStream() {
  elements.video.removeAttribute("src"); streamAttached = false; streamReady = false; resetBrowserPreviewImageLoads();
}

function attachStream() {
  if (streamAttached) return;
  resetBrowserPreviewImageLoads();
  elements.video.src = `/api/video-feed${rawPreview ? "/raw" : ""}?t=${Date.now()}`;
  streamAttached = true;
}
elements.video.addEventListener("load", () => {
  if (!streamAttached) return;
  streamReady = true;
  if (latestStatus?.inspection_status === "running") { recordBrowserPreviewImageLoad(); elements.placeholder.classList.add("hidden"); }
});
elements.video.addEventListener("error", () => {
  detachStream();
  elements.placeholder.classList.remove("hidden");
  elements.placeholderTitle.textContent = "Camera feed interrupted";
  elements.placeholderCopy.textContent = "Reconnecting to the inspection feed…";
});

function renderAlert(data) {
  const modelIssue = data.model_status !== "ready";
  const segmenterIssue = data.runtime_mode !== "part_preview" && ["unavailable", "error"].includes(data.segmenter_status);
  const inspectionIssue = data.inspection_status === "errored";
  const visible = modelIssue || segmenterIssue || inspectionIssue;
  elements.alert.classList.toggle("hidden", !visible);
  if (!visible) return;
  if (modelIssue) {
    elements.alertTitle.textContent = "Detection Model unavailable";
    elements.alertCopy.textContent = data.upload_analysis_available
      ? "Live camera needs the Model 1 fish-detector checkpoint."
      : "Model checkpoint could not be loaded.";
    elements.alertDetails.textContent = data.message || "No diagnostic details supplied.";
  } else if (segmenterIssue) {
    elements.alertTitle.textContent = "Quality Model unavailable";
    elements.alertCopy.textContent = "Fish detection can continue, but fish are recorded as Ungraded until Model 2 is available.";
    elements.alertDetails.textContent = data.segmenter_message || "No diagnostic details supplied.";
  } else if (inspectionIssue) {
    elements.alertTitle.textContent = "Inspection unavailable";
    elements.alertCopy.textContent = "The camera or inspection worker needs attention.";
    elements.alertDetails.textContent = data.message || "No diagnostic details supplied.";
  }
}

function renderCamera(data) {
  const inspection = data.inspection_status;
  elements.previewMode.classList.toggle("hidden", !data.raw_preview_available);
  if (!data.raw_preview_available && rawPreview) { rawPreview = false; detachStream(); }
  elements.previewMode.textContent = rawPreview ? "View processed feed" : "View raw preview";
  elements.previewMode.setAttribute("aria-pressed", String(rawPreview));
  const previewRate = browserPreviewImageLoadText();
  elements.previewDescription.textContent = rawPreview
    ? `Raw camera preview, without AI annotations. This browser's image-load rate: ${previewRate}. Capture-to-display latency is not measured.`
    : `Processed feed with AI annotations. This browser's image-load rate: ${previewRate}. Capture-to-display latency is not measured.`;
  elements.video.alt = rawPreview ? "Raw local webcam preview without AI annotations" : "Annotated local webcam feed";
  const running = ["starting", "running", "stopping"].includes(inspection);
  const preview = data.runtime_mode === "part_preview";
  setCompactStatus($("connection-pill"), "Server", "Online", "ready");
  $("part-preview-banner").classList.toggle("hidden", !preview);
  elements.shell.dataset.runtimeMode = data.runtime_mode || "whole_fish";
  setCompactStatus(elements.cameraPill, "Camera", titleCase(data.camera_status), data.camera_status);
  const qualityStatus = data.model_info?.quality?.status || data.segmenter_status;
  const modelState = data.model_status !== "ready" ? data.model_status : qualityStatus;
  setCompactStatus(elements.modelPill, preview ? "Part model" : "M1 / M2", preview ? titleCase(data.model_status) : `${titleCase(data.model_status)} / ${titleCase(qualityStatus)}`, preview ? data.model_status : modelState);
  const device = data.model_info?.detector?.device ?? "—";
  const deviceKey = String(device).trim().toLowerCase();
  const recognizedDevice = deviceKey === "cpu" || deviceKey === "cuda" || /^\d+$/.test(deviceKey) || /^cuda:\d+$/.test(deviceKey);
  setCompactStatus(elements.devicePill, "Device", String(device).toUpperCase(), recognizedDevice ? "healthy" : "neutral");
  elements.inspectionState.className = `inspection-state ${stateClass(inspection)}`;
  elements.inspectionState.classList.toggle("hidden", inspection === "stopped");
  elements.inspectionState.replaceChildren(document.createElement("i"), document.createTextNode(titleCase(inspection)));
  elements.liveBadge.className = `live-badge ${stateClass(inspection)}`;
  elements.liveBadge.textContent = inspection === "running" ? "LIVE" : inspection === "starting" ? "STARTING" : inspection === "stopping" ? "STOPPING" : "OFFLINE";
  elements.start.disabled = controlRequestInFlight || inspection === "stopping" || data.model_status !== "ready";
  elements.start.textContent = running ? "Stop inspection" : "Start inspection";
  elements.start.classList.toggle("danger", running);
  elements.start.classList.toggle("primary", !running);
  elements.emptyStart.disabled = elements.start.disabled;
  elements.emptyStart.textContent = running ? "Stop inspection" : "Start inspection";
  elements.emptyStart.classList.toggle("danger", running);
  elements.emptyStart.classList.toggle("primary", !running);
  elements.webcam.disabled = controlRequestInFlight || data.model_status !== "ready";
  elements.webcam.textContent = running ? "Webcam active" : "Use webcam";
  elements.webcam.setAttribute("aria-pressed", String(running));
  // Keep the main control in the action row as a single start/stop toggle.
  elements.start.classList.remove("hidden");
  elements.emptyStart.classList.toggle("hidden", running);
  elements.reset.disabled = controlRequestInFlight || ["starting", "stopping"].includes(inspection);
  updateUploadControls();
  if (running) attachStream();
  else if (streamAttached) detachStream();
  elements.placeholder.classList.toggle("hidden", inspection === "running" && streamReady);
  elements.placeholderTitle.classList.toggle("hidden", inspection === "stopped");
  elements.placeholderCopy.classList.toggle("hidden", inspection === "stopped");
  if (inspection === "starting") {
    elements.placeholderTitle.textContent = "Starting inspection";
    elements.placeholderCopy.textContent = "Opening the local camera and preparing inference.";
  } else if (inspection === "stopping") {
    elements.placeholderTitle.textContent = "Stopping inspection";
    elements.placeholderCopy.textContent = "Waiting for the camera and inference worker to finish.";
  } else if (inspection === "errored") {
    elements.placeholderTitle.textContent = "Inspection needs attention";
    elements.placeholderCopy.textContent = data.message || "Check the status message, then start inspection again.";
  } else if (inspection === "running" && !streamReady) {
    elements.placeholderTitle.textContent = "Connecting to inspection camera…";
    elements.placeholderCopy.textContent = rawPreview ? "Waiting for the first raw camera frame." : "Waiting for the first processed camera frame.";
  } else {
    elements.placeholderTitle.textContent = "";
    elements.placeholderCopy.textContent = data.model_status === "ready"
      ? "Start inspection to connect the camera and view live evidence."
      : "The local model is unavailable. See the status message above.";
  }
  const fps = Number(data.fps || 0);
  elements.feedFps.textContent = `AI processing: ${fps.toFixed(1)} FPS`;
  const frameSize = data.frame_size;
  elements.feedResolution.textContent = Array.isArray(frameSize) ? `${frameSize[0]} × ${frameSize[1]}` : "—";
  elements.settingsResolution.textContent = elements.feedResolution.textContent;
  elements.settingsFps.textContent = `${fps.toFixed(1)} FPS`;
}

function analysisFor(event) { return event?.analysis && typeof event.analysis === "object" ? event.analysis : {}; }

// Evidence-aware verdict helpers. Values in persisted records are fractions; the
// fallback also accepts legacy percentage fields so old sessions remain readable.
const MANUAL_GRADE_CHOICES = ["A", "B", "C", "Rejected"];
function finiteNumber(value) { if (value == null || value === "") return null; const number = Number(value); return Number.isFinite(number) ? number : null; }
function asFraction(value) { const number = finiteNumber(value); return number == null ? null : Math.abs(number) > 1 ? number / 100 : number; }
function scoreText(value) { const fraction = asFraction(value); return fraction == null ? "-" : formatPercent(fraction * 100); }
function eventValue(event, ...keys) {
  const topLevel = event && typeof event === "object" ? event : {}; const analysis = analysisFor(event);
  for (const source of [topLevel, analysis]) for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source, key) && source[key] !== null && source[key] !== undefined && source[key] !== "") return source[key];
  }
  return undefined;
}
function model1Confidence(event) { const model1 = analysisFor(event).model1_detection; return model1 && typeof model1 === "object" && model1.confidence != null ? model1.confidence : eventValue(event, "model1_detection_confidence", "detection_confidence", "final_confidence", "confidence_percent"); }
function weightedFinalSupport(event) { return eventValue(event, "final_score", "provisional_score", "best_evidence_score", "quality_confidence"); }
function model2BestEvidence(event) { return { grade: eventValue(event, "best_evidence_class", "provisional_grade", "quality"), score: eventValue(event, "best_evidence_score", "provisional_score", "quality_confidence") }; }
function aiFinalGrade(event) { return String(eventValue(event, "ai_final_grade", "final_grade", "quality") || "Ungraded"); }
function manualGrade(event) { return eventValue(event, "manual_grade"); }
function verdictStatus(event) { return String(eventValue(event, "verdict_status") || "NOT_AVAILABLE").toUpperCase(); }
function readableVerdictStatus(value) {
  const labels = { AUTO_GRADED: "Automatically graded", NEEDS_REVIEW: "Needs review", NOT_AVAILABLE: "Verdict status unavailable" };
  return labels[String(value || "").toUpperCase()] || titleCase(value);
}
function conveyorTiming(event) {
  const value = analysisFor(event).conveyor_timing;
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function readableDecisionDeadlineStatus(value) {
  const labels = { met: "Met", missed: "Missed", not_configured: "Not configured" };
  return labels[String(value || "").toLowerCase()] || "Not recorded";
}
function verdictReason(event) {
  const stored = eventValue(event, "reason_codes");
  const codes = Array.isArray(stored) ? stored.map(String).filter(Boolean) : typeof stored === "string" ? stored.split(",").map((item) => item.trim()).filter(Boolean) : [];
  const code = String(eventValue(event, "verdict_reason_code") || codes[0] || "");
  if (code && !codes.includes(code)) codes.unshift(code);
  return { code, codes, label: codes.join(", ") || code, text: eventValue(event, "verdict_reason_text") };
}
function needsReview(event) { return verdictStatus(event) === "NEEDS_REVIEW"; }
function observedRegions(event) {
  const stored = eventValue(event, "observed_regions");
  if (Array.isArray(stored)) return stored.map((region) => titleCase(region)).filter(Boolean);
  if (typeof stored === "string" && stored.trim()) return stored.split(",").map((region) => titleCase(region.trim())).filter(Boolean);
  const parts = analysisFor(event).part_results || {};
  return ["Body", "Head", "Tail"].filter((region) => parts[region]?.present === true);
}
function coverageText(event) { return scoreText(eventValue(event, "coverage_percentage", "original_weight_coverage", "coverage")); }
function effectiveWeightText(event) {
  const weights = eventValue(event, "effective_weights");
  if (!weights || typeof weights !== "object" || Array.isArray(weights)) return "-";
  const entries = Object.entries(weights).filter(([, value]) => asFraction(value) != null && asFraction(value) > 0);
  return entries.length ? entries.map(([region, weight]) => `${titleCase(region)} ${scoreText(weight)}`).join("; ") : "-";
}
function partFor(event, region) {
  const parts = analysisFor(event).part_results;
  return parts && typeof parts === "object" ? (parts[region] || parts[region.toLowerCase()] || {}) : {};
}
function partStatus(part) {
  if (part && part.visibility_state) return titleCase(String(part.visibility_state).replaceAll("_", " "));
  if (part && part.status) return titleCase(part.status);
  return part?.present ? "Observed" : "Unknown / not observed";
}
function partContribution(part, grade) {
  const contributions = part?.contributions;
  return contributions && typeof contributions === "object" ? contributions[grade] : undefined;
}
function topStatistics(part) {
  const temporal = part?.temporal_statistics;
  return temporal && typeof temporal === "object" && temporal.top_grade_statistics && typeof temporal.top_grade_statistics === "object" ? temporal.top_grade_statistics : {};
}
function latestFeatureRows(event) {
  const rows = ["Body", "Head", "Tail"].map((region) => {
    const part = partFor(event, region);
    if (!part.present) return [region, partStatus(part), "unmeasured"];
    return [region, `${part.grade || "Unknown"} · ${scoreText(part.grade_confidence)}`, "detected"];
  });
  const wholeFishColor = analysisFor(event).color?.["Whole Fish"];
  const brightness = wholeFishColor?.mean_value;
  rows.push(["Brightness", brightness == null ? "Not measured" : `${scoreText(brightness)} (HSV value)`, brightness == null ? "unmeasured" : "detected"]);
  rows.push(["Cracks", "Not measured", "unmeasured"]);
  return rows;
}
function bodyWidthRows(event) {
  const width = event?.analysis?.body_width || {};
  const wholeBox = pixelBox(event?.bbox || event?.analysis?.model1_detection?.bbox);
  const bodyParts = (event?.parts || []).filter((part) => (part.region || part.part) === "Body");
  const bodyPart = bodyParts.reduce((best, part) => !best || Number(part.confidence ?? part.evidence_score ?? 0) > Number(best.confidence ?? best.evidence_score ?? 0) ? part : best, null);
  const bodyBox = pixelBox(bodyPart?.bbox);
  const numberText = (value) => typeof value === "number" && Number.isFinite(value) ? String(Number(value.toFixed(4))) : "Unavailable";
  const dimensions = (x, y) => typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y) ? `${numberText(x)} x ${numberText(y)} px` : "Unavailable";
  const reference = Array.isArray(width.normal_reference_range) && width.normal_reference_range.length === 2 ? width.normal_reference_range.map(numberText).join(" - ") : "Not calibrated";
  const reasons = Array.isArray(width.reliability_reasons) ? width.reliability_reasons.filter(Boolean).map((reason) => String(reason).replaceAll("_", " ")).join("; ") : "";
  const points = typeof width.class_c_supporting_points === "number" && Number.isFinite(width.class_c_supporting_points) ? `${numberText(width.class_c_supporting_points)} / 10` : width.score_status || "Unavailable";
  const contributed = width.score_contributed === true ? "Yes" : width.score_contributed === false ? "No" : "Unavailable";
  return [
    ["Whole-fish bounding box", dimensions(width.whole_fish_width_px ?? wholeBox?.width, width.whole_fish_height_px ?? wholeBox?.height)],
    ["Body bounding box", dimensions(width.body_width_px ?? bodyBox?.width, width.body_height_px ?? bodyBox?.height)],
    ["Relative width proxy", numberText(width.relative_width_proxy)],
    ["Measurement status", width.measurement_status || (width.status === "measured" ? "Measured" : "Missing Detection")],
    ["Orientation", width.orientation || "Unknown"],
    ["Measurement reliability", [width.reliability || "Unavailable", reasons].filter(Boolean).join(": ")],
    ["Calibration status", width.calibration_status || (width.score_status === "Calibrated" ? "Calibrated" : "Not Calibrated")],
    ["Normal reference range", reference],
    ["Width abnormality", width.width_abnormality || "Unavailable"],
    ["Class C supporting points", points],
    ["Contributed to final grade", [contributed, width.contribution_reason ? String(width.contribution_reason).replaceAll("_", " ") : ""].filter(Boolean).join(": ")],
    ["Actual combined-score contribution", numberText(event?.analysis?.geometric_support?.applied_score_shift ?? width.applied_body_score_shift)],
  ];
}
function renderLatest(data) {
  const evidenceKey = JSON.stringify([data.current_detection, data.latest_event, data.runtime_mode]);
  if (latestEvidenceKey === evidenceKey) return;
  latestEvidenceKey = evidenceKey;
  const event = data.current_detection || data.latest_event; const hasEvent = Boolean(event); const liveTrack = Boolean(event?.live_track); const status = verdictStatus(event); const manual = manualGrade(event); const aiGrade = aiFinalGrade(event); const support = weightedFinalSupport(event); const evidence = model2BestEvidence(event); const reason = verdictReason(event);
  elements.resultEmpty.classList.toggle("hidden", hasEvent); elements.resultActive.classList.toggle("hidden", !hasEvent); elements.latestVerdictDetails.classList.toggle("hidden", !hasEvent);
  const verdictClass = aiGrade === "Rejected" ? "error" : aiGrade === "Ungraded" || needsReview(event) ? "warning" : "healthy";
  elements.decision.className = `decision ${hasEvent ? verdictClass : "neutral"}`; elements.decision.textContent = hasEvent ? (liveTrack ? "LIVE FISH" : readableVerdictStatus(status).toUpperCase()) : "WAITING";
  elements.latestFeatures.replaceChildren(Object.assign(document.createElement("p"), {className: "muted", textContent: "Complete evidence and measurements appear once in the grouped fish results below."}));
  $("result-panel").style.setProperty("--grade-color", gradeColors[manual || aiGrade] || gradeColors.Ungraded);
  if (data.runtime_mode === "part_preview") {
    elements.resultEmpty.classList.remove("hidden");
    elements.resultActive.classList.add("hidden");
    elements.latestVerdictDetails.classList.add("hidden");
    elements.resultEmptyTitle.textContent = "Part evidence preview";
    elements.resultEmptyCopy.textContent = "Raw part detections do not establish a whole-fish grade.";
    elements.decision.textContent = "RESEARCH";
    elements.decision.className = "decision warning";
    elements.latestFeatures.replaceChildren();
    elements.classificationPolicy.textContent = "Fish counting and final grading are disabled in this mode.";
    return;
  }
  elements.resultEmptyTitle.textContent = "Ready for the next fish";
  elements.resultEmptyCopy.textContent = "The current track and its quality evidence will appear here.";
  if (!hasEvent) { elements.classificationPolicy.textContent = "Model 1 detection, Model 2 evidence, and final weighted support are reported separately."; return; }
  elements.resultFish.textContent = event.fish_label || `Fish #${event.track_id}`; elements.resultLabel.textContent = manual ? `Manual: ${manual}` : aiGrade; const verdictLabel = elements.resultLabel.closest(".grade-readout")?.querySelector("span"); if (verdictLabel) verdictLabel.textContent = liveTrack ? "LIVE VERDICT" : "FINAL VERDICT";
  elements.confidence.textContent = scoreText(support); elements.confidenceBar.style.width = `${Math.max(0, Math.min(100, (asFraction(support) || 0) * 100))}%`;
  const confidenceLabel = elements.confidence.closest("div")?.querySelector("dt"); if (confidenceLabel) confidenceLabel.textContent = "Weighted final support";
  elements.resultProcessing.textContent = formatMs(event.processing_time_ms); elements.resultTime.textContent = liveTrack ? "Live track" : formatTime(event.timestamp);
  elements.latestVerdictStatus.textContent = manual ? "Manual final grade recorded" : readableVerdictStatus(status); elements.latestVerdictReason.textContent = reason.text || (needsReview(event) ? "The AI did not meet the configured final-verdict acceptance rules." : "No structured verdict reason was supplied.");
  elements.latestDetectionConfidence.textContent = scoreText(model1Confidence(event)); elements.latestModel2Evidence.textContent = `${evidence.grade || "-"} ${scoreText(evidence.score)}`; elements.latestCoverage.textContent = `${coverageText(event)} (${observedRegions(event).join(" / ") || "no regions"})`; elements.latestEffectiveWeights.textContent = effectiveWeightText(event);
  elements.classificationPolicy.textContent = manual ? `Manual final grade: ${manual}. Original AI verdict remains ${aiGrade}; Model 1 detection and Model 2 evidence are retained separately.` : needsReview(event) ? "This is not a Rejected fish. The AI does not have enough reliable evidence for an automatic final grade." : "Model 1 detection, Model 2 evidence, and final weighted support are separate measurements.";
}

function kpiCard(label, value, note, emphasis = false, cache = kpiCards) {
  let record = cache.get(label);
  if (!record) {
    const card = document.createElement("article");
    const labelEl = document.createElement("span"); labelEl.className = "kpi-label"; labelEl.append(document.createElement("i"), document.createTextNode(label));
    const valueEl = document.createElement("strong");
    const noteEl = document.createElement("small");
    card.append(labelEl, valueEl, noteEl);
    record = { card, valueEl, noteEl };
    cache.set(label, record);
  }
  record.card.className = `kpi-card${emphasis ? " emphasis" : ""}`;
  record.card.style.setProperty("--grade-color", gradeColors[label] || theme.getPropertyValue("--ocean-700").trim());
  const nextValue = String(value);
  if (record.valueEl.textContent !== nextValue) record.valueEl.textContent = nextValue;
  if (record.noteEl.textContent !== note) record.noteEl.textContent = note;
  return record.card;
}

function reconcileCards(container, cache, cards, makeCard) {
  const wanted = new Set(cards.map(([name]) => name));
  for (const [name, record] of cache) {
    if (!wanted.has(name)) {
      record.card.remove();
      cache.delete(name);
    }
  }
  if (!container) return;
  cards.forEach((cardData, index) => {
    const card = makeCard(cardData);
    if (container.children[index] !== card) container.insertBefore(card, container.children[index] || null);
  });
}
function renderKpis(data) {
  const counters = data.counters || {}; const grades = data.quality_counters || {}; const total = Number(counters.total || 0);
  const processingTiming = data.runtime_diagnostics?.timings?.total_processing;
  const latency = processingTiming?.mean ?? data.analytics?.average_processing_time_ms;
  const cards = [
    ["Fish detected", total, "Since reset", true],
    ["Processing FPS", `${Number(data.fps || 0).toFixed(1)}`, "AI-processed frames per second"],
    ["Latency", latency == null ? "Not measured" : `${Number(latency).toFixed(0)} ms`, "Average frame processing time"],
    ["Detection threshold", formatPercent(Number(data.detection_confidence_threshold) * 100), "Model 1 confidence"],
  ];
  elements.kpiGrid.querySelector(".metric-waiting")?.remove();
  if (data.runtime_mode === "part_preview") {
    cards[0] = ["Fish detected", "—", "Counting disabled in part preview", true];
  }
  reconcileCards(elements.kpiGrid, kpiCards, cards, ([label, value, note, emphasis]) => kpiCard(label, value, note, Boolean(emphasis)));
  reconcileCards($("secondary-kpi-grid"), secondaryKpiCards, [], ([label, value, note]) => kpiCard(label, value, note, false, secondaryKpiCards));
  elements.threshold.textContent = formatPercent(Number(data.detection_confidence_threshold) * 100);
}

function renderFeatureCounters(data) {
  const counters = Object.entries(data.feature_counters || {});
  reconcileCards(elements.featureCounterGrid, featureCards, counters, ([name, detail]) => {
    let record = featureCards.get(name);
    if (!record) {
      const card = document.createElement("article");
      const title = document.createElement("span"); title.textContent = name;
      const value = document.createElement("strong");
      const note = document.createElement("small");
      card.append(title, value, note);
      record = { card, value, note };
      featureCards.set(name, record);
    }
    record.card.className = `feature-counter${detail.available ? "" : " unavailable"}`;
    const valueText = detail.available ? String(detail.count || 0) : "Not measured";
    if (record.value.textContent !== valueText) record.value.textContent = valueText;
    const noteText = String(detail.source || "");
    if (record.note.textContent !== noteText) record.note.textContent = noteText;
    return record.card;
  });
}

function ensureAnalysisCharts() {
  if (partQualityChart && colorTrendChart && decisionTimingChart) return;
  const grid = document.querySelector("#analytics-section .analytics-grid"); if (!grid) return;
  const makeCard = (title) => { const card = document.createElement("article"); card.className = "chart-card surface"; const heading = document.createElement("h3"); heading.textContent = title; const chart = document.createElement("div"); chart.className = "bar-chart"; card.append(heading, chart); grid.append(card); return chart; };
  partQualityChart = makeCard("Average part quality scores");
  colorTrendChart = makeCard("Colour measurement trend");
  decisionTimingChart = makeCard("Conveyor decision timing");
}
function appendMetricRow(container, label, fraction, value) {
  const row = document.createElement("div"); row.className = "bar-row"; const name = document.createElement("span"); name.textContent = label; const track = document.createElement("i"); track.style.setProperty("--bar-width", `${Math.max(0, Math.min(100, fraction * 100))}%`); const amount = document.createElement("b"); amount.textContent = value; row.append(name, track, amount); container.append(row);
}
function renderAnalytics(analytics) {
  const reasons = $("ungraded-reasons");
  if (reasons) {
    reasons.replaceChildren();
    const counts = analytics?.ungraded_reasons;
    if (!counts || typeof counts !== "object" || Array.isArray(counts)) {
      reasons.textContent = analytics?.has_data ? "Reasons not available" : "Waiting for inspection data";
    } else if (!Object.keys(counts).length) {
      reasons.textContent = "No AI Ungraded reasons recorded";
    } else {
      Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0])).forEach(([reason, count]) => {
        const row = document.createElement("div"); row.className = "legend-row";
        row.append(Object.assign(document.createElement("span"), { textContent: reason }), Object.assign(document.createElement("b"), { textContent: String(count) }));
        reasons.append(row);
      });
    }
  }
  ensureAnalysisCharts();
  const hasData = Boolean(analytics?.has_data);
  [elements.gradeChartEmpty, elements.featureChartEmpty, elements.throughputChartEmpty, elements.confidenceChartEmpty].forEach((element) => element.classList.toggle("hidden", hasData));
  elements.gradeChart.classList.toggle("hidden", !hasData); elements.featureChart.classList.toggle("hidden", !hasData); elements.throughputChart.classList.toggle("hidden", !hasData);
  const confidenceAvailable = analytics?.average_grade_confidence != null;
  elements.confidenceChart.classList.toggle("hidden", !confidenceAvailable);
  elements.confidenceChartEmpty.classList.toggle("hidden", confidenceAvailable);
  if (!hasData) {
    [partQualityChart, colorTrendChart, decisionTimingChart].filter(Boolean).forEach((chart) => {
      chart.classList.add("chart-empty");
      chart.textContent = "Waiting for inspection data";
    });
    return;
  }
  [partQualityChart, colorTrendChart, decisionTimingChart].filter(Boolean).forEach((chart) => chart.classList.remove("chart-empty"));
  const distribution = analytics.grade_distribution || {}; const total = Object.values(distribution).reduce((sum, value) => sum + Number(value || 0), 0);
  let offset = 0; const segments = []; const colors = { ...gradeColors };
  Object.keys(distribution).forEach((name) => { if (!colors[name]) colors[name] = gradeColors.Ungraded; });
  Object.entries(colors).filter(([name]) => name in distribution).forEach(([name, color]) => { const portion = total ? (Number(distribution[name] || 0) / total) * 100 : 0; segments.push(`${color} ${offset}% ${offset + portion}%`); offset += portion; });
  elements.gradeDonut.style.background = `conic-gradient(${segments.join(", ")})`;
  elements.gradeTotal.textContent = String(total);
  elements.gradeLegend.replaceChildren();
  Object.entries(colors).filter(([name]) => name in distribution).forEach(([name, color]) => { const row = document.createElement("div"); row.className = "legend-row"; row.style.setProperty("--legend-color", color); const label = document.createElement("span"); label.textContent = name; const value = document.createElement("b"); value.textContent = String(distribution[name] || 0); row.append(label, value); elements.gradeLegend.append(row); });
  elements.featureChart.replaceChildren();
  const features = analytics.feature_counts || {}; const measurable = Object.entries(features).filter(([, detail]) => detail.available);
  const max = Math.max(1, ...measurable.map(([, detail]) => Number(detail.count || 0)));
  measurable.forEach(([name, detail]) => { const row = document.createElement("div"); row.className = "bar-row"; const label = document.createElement("span"); label.textContent = name; const track = document.createElement("i"); track.style.setProperty("--bar-width", `${(Number(detail.count || 0) / max) * 100}%`); const value = document.createElement("b"); value.textContent = String(detail.count || 0); row.append(label, track, value); elements.featureChart.append(row); });
  if (partQualityChart) { partQualityChart.replaceChildren(); const scores = analytics.average_part_quality_scores || {}; ["Body", "Head", "Tail"].forEach((region) => { const score = scores[region]; appendMetricRow(partQualityChart, region, Number(score || 0) / 100, score == null ? "—" : formatPercent(score)); }); }
  if (colorTrendChart) { colorTrendChart.replaceChildren(); const trend = analytics.color_trend || []; if (!trend.length) { const note = document.createElement("span"); note.textContent = "No measured HSV samples"; colorTrendChart.append(note); } else trend.slice(-6).forEach((sample) => appendMetricRow(colorTrendChart, formatTime(sample.timestamp), Number(sample.mean_hue_deg || 0) / 360, `${Number(sample.mean_hue_deg).toFixed(1)}° / ${formatPercent(sample.yellow_ratio_proxy)}`)); }
  if (decisionTimingChart) {
    decisionTimingChart.replaceChildren();
    const average = finiteNumber(analytics.average_first_detection_to_decision_ms);
    const statuses = analytics.decision_deadline_status_counts && typeof analytics.decision_deadline_status_counts === "object" ? analytics.decision_deadline_status_counts : {};
    const statusCount = (value) => Math.max(0, finiteNumber(value) ?? 0);
    const met = statusCount(statuses.met); const missed = statusCount(statuses.missed); const notConfigured = statusCount(statuses.not_configured);
    if (average == null) {
      decisionTimingChart.append(Object.assign(document.createElement("span"), { textContent: "No finalized decision-timing measurement yet" }));
    } else {
      const averageLine = document.createElement("p"); averageLine.textContent = `Average first detection to decision: ${formatMs(average)}`; decisionTimingChart.append(averageLine);
      const configuredTotal = Math.max(1, met + missed);
      appendMetricRow(decisionTimingChart, "Deadline met", met / configuredTotal, String(met));
      appendMetricRow(decisionTimingChart, "Deadline missed", missed / configuredTotal, String(missed));
      const unconfigured = document.createElement("p"); unconfigured.textContent = `No deadline configured: ${notConfigured}`; decisionTimingChart.append(unconfigured);
    }
    const scope = typeof analytics.decision_timing_scope === "string" && analytics.decision_timing_scope.trim()
      ? analytics.decision_timing_scope.trim()
      : "Elapsed time from first persistent Model 1 detection to the virtual count-line decision; it is not physical entry or actuator confirmation.";
    decisionTimingChart.append(Object.assign(document.createElement("small"), { textContent: scope }));
  }
  const throughput = analytics.throughput || []; const maxTotal = Math.max(1, ...throughput.map((item) => Number(item.total || 0))); const denominator = Math.max(1, throughput.length - 1);
  const points = throughput.map((item, index) => `${(index / denominator) * 560},${166 - (Number(item.total || 0) / maxTotal) * 142}`).join(" ");
  elements.throughputLine.setAttribute("points", points || "0,166");
  const trendLabel = Number(analytics.trend_events_total || 0) > throughput.length ? `latest ${throughput.length}` : `${throughput.length}`;
  elements.throughputCaption.textContent = `${total} fish · ${trendLabel} observations`;
  if (confidenceAvailable) elements.averageGradeConfidence.textContent = `Track-mean M1 detection confidence ${formatPercent(analytics.average_detection_confidence)} · final support ${formatPercent(analytics.average_grade_confidence)}`;
}

function detectedFeatures(event) {
  const regions = [...new Set((event?.parts || []).map((part) => part.region).filter(Boolean))];
  return regions.length ? regions.join(", ") : "No Model 2 regions";
}
function historyCell(value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value == null || value === "" ? "—" : String(value);
  if (className) cell.className = className;
  if (className === "grade-cell") cell.style.setProperty("--grade-color", gradeColors[value] || gradeColors.Ungraded);
  return cell;
}
function fishHistoryCell(event) {
  const cell = document.createElement("td");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "history-open";
  button.textContent = event.fish_label || `Fish #${event.track_id}`;
  button.setAttribute("aria-label", `Open full analysis for ${button.textContent}`);
  button.addEventListener("click", () => openHistoryAnalysis(event));
  cell.append(button);
  return cell;
}
function labelHistoryRows(body) {
  const table = body.closest("table");
  table.setAttribute("role", "table");
  table.setAttribute("aria-label", body === elements.historyBody ? "Inspection history" : body === elements.reviewBody ? "Review queue" : "Recent inspections");
  const headings = [...table.querySelectorAll("thead th")].map((header) => header.textContent.trim());
  table.querySelectorAll("thead, tbody").forEach((group) => group.setAttribute("role", "rowgroup"));
  table.querySelectorAll("tr").forEach((row) => row.setAttribute("role", "row"));
  body.querySelectorAll("tr").forEach((row) => {
    [...row.children].forEach((cell, index) => {
      cell.dataset.label = headings[index] || "Detail";
      cell.setAttribute("role", "cell");
    });
  });
}
function resultGrade(event) {
  const grade = manualGrade(event) || aiFinalGrade(event);
  return sessionGradeBuckets.includes(grade) ? grade : "Ungraded";
}
function resultValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(Math.round(value * 100) / 100) : "—";
  return String(value);
}
function resultEvidenceRows(event) {
  const analysis = event?.analysis && typeof event.analysis === "object" ? event.analysis : {};
  const detection = analysis.model1_detection && typeof analysis.model1_detection === "object" ? analysis.model1_detection : {};
  const weights = analysis.effective_weights || analysis.weighted_weights || {};
  const parts = Array.isArray(event?.parts) ? event.parts : [];
  const geometry = analysis.geometric_support || {};
  return [
    ["Model 1 detection", scoreText(detection.confidence ?? event?.final_confidence)],
    ...["Body", "Head", "Tail"].map((region) => {
      const part = analysis.part_results?.[region];
      return [`Model 2 ${region}`, part?.present ? `${part.grade || "Observed"} · ${scoreText(part.grade_confidence)} part confidence` : partEvidenceText(parts, region)];
    }),
    ["Effective weights", Object.keys(weights).length ? Object.entries(weights).map(([key, value]) => `${key}: ${resultValue(value)}`).join(" · ") : effectiveWeightText(event)],
    ["Original weighted classification", geometry.original_grade || "Not recorded"],
    ["Original weighted support", scoreText(geometry.original_support)],
    ["Final combined support", scoreText(weightedFinalSupport(event))],
    ["Ungraded reason", resultGrade(event) === "Ungraded" ? (verdictReason(event).text || analysis.verdict_reason_text || "Evidence was missing or unreliable.") : "—"],
  ];
}
function partEvidenceText(parts, region) {
  const matches = parts.filter((part) => String(part?.region || "").toLowerCase() === region.toLowerCase());
  if (!matches.length) return "Not Detected";
  const best = matches.reduce((item, current) => Number(current?.evidence_score ?? current?.confidence ?? 0) > Number(item?.evidence_score ?? item?.confidence ?? 0) ? current : item);
  return `${best.grade || best.source_class_name || "Observed"} · ${scoreText(best.evidence_score ?? best.confidence)}`;
}
const measurementColumns = [["mean_hue_deg", "Hue (deg)"], ["mean_saturation", "Saturation (0–1)"], ["mean_value", "Brightness / HSV value (0–1)"], ["yellow_ratio_proxy", "Yellow proxy"], ["brown_ratio_proxy", "Brown proxy"], ["dark_patch_ratio_proxy", "Dark-area proxy"], ["discoloration_coverage_proxy", "Discoloration proxy"], ["specular_ratio_proxy", "Highlight proxy"]];
function measurementRegion(event, region) {
  const reading = event?.analysis?.supporting_image_measurements?.regions?.[region] || {};
  const part = (event?.parts || []).find((value) => (value.region || value.part) === region);
  const width = event?.analysis?.body_width || {};
  const frame = Array.isArray(reading.frame_rois) ? reading.frame_rois.at(-1) : null;
  const box = region === "Whole Fish" ? width.whole_fish_bbox || event.bbox || frame?.crop_local_bbox : region === "Body" ? width.body_bbox || part?.bbox || frame?.crop_local_bbox : part?.bbox || frame?.crop_local_bbox;
  return {reading, box, dimensions: pixelBox(box), values: reading.values || {}, status: reading.status === "measured" ? "Measured" : part || region === "Whole Fish" && box ? "Not measured" : "Not Detected"};
}
function measurementRows(event) {
  return ["Whole Fish", "Body", "Head", "Tail"].map((region) => {
    const item = measurementRegion(event, region);
    return [region, item.status, item.dimensions ? `${resultValue(item.dimensions.width)} x ${resultValue(item.dimensions.height)} px` : "Not Detected", ...measurementColumns.map(([key]) => item.reading.status === "measured" ? resultValue(item.values[key]) : "—")];
  });
}
function finalExplanationRows(event) {
  const analysis = event.analysis || {}; const geometry = analysis.geometric_support || {}; const width = analysis.body_width || {};
  const reason = verdictReason(event);
  return [
    ["Original weighted grade", geometry.original_grade || "Not recorded"],
    ["Geometric support", typeof geometry.class_c_points === "number" ? `${resultValue(geometry.class_c_points)} / 10 points` : width.score_status || "Unavailable"],
    ["Geometric contribution", String(geometry.contribution_reason || width.contribution_reason || "Not recorded").replaceAll("_", " ")],
    ["Final combined AI grade", aiFinalGrade(event)],
    ["Width changed classification", geometry.width_changed_classification === true ? "Yes" : geometry.width_changed_classification === false ? "No" : "Not recorded"],
    ...(manualGrade(event) ? [["Operator-reviewed final grade", manualGrade(event)]] : []),
    ["Decision reason", reason.text || (analysis.explanation || []).join(" ") || "Model 2 evidence and configured acceptance safeguards determine the final grade."],
    ...(aiFinalGrade(event) === "Ungraded" ? [["Next step", "Review the reason above and acquire a clear view with reliable Model 2 Body evidence; geometric support cannot bypass missing evidence."]] : []),
  ];
}
function appendResultTable(parent, headers, rows) {
  const scroll = document.createElement("div"); scroll.className = "result-table-scroll"; scroll.tabIndex = 0;
  const table = document.createElement("table"); table.className = "compact-results-table";
  const thead = document.createElement("thead"); const headRow = document.createElement("tr"); headers.forEach((header) => { const cell = document.createElement("th"); cell.textContent = header; headRow.append(cell); }); thead.append(headRow);
  const body = document.createElement("tbody"); rows.forEach((values) => { const row = document.createElement("tr"); values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = resultValue(value); row.append(cell); }); body.append(row); }); table.append(thead, body); scroll.append(table); parent.append(scroll);
}
function resultIdentity(event, scope = "current", index = 0) {
  const identifier = event.track_id ?? event.id ?? event.fish_id;
  return `${event.session_id || scope}:${identifier == null ? `detection-${index}` : identifier}`;
}
function mergeResultEvidence(previous, current) {
  if (!previous) return {...current};
  const merge = (left, right) => {
    const result = {...left};
    Object.entries(right || {}).forEach(([key, value]) => {
      if (value && typeof value === "object" && !Array.isArray(value) && left?.[key] && typeof left[key] === "object" && !Array.isArray(left[key])) result[key] = merge(left[key], value);
      else if (value !== undefined) result[key] = value;
    });
    return result;
  };
  const result = merge(previous, current);
  const completeAnalysis = current.analysis && (Object.hasOwn(current.analysis, "final_grade") || Object.hasOwn(current.analysis, "weighted_scores"));
  if (completeAnalysis) {
    // Complete grading snapshots are coherent observations. Never carry old
    // Body/width evidence into a newer missing or differently associated Body.
    result.analysis = {...current.analysis};
    result.parts = Array.isArray(current.parts) ? current.parts : [];
    if (previous.analysis?.body_width?.relative_width_proxy != null && current.analysis.body_width?.relative_width_proxy == null) {
      result._previous_measurement_evidence = {timestamp: previous.timestamp, frame_id: previous.analysis.body_width.frame_id, body_width: previous.analysis.body_width, supporting_image_measurements: previous.analysis.supporting_image_measurements};
    }
  }
  return result;
}
function uniqueResultEvents(rows, scope = "current", previous = [], complete = true) {
  const earlier = new Map(previous.map((event, index) => [resultIdentity(event, scope, index), event]));
  const merged = complete ? new Map() : new Map(earlier);
  (Array.isArray(rows) ? rows : []).forEach((event, index) => {
    if (!event || typeof event !== "object") return;
    const key = resultIdentity(event, scope, index); const prior = merged.get(key) || earlier.get(key);
    // A response may contain repeated observations of one tracked fish. Keep
    // the newest timestamp and merge partial evidence into that identity.
    const previousTime = Date.parse(prior?.timestamp); const updateTime = Date.parse(event.timestamp);
    const current = Number.isFinite(previousTime) && Number.isFinite(updateTime) && updateTime < previousTime ? mergeResultEvidence(event, prior) : mergeResultEvidence(prior, event);
    merged.set(key, current);
  });
  return [...merged.values()];
}
function resultsScope() { return latestStatus?.durable_session?.session_id || "current"; }
function rememberResultsDisclosures() {
  const state = new Set(resultDisclosureStates.get(renderedResultsSource) || []);
  elements.resultsGroups.querySelectorAll("details[data-disclosure-key]").forEach((item) => { state.delete(item.dataset.disclosureKey); if (item.open) state.add(item.dataset.disclosureKey); });
  resultDisclosureStates.set(renderedResultsSource, state);
}
function lazyResultSection(parent, title, key, build, expanded = new Set()) {
  const details = document.createElement("details"); details.className = "result-evidence-section"; details.dataset.disclosureKey = key;
  const summary = document.createElement("summary"); summary.textContent = title; details.append(summary);
  let built = false;
  const populate = () => { if (!details.open || built) return; built = true; const body = document.createElement("div"); body.className = "result-section-body"; build(body); details.append(body); };
  details.addEventListener("toggle", populate); details.open = expanded.has(key); parent.append(details); populate(); return details;
}
function appendResultCard(parent, event) {
  const grade = resultGrade(event); const details = document.createElement("details"); details.className = "result-fish-card";
  const key = resultIdentity(event, resultDatasets[resultsSource].scope); const expanded = resultDisclosureStates.get(resultsSource) || new Set();
  details.dataset.fishKey = key; details.dataset.disclosureKey = `fish:${key}`;
  const summary = document.createElement("summary"); const title = document.createElement("strong"); title.textContent = event.fish_label || `Fish #${event.track_id ?? event.id ?? event.fish_id ?? "?"}`;
  const support = document.createElement("b"); support.textContent = `Final support: ${scoreText(weightedFinalSupport(event))}`;
  const status = document.createElement("span"); status.textContent = grade; summary.append(title, status, support); details.append(summary);
  let built = false;
  const populate = () => {
    if (!details.open || built) return; built = true;
    const body = document.createElement("div"); body.className = "result-fish-details";
    lazyResultSection(body, "A. Grading Evidence", `${key}:A`, (section) => {
      appendResultTable(section, ["Evidence", "Recorded value"], resultEvidenceRows(event));
      const scores = event.analysis?.geometric_support?.original_scores || event.analysis?.weighted_scores || {};
      appendResultTable(section, ["Class", "Original weighted support (0–1)"], sessionGradeBuckets.filter((name) => name !== "Ungraded").map((name) => [name, scores[name]]));
      section.append(Object.assign(document.createElement("p"), {className: "muted", textContent: "Detection confidence, part confidence, weighted support and geometric points describe different evidence; support is not measured accuracy."}));
    }, expanded);
    lazyResultSection(body, "B. Body Width and Geometric Analysis", `${key}:B`, (section) => {
      appendResultTable(section, ["Measurement / evidence", "Value"], bodyWidthRows(event));
      section.append(Object.assign(document.createElement("p"), {className: "muted", textContent: "Bounding-box proxy, not anatomical width. Unreliable measurements remain visible and cannot contribute grading points."}));
    }, expanded);
    lazyResultSection(body, "C. Image Features and Measurements", `${key}:C`, (section) => {
      appendResultTable(section, ["Region", "Status", "Bounding box", ...measurementColumns.map(([, label]) => label)], measurementRows(event));
      section.append(Object.assign(document.createElement("p"), {className: "muted", textContent: "Color measurements are diagnostic only; rectangular ROIs can include background. Brightness uses HSV value (brightness proxy). No fish mask or calibrated cm/mm scale is available. Yellow and highlight values are not validated defect or shininess detection."}));
    }, expanded);
    lazyResultSection(body, "D. Final Grading Explanation", `${key}:D`, (section) => {
      appendResultTable(section, ["Decision stage", "Recorded result"], finalExplanationRows(event));
      const metadata = document.createElement("details"); const heading = document.createElement("summary"); heading.textContent = "Model, source and threshold configuration"; metadata.append(heading);
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify(event, null, 2); metadata.append(pre); section.append(metadata);
      if (event._inspection_source !== "upload" && event._inspection_source !== "history") appendManualReviewPanel(section, event);
    }, expanded);
    details.append(body);
  };
  details.addEventListener("toggle", populate); details.open = expanded.has(`fish:${key}`); parent.append(details); populate(); return details;
}
function renderResultsDashboard(history, {source = "live", complete = false, metadata = {}, scope = null, renderOnly = false} = {}) {
  if (!renderOnly) {
    const dataset = resultDatasets[source]; const nextScope = scope || (source === "live" ? resultsScope() : dataset.scope || "photo");
    if (dataset.scope !== nextScope) { dataset.rows = []; resultDisclosureStates.delete(source); dataset.scope = nextScope; }
    dataset.rows = uniqueResultEvents(history, nextScope, dataset.rows, complete).map((event) => ({...event, _inspection_source: source}));
    dataset.metadata = {...dataset.metadata, ...metadata};
  }
  if (!renderOnly && source !== resultsSource) return;
  const dataset = resultDatasets[resultsSource]; const rows = dataset.rows; const key = JSON.stringify([resultsSource, dataset.scope, dataset.metadata, rows]);
  if (key === recentHistoryKey && resultsRenderedFilter === resultsFilter && elements.resultsGroups.childElementCount) return;
  rememberResultsDisclosures(); renderedResultsSource = resultsSource; recentHistoryKey = key; resultsEvents = rows;
  resultsRenderedFilter = resultsFilter;
  const counts = Object.fromEntries(["All", ...sessionGradeBuckets].map((grade) => [grade, grade === "All" ? rows.length : rows.filter((event) => resultGrade(event) === grade).length]));
  elements.resultsCounts.replaceChildren();
  const countCards = [
    ["All Fish", "All", counts.All, "all"],
    ["Graded Fish", null, counts.All - counts.Ungraded, "graded"],
    ["Class A", "Class A", counts["Class A"], "class-a"],
    ["Class B", "Class B", counts["Class B"], "class-b"],
    ["Class C", "Class C", counts["Class C"], "class-c"],
    ["Rejected", "Rejected", counts.Rejected, "rejected"],
    ["Ungraded", "Ungraded", counts.Ungraded, "ungraded"],
  ];
  countCards.forEach(([label, category, count, tone]) => {
    const item = document.createElement(category ? "button" : "div");
    item.className = `results-count-card ${tone}`;
    if (category) {
      item.type = "button";
      item.dataset.resultsFilter = category;
      item.setAttribute("aria-pressed", String(category === resultsFilter));
      item.addEventListener("click", () => {
        resultsFilter = category;
        recentHistoryKey = null;
        renderResultsDashboard(null, {renderOnly: true});
      });
      item.classList.toggle("active", category === resultsFilter);
    } else {
      item.setAttribute("aria-label", `${label}: ${count} fish`);
    }
    item.append(Object.assign(document.createElement("small"), {textContent: label}), Object.assign(document.createElement("strong"), {textContent: String(count)}));
    elements.resultsCounts.append(item);
  });
  elements.resultsSource.value = resultsSource;
  const visible = resultsFilter === "All" ? rows : rows.filter((event) => resultGrade(event) === resultsFilter); elements.resultsSummary.textContent = `${dataset.metadata.source_name || (resultsSource === "upload" ? "Uploaded photo" : "Live inspection session")} · ${visible.length} shown / ${rows.length} unique fish. Expand a class, then a fish, to inspect its evidence.`;
  elements.resultsGroups.replaceChildren();
  const groups = resultsFilter === "All" ? sessionGradeBuckets : [resultsFilter];
  const expanded = resultDisclosureStates.get(resultsSource) || new Set();
  groups.forEach((grade) => {
    const groupRows = visible.filter((event) => resultGrade(event) === grade); if (!groupRows.length && resultsFilter === "All") return;
    const group = document.createElement("details"); group.className = "result-grade-group"; group.dataset.grade = grade; group.dataset.disclosureKey = `group:${grade}`;
    const summary = document.createElement("summary"); summary.append(Object.assign(document.createElement("span"), {textContent: grade}), Object.assign(document.createElement("b"), {textContent: String(groupRows.length)})); group.append(summary);
    let built = false;
    const populate = () => {
      if (!group.open || built) return; built = true; const cards = document.createElement("div"); cards.className = "result-fish-cards"; let rendered = 0;
      const more = document.createElement("button"); more.type = "button"; more.className = "button quiet result-load-more";
      const batch = () => { const end = Math.min(rendered + 50, groupRows.length); for (; rendered < end; rendered++) appendResultCard(cards, groupRows[rendered]); more.textContent = `Show next ${Math.min(50, groupRows.length - rendered)} fish (${rendered} / ${groupRows.length})`; more.hidden = rendered >= groupRows.length; };
      more.addEventListener("click", batch); group.append(cards, more); batch();
    };
    group.addEventListener("toggle", populate); group.open = expanded.has(`group:${grade}`) || resultsFilter !== "All"; elements.resultsGroups.append(group); populate();
  });
  if (!visible.length) { const empty = document.createElement("p"); empty.className = "history-empty"; empty.textContent = "No fish match this classification yet."; elements.resultsGroups.append(empty); }
}
function selectResultsSource(source) {
  if (!resultDatasets[source] || source === "upload" && !resultDatasets.upload.scope) return;
  rememberResultsDisclosures(); resultsSource = source; recentHistoryKey = null;
  renderResultsDashboard(null, {renderOnly: true});
  if (source === "live") void loadResultsDashboard();
}
function mountResultsDashboard(inUpload = false) {
  if (inUpload) elements.uploadResults.append(elements.resultsDashboard);
  else resultsHomeAnchor.after(elements.resultsDashboard);
}
let resultsRequestInFlight = false;
let loadedResultsRevision = null;
async function loadResultsDashboard() {
  const scope = resultsScope(); const revision = analyticsVersion(latestStatus);
  if (resultsRequestInFlight || selectedView !== "live" || resultsSource !== "live" || loadedResultsRevision === revision) return;
  resultsRequestInFlight = true;
  try {
    const response = await fetch("/api/history?page=1&page_size=100&range_name=current_session");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    let items = data.items || data.recent_history || [];
    for (let page = 2; page <= Number(data.total_pages || 1); page += 1) {
      const pageResponse = await fetch(`/api/history?page=${page}&page_size=100&range_name=current_session`);
      if (!pageResponse.ok) throw new Error(`HTTP ${pageResponse.status}`);
      const pageData = await pageResponse.json();
      items = items.concat(pageData.items || []);
    }
    if (scope !== resultsScope() || revision !== analyticsVersion(latestStatus)) return;
    renderResultsDashboard(items, {source: "live", scope, metadata: {source_name: "Live inspection session", session_id: scope, model_info: latestStatus?.model_info}});
    loadedResultsRevision = revision;
  } catch (error) {
    if (resultsSource === "live") elements.resultsSummary.textContent = `Unable to load fish-level results: ${error.message}`;
  } finally {
    resultsRequestInFlight = false;
  }
}
function selectedResultEvents() { return uniqueResultEvents(resultsEvents, resultDatasets[resultsSource].scope).filter((event) => resultsFilter === "All" || resultGrade(event) === resultsFilter); }
function flattenResultData(value, prefix = "", output = {}) {
  Object.entries(value || {}).forEach(([key, item]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object" && !Array.isArray(item)) flattenResultData(item, name, output);
    else output[name] = Array.isArray(item) ? JSON.stringify(item) : item ?? "";
  });
  return output;
}
function resultExportRecord(event) {
  const analysis = event.analysis || {}; const geometry = analysis.geometric_support || {};
  const record = {
    "Fish ID": event.fish_label || `Fish #${event.track_id ?? event.id ?? event.fish_id ?? "?"}`,
    "Unique identity": resultIdentity(event, resultDatasets[resultsSource].scope),
    "Source": resultDatasets[resultsSource].metadata.source_name || resultsSource,
    "Timestamp": event.timestamp || "", "Original weighted grade": geometry.original_grade || "Not recorded",
    "Original weighted support (0-1)": geometry.original_support ?? "", "Final AI grade": aiFinalGrade(event),
    "Final classification": resultGrade(event), "Final combined support (0-1)": weightedFinalSupport(event) ?? "",
    "Width changed classification": geometry.width_changed_classification ?? "",
    "Class C width points (0-10)": geometry.class_c_points ?? analysis.body_width?.class_c_supporting_points ?? "",
    "Geometric score contribution": geometry.applied_score_shift ?? 0,
    "Ungraded reason": aiFinalGrade(event) === "Ungraded" ? verdictReason(event).text || analysis.verdict_reason_code || "Insufficient reliable evidence" : "",
    "Body Width Analysis": JSON.stringify(analysis.body_width || {}),
    "Body Width Threshold Configuration": JSON.stringify(analysis.body_width?.threshold_configuration || {}),
    "Source metadata": JSON.stringify(resultDatasets[resultsSource].metadata),
    "Complete fish event": JSON.stringify(event),
  };
  return {...record, ...flattenResultData(event, "record")};
}
function exportResultsCsv() {
  const records = selectedResultEvents().map(resultExportRecord);
  const headers = [...new Set(records.flatMap((record) => Object.keys(record)))];
  if (!headers.length) headers.push("Fish ID", "Final classification", "Complete fish event");
  const csvEscape = (value) => {
    let text = String(value ?? "");
    if (typeof value === "string" && (/^[\t\r\n]/.test(text) || /^[=+\-@]/.test(text.trimStart()))) text = "'" + text;
    return `"${text.replaceAll("\"", "\"\"")}"`;
  };
  const lines = [headers.map(csvEscape).join(","), ...records.map((record) => headers.map((field) => csvEscape(record[field])).join(","))];
  const blob = new Blob([`\ufeff${lines.join("\r\n")}`], {type: "text/csv;charset=utf-8"}); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `fish-inspection-${resultsSource}-${resultsFilter.toLowerCase().replaceAll(" ", "-")}.csv`; link.click(); URL.revokeObjectURL(link.href);
}
function resultReportHtml(rows = selectedResultEvents()) {
  const htmlEscape = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;");
  const table = (headers, values) => `<table><thead><tr>${headers.map((header) => `<th>${htmlEscape(header)}</th>`).join("")}</tr></thead><tbody>${values.map((row) => `<tr>${row.map((value) => `<td>${htmlEscape(value == null || value === "" ? "Not recorded" : value)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const jsonTable = (value) => table(["Recorded field", "Value"], Object.entries(flattenResultData(value)).map(([key, item]) => [key, typeof item === "string" ? item : String(item)]));
  const distribution = sessionGradeBuckets.map((grade) => [grade, rows.filter((event) => resultGrade(event) === grade).length]);
  const groups = sessionGradeBuckets.map((grade) => [grade, rows.filter((event) => resultGrade(event) === grade)]).filter(([, items]) => items.length);
  const cards = groups.map(([grade, items]) => `<section><h2>${htmlEscape(grade)} (${items.length})</h2>${items.map((event) => {
    const analysis = event.analysis || {}; const geometry = analysis.geometric_support || {};
    const scores = sessionGradeBuckets.filter((name) => name !== "Ungraded").map((name) => [name, geometry.original_scores?.[name] ?? "Not recorded", analysis.weighted_scores?.[name] ?? geometry.final_scores?.[name] ?? "Not recorded"]);
    const measurements = ["Whole Fish", "Body", "Head", "Tail"].map((region) => {
      const reading = measurementRegion(event, region);
      return `<h4>${htmlEscape(region)} ROI — ${htmlEscape(reading.status)}</h4>${jsonTable({bbox: reading.box || null, ...reading.reading})}`;
    }).join("");
    const detections = (event.parts || []).map((part) => [part.source_class_name || "Not recorded", part.region || part.part, part.grade, part.confidence ?? part.evidence_score, JSON.stringify(part.bbox || null)]);
    const gradingConfig = {...analysis.grading_config}; delete gradingConfig.body_width;
    return `<article><h3>${htmlEscape(event.fish_label || `Fish #${event.track_id ?? event.id ?? "?"}`)} · ${htmlEscape(resultGrade(event))} · Final support ${htmlEscape(scoreText(weightedFinalSupport(event)))}</h3><h4>A. Grading Evidence</h4>${table(["Evidence", "Value"], resultEvidenceRows(event))}${table(["Class", "Original weighted support", "Final combined support"], scores)}${detections.length ? table(["Model 2 label", "Region", "Class", "Confidence (0–1)", "Original bbox (px)"], detections) : "<p>Model 2 detections: Not Detected</p>"}<h4>B. Body Width and Geometric Analysis</h4>${table(["Measurement", "Value"], bodyWidthRows(event))}<h4>C. Image Features and Measurements</h4>${measurements}<h4>D. Final Grading Explanation</h4>${table(["Decision stage", "Result"], finalExplanationRows(event))}<h4>Model, source and threshold configuration</h4>${jsonTable({session_id: event.session_id || null, timestamp: event.timestamp || null, inspection_source: analysis.inspection_source || {}, traceability: analysis.traceability || {}, grading_config: gradingConfig, width_threshold_configuration: analysis.body_width?.threshold_configuration || {}})}</article>`;
  }).join("")}</section>`).join("");
  const metadata = resultDatasets[resultsSource].metadata;
  const dates = rows.map((event) => event.timestamp).filter(Boolean).sort();
  const dateRange = dates.length ? dates[0] === dates.at(-1) ? dates[0] : `${dates[0]} to ${dates.at(-1)}` : metadata.analyzed_at || "Not recorded";
  return `<!doctype html><html><head><meta charset="UTF-8"><title>Tamban Fish Inspection Report</title><style>@page{size:A4;margin:16mm 14mm;@bottom-right{content:"Page " counter(page) " of " counter(pages);font:9px Arial}}body{font:10px/1.45 Arial,sans-serif;color:#172b29;margin:0}h1{font-size:22px;color:#0e5a78;margin:0 0 8px}h2{font-size:16px;border-bottom:2px solid #137c9e;padding-bottom:5px;break-after:avoid}h3{font-size:13px;background:#edf8f4;padding:8px;break-after:avoid}h4{font-size:11px;margin:12px 0 5px;break-after:avoid}p{margin:5px 0}article+article{break-before:page}table{border-collapse:collapse;width:100%;table-layout:fixed;margin:5px 0 12px}thead{display:table-header-group}tr{break-inside:avoid}th,td{border:1px solid #d4dcd5;padding:5px;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}th{background:#f1f7f5}header{border-bottom:1px solid #d4dcd5;padding-bottom:12px}footer{font-size:9px;color:#68756d;margin-top:12px}@media screen{body{max-width:900px;padding:24px;margin:auto}}</style></head><body><header><h1>Tamban Fish Inspection Report</h1><p>Inspection source: ${htmlEscape(metadata.source_name || resultsSource)}</p><p>Inspection dates: ${htmlEscape(dateRange)}</p><p>Export filter: ${htmlEscape(resultsFilter)} · Unique fish: ${rows.length} · Generated: ${htmlEscape(new Date().toLocaleString())}</p></header><h2>Class distribution</h2>${table(["Final classification", "Unique fish"], distribution)}<h2>Grading methodology</h2><p>Model 1 locates each fish. Model 2 provides Body / Head / Tail classification evidence with original weights 50% / 30% / 20%. The recorded policy determines effective weights and acceptance safeguards. Validated Class C geometric support is bounded and applied once after weighted classification. Width is a bounding-box proxy; uncalibrated or unreliable width cannot contribute. Detection confidence, part confidence, weighted support and 0–10 geometric points are separate quantities.</p>${cards}<footer>Rectangular ROI colour measurements are diagnostics and may include background; no calibrated physical size or fish mask is implied. Original AI verdicts remain separate from operator reviews.</footer></body></html>`;
}
function exportResultsPdf() {
  const report = window.open("", "_blank"); if (!report) return;
  report.document.write(resultReportHtml()); report.document.close(); report.focus(); setTimeout(() => report.print(), 250);
}

function manualChoiceForDisplay(value) { return String(value || "").replace(/^Class\s+/i, ""); }
function appendManualReviewPanel(container, event) {
  const currentManual = manualGrade(event); if (!needsReview(event) && !currentManual) return;
  const panel = document.createElement("section"); panel.className = "manual-review-panel";
  const heading = document.createElement("h3"); heading.textContent = "Manual review"; const original = document.createElement("p");
  original.textContent = `Session: ${event.session_id || "current session"}. Original AI verdict: ${aiFinalGrade(event)}. Weighted final support: ${scoreText(weightedFinalSupport(event))}. This evidence is retained when a manual grade is recorded.`;
  const controls = document.createElement("div"); controls.className = "manual-review-controls"; const label = document.createElement("label"); label.textContent = "Manual final grade";
  const select = document.createElement("select"); select.setAttribute("aria-label", "Manual final grade"); const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Select an operator grade"; select.append(empty);
  MANUAL_GRADE_CHOICES.forEach((grade) => { const option = document.createElement("option"); option.value = grade; option.textContent = grade === "Rejected" ? "Rejected" : `Class ${grade}`; option.selected = manualChoiceForDisplay(currentManual) === grade; select.append(option); });
  label.append(select); const save = document.createElement("button"); save.type = "button"; save.className = "button primary"; save.textContent = currentManual ? "Update manual grade" : "Record manual grade"; save.disabled = !select.value;
  const message = document.createElement("p"); message.className = "manual-review-message"; if (currentManual) message.textContent = `Manual final grade currently recorded as ${currentManual}.`;
  select.addEventListener("change", () => { save.disabled = !select.value; message.textContent = ""; message.classList.remove("error"); });
  const reviewerLabel = document.createElement("label"); reviewerLabel.textContent = "Reviewer (optional)"; const reviewer = document.createElement("input"); reviewer.type = "text"; reviewer.maxLength = 120; reviewer.value = event.reviewer || ""; reviewerLabel.append(reviewer);
  save.addEventListener("click", () => submitManualReview(event, select.value, save, message, reviewer.value)); controls.append(label, reviewerLabel, save);
  if (currentManual) { const clear = document.createElement("button"); clear.type = "button"; clear.className = "button quiet"; clear.textContent = "Clear manual grade"; clear.addEventListener("click", () => submitManualReview(event, null, clear, message, reviewer.value)); controls.append(clear); }
  panel.append(heading, original, controls, message); container.append(panel);
}
async function submitManualReview(event, selectedGrade, button, message, reviewer = "") {
  if ((selectedGrade !== null && !selectedGrade) || event?.track_id == null) return;
  button.disabled = true; message.classList.remove("error"); message.textContent = "Saving manual final grade...";
  try {
    const request = { manual_grade: selectedGrade, reviewer: reviewer.trim() || null }; if (event.session_id) request.session_id = event.session_id;
    const response = await fetch(`/api/reviews/${encodeURIComponent(String(event.track_id))}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
    const payload = await response.json().catch(() => ({})); if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    const updated = payload.item && typeof payload.item === "object" ? payload.item : null;
    message.textContent = selectedGrade === null ? "Manual grade cleared. The original AI verdict is unchanged." : "Manual final grade saved. The original AI verdict is unchanged.";
    if (updated) openHistoryAnalysis(updated); await getStatus();
    if (selectedView === "history") await loadHistory();
    else if (selectedView === "review") await loadReviewQueue();
  } catch (error) { message.classList.add("error"); message.textContent = error instanceof Error ? error.message : "Manual review could not be saved."; button.disabled = false; }
}
function openHistoryAnalysis(event) {
  let dialog = $("history-analysis-dialog");
  if (!dialog) { dialog = document.createElement("dialog"); dialog.id = "history-analysis-dialog"; dialog.className = "history-analysis-dialog"; document.body.append(dialog); }
  dialog.replaceChildren(); const close = document.createElement("button"); close.className = "icon-button"; close.type = "button"; close.textContent = "x"; close.setAttribute("aria-label", "Close analysis"); close.addEventListener("click", () => dialog.close());
  const title = document.createElement("h2"); title.textContent = `${event.fish_label || `Fish #${event.track_id}`} full analysis`; const content = document.createElement("div"); appendResultCard(content, {...event, _inspection_source: "history"}); content.querySelector("details")?.setAttribute("open", ""); appendManualReviewPanel(content, event); dialog.append(close, title, content);
  title.id = "history-analysis-title";
  dialog.setAttribute("aria-labelledby", title.id);
  if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
}

function activeModel2Id(data = latestStatus) {
  return data?.active_model2_id || data?.model_info?.quality?.model_id || "";
}
function modelCanGrade(model) {
  return Boolean(model?.is_compatible_grading) && model?.availability === "available";
}
function setModelSelectorStatus(message, isError = false) {
  if (elements.model2SelectorStatus.textContent !== message) elements.model2SelectorStatus.textContent = message;
  if (elements.model2SelectorStatus.classList.contains("error") !== isError) elements.model2SelectorStatus.classList.toggle("error", isError);
}
function modelOptionLabel(model) {
  const suffix = [model.is_default_model2 ? "default" : "", model.is_loaded ? "loaded" : "", modelCanGrade(model) ? "" : "unavailable"].filter(Boolean).join(", ");
  return `${model.name || model.display_name || model.id}${suffix ? ` (${suffix})` : ""}`;
}
function renderModelSelectorOptions(activeId = activeModel2Id()) {
  const selects = [elements.model2Selector, elements.liveModelSelector].filter(Boolean);
  selects.forEach((select) => select.replaceChildren());
  if (!modelSelectorModels.length) {
    const option = document.createElement("option"); option.textContent = "No requested Model 2 checkpoints found"; option.disabled = true; option.selected = true;
    selects.forEach((select) => { select.append(option.cloneNode(true)); select.disabled = true; });
    return;
  }
  const selectedId = modelSelectorModels.some((model) => model.id === activeId)
    ? activeId
    : modelSelectorModels[0].id;
  selects.forEach((select) => {
    modelSelectorModels.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = modelOptionLabel(model);
      option.disabled = !modelCanGrade(model);
      option.selected = model.id === selectedId;
      select.append(option);
    });
    select.value = selectedId;
  });
}
function syncModelSelector(data = latestStatus) {
  const selects = [elements.model2Selector, elements.liveModelSelector].filter(Boolean);
  if (modelSelectorChanging) {
    selects.forEach((select) => { select.disabled = true; select.title = "The selected model is loading."; });
    return;
  }
  if (!modelSelectorModels.length) {
    selects.forEach((select) => { select.disabled = true; select.title = "The requested Model 2 checkpoints are unavailable."; });
    return;
  }
  const activeId = activeModel2Id(data);
  selects.forEach((select) => {
    if (activeId && [...select.options].some((option) => option.value === activeId)) select.value = activeId;
  });
  const inspectionActive = Boolean(data?.policy_settings_locked) || ["starting", "running", "stopping"].includes(data?.inspection_status);
  selects.forEach((select) => {
    select.disabled = modelSelectorLoading || inspectionActive;
    select.title = inspectionActive ? "Stop inspection before changing Model 2." : "";
  });
  const activeModel = modelSelectorModels.find((model) => model.id === activeId);
  const quality = data?.model_info?.quality || {};
  const readiness = quality.is_loaded === true ? "Loaded and ready." : quality.is_loaded === false ? "Not loaded." : "";
  const blocked = modelSelectorModels.filter((model) => !modelCanGrade(model));
  const blockedNote = blocked.length
    ? ` ${blocked.map((model) => `${model.display_name || model.id} is unavailable: ${model.incompatibility_reason || "not compatible with the grading workflow"}.`).join(" ")}`
    : "";
  const lockNote = inspectionActive ? " Stop inspection before changing models." : "";
  setModelSelectorStatus(`${activeModel?.display_name || data?.active_model2_name || "Active Model 2"} is selected. ${readiness}${lockNote}${blockedNote}`.trim());
}
async function loadModelSelector() {
  if (modelSelectorLoading || modelSelectorModels.length) return;
  let selectorStatus = null;
  modelSelectorLoading = true;
  elements.model2Selector.disabled = true;
  if (elements.liveModelSelector) elements.liveModelSelector.disabled = true;
  setModelSelectorStatus("Loading the requested Model 2 checkpoints.");
  try {
    const response = await fetch("/api/models", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    const registryModels = Array.isArray(payload.models) ? payload.models : [];
    modelSelectorModels = MODEL2_SELECTOR_IDS
      .map((modelId) => registryModels.find((model) => model?.id === modelId))
      .filter(Boolean);
    if (!modelSelectorModels.length) throw new Error("None of the requested Model 2 checkpoints are registered.");
    const activeId = payload.active_model2_id || activeModel2Id();
    renderModelSelectorOptions(activeId);
    selectorStatus = { ...(latestStatus || {}), active_model2_id: activeId };
    syncModelSelector(selectorStatus);
  } catch (error) {
    modelSelectorModels = [];
    renderModelSelectorOptions();
    setModelSelectorStatus(error instanceof Error ? `Model list unavailable: ${error.message}` : "Model list unavailable.", true);
  } finally {
    modelSelectorLoading = false;
    if (modelSelectorModels.length) syncModelSelector(selectorStatus || latestStatus);
  }
}
async function selectModel2() {
  if (modelSelectorChanging) return;
  const selectedId = elements.model2Selector.value;
  const activeId = activeModel2Id();
  const selectedModel = modelSelectorModels.find((model) => model.id === selectedId);
  if (!selectedModel || !modelCanGrade(selectedModel) || selectedId === activeId) {
    syncModelSelector(latestStatus);
    return;
  }
  modelSelectorChanging = true;
  elements.model2Selector.disabled = true;
  setModelSelectorStatus(`Loading ${selectedModel.display_name || selectedId}.`);
  try {
    const response = await fetch("/api/models/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: selectedId }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    modelSelectorChanging = false;
    modelSelectorModels = modelSelectorModels.map((model) => ({ ...model, is_loaded: model.id === payload.active_model2_id }));
    renderModelSelectorOptions(payload.active_model2_id);
    render(payload);
    setModelSelectorStatus(`${payload.active_model2_name || selectedModel.display_name || selectedId} is now active. Loaded weights will be used for live inspection and media analysis.`);
  } catch (error) {
    modelSelectorChanging = false;
    syncModelSelector(latestStatus);
    setModelSelectorStatus(error instanceof Error ? `Model was not changed: ${error.message}` : "Model was not changed.", true);
  } finally {
    modelSelectorChanging = false;
  }
}

function renderModel(data) {
  const preview = data.runtime_mode === "part_preview";
  const intro = $("view-model").querySelector(".view-intro");
  intro.querySelector("h2").textContent = preview ? "Research part-model status" : "Local two-model status";
  intro.querySelector("p:last-child").textContent = preview
    ? "The preview model shows raw part evidence. Whole-fish tracking, counting, and final grading are disabled."
    : "Model 1 locates and tracks fish. Model 2 supplies head, body, and tail evidence for grading.";
  elements.detectorModelName.closest(".model-card").querySelector(".eyebrow").textContent = preview ? "RESEARCH · PART MODEL" : "MODEL 1 · FISH DETECTION";
  const detector = data.model_info?.detector || {}; const segmenter = data.model_info?.quality || {}; const diagnostic = segmenter.diagnostics || {};
  elements.detectorModelName.textContent = detector.name || "Fish detector"; elements.detectorModelStatus.textContent = titleCase(detector.status); elements.detectorCheckpoint.textContent = detector.checkpoint_resolved ? "Resolved" : "Unresolved"; elements.detectorDevice.textContent = detector.device || "—"; elements.detectorThreshold.textContent = formatPercent(Number(detector.confidence_threshold) * 100);
  syncModelSelector(data);
  elements.segmenterModelName.textContent = segmenter.name || "Quality Model"; elements.segmenterModelStatus.textContent = titleCase(segmenter.status); elements.segmenterCheckpoint.textContent = segmenter.checkpoint_resolved ? "Resolved" : "Unresolved"; elements.segmenterDevice.textContent = segmenter.device || "—"; elements.segmenterInference.textContent = diagnostic.last_inference_ms == null ? "No measurement" : `${diagnostic.last_inference_ms} ms`;
}

function diagnosticsRow(label, value) {
  const row = document.createElement("div"); const term = document.createElement("dt"); const detail = document.createElement("dd");
  term.textContent = label; detail.textContent = value == null || value === "" ? "—" : String(value); row.append(term, detail); return row;
}
function renderRuntimeDiagnostics(data) {
  const diagnostics = data.runtime_diagnostics || {}; const performance = diagnostics.performance || {}; const timings = performance.timings || {}; const queue = diagnostics.frame_queue || {}; const persistenceQueue = diagnostics.event_persistence_queue || {};
  const measured = (value) => value == null || value === "" ? "Not measured" : String(value);
  const rate = (value) => value == null ? "Not measured" : `${Number(value).toFixed(1)} FPS`;
  const timing = (name) => {
    const sample = timings[name];
    return sample?.p50 == null ? "Not measured" : `${sample.p50} / ${sample.p95} ms (${sample.count} samples)`;
  };
  const enabled = Boolean(diagnostics.enabled); elements.debugRuntimeEnabled.checked = enabled; elements.debugPause.disabled = !enabled; elements.debugPause.textContent = diagnostics.paused ? "Resume inspection" : "Pause on current frame";
  elements.runtimeDiagnosticsNote.textContent = enabled
    ? "Debug mode is bounded and research-only. Raw candidates and saved crops do not change production predictions, grading, or history."
    : performance.recording_enabled === false
      ? "Runtime sample recording is disabled for an overhead experiment. Debug capture is off."
      : "Clean runtime counters remain active. Debug capture changes candidate collection and saves research artifacts; leave it off for baseline measurements.";
  elements.runtimeDiagnosticsValues.replaceChildren(
    diagnosticsRow("Camera", measured(data.camera_status)),
    diagnosticsRow("Model 1 / device", `${measured(data.model_info?.detector?.name)} / ${measured(data.model_info?.detector?.device)}`),
    diagnosticsRow("Model 2 / device", `${measured(data.model_info?.quality?.name)} / ${measured(data.model_info?.quality?.device)}`),
    diagnosticsRow("CUDA / FP16", `${data.device_report?.pytorch_cuda_available ? "available" : "CPU fallback"} / ${data.device_report?.model1_compute?.fp16_enabled || data.device_report?.model2_compute?.fp16_enabled ? "enabled" : "off"}`),
    diagnosticsRow("Capture FPS", rate(performance.calls_per_second?.camera_capture)),
    diagnosticsRow("AI processing FPS", rate(performance.processing_fps ?? performance.calls_per_second?.processed_frame)),
    diagnosticsRow("This browser's MJPEG image-load FPS", browserPreviewImageLoadText()),
    diagnosticsRow("Capture-to-display latency", "Not measured"),
    diagnosticsRow("Dropped stale frames", measured(queue.dropped_frames)), diagnosticsRow("Queue depth / capacity", `${measured(queue.depth)} / ${measured(queue.capacity)}`),
    diagnosticsRow("Capture p50 / p95", timing("camera_capture")),
    diagnosticsRow("Frame age at processing p50 / p95", timing("capture_to_process")),
    diagnosticsRow("Capture-to-server-publish p50 / p95", timing("capture_to_publish")),
    diagnosticsRow("Model 1 host time p50 / p95", timing("model1_inference")),
    diagnosticsRow("Model 2 host time p50 / p95", timing("model2_inference")),
    diagnosticsRow("ROI extraction p50 / p95", timing("roi_extraction")),
    diagnosticsRow("Association p50 / p95", timing("association")),
    diagnosticsRow("Part assignment p50 / p95", timing("part_assignment")),
    diagnosticsRow("Visual evidence preparation p50 / p95", timing("hsv")),
    diagnosticsRow("Grading p50 / p95", timing("grading_engine")),
    diagnosticsRow("Event tracking p50 / p95", timing("event_tracking")),
    diagnosticsRow("First detection to virtual decision p50 / p95", timing("first_detection_to_decision")),
    diagnosticsRow("Event persistence worker p50 / p95", timing("event_persistence")),
    diagnosticsRow("Event write queue (pending / capacity)", `${measured(persistenceQueue.pending)} / ${measured(persistenceQueue.capacity)}`),
    diagnosticsRow("Event queue accepted / completed", `${measured(persistenceQueue.accepted)} / ${measured(persistenceQueue.completed)}`),
    diagnosticsRow("Event queue backpressure", `${measured(persistenceQueue.backpressure_waits)} waits / ${measured(persistenceQueue.backpressure_wait_ms)} ms total`),
    diagnosticsRow("Event queue health", persistenceQueue.failed ? `Failure: ${persistenceQueue.failure?.message || "unknown error"}` : !persistenceQueue.accepting ? "Stopping" : persistenceQueue.worker_alive ? "Ready" : "Stopped"),
    diagnosticsRow("Overlay rendering p50 / p95", timing("overlay_rendering")),
    diagnosticsRow("Total processing p50 / p95", timing("total_processing")),
    diagnosticsRow("Model 2 calls / active fish / mode", `${measured(performance.counters?.model2)} / ${measured(diagnostics.active_tracks)} / ${measured(diagnostics.quality_inference_mode)}`),
    diagnosticsRow("Timing scope", "Host durations; GPU work may be asynchronous. Some stages overlap."),
    diagnosticsRow("JPEG p50 / p95", timing("jpeg_encoding")),
    diagnosticsRow("MJPEG dispatch samples / s", rate(performance.calls_per_second?.mjpeg_dispatch)),
    diagnosticsRow("MJPEG generator pacing p50 / p95", timing("mjpeg_dispatch")),
    diagnosticsRow("Frontend DOM render p50 / p95", timing("frontend_render")),
    diagnosticsRow("Telemetry recording overhead", "Not measured"),
    diagnosticsRow("Model 2 raw / associated / rejected / unassigned", enabled ? `${measured(diagnostics.model2_raw_candidates)} / ${measured(diagnostics.model2_associated_parts)} / ${measured(diagnostics.model2_rejected_candidates)} / ${measured(diagnostics.model2_unassigned_candidates)}` : "Not measured (debug capture off)"),
  );
  elements.hardNegativeList.replaceChildren(); const records = Array.isArray(diagnostics.hard_negative_records) ? diagnostics.hard_negative_records : [];
  if (!records.length) { elements.hardNegativeList.textContent = enabled ? "No bounded candidates saved yet." : "Enable diagnostics to create bounded research-only candidates."; return; }
  records.slice(-8).reverse().forEach((record) => {
    const row = document.createElement("div"); row.className = "verdict-summary-row";
    const text = document.createElement("span"); text.textContent = `Frame ${record.frame_number} · Fish #${record.track_id} · detector ${formatPercent(Number(record.confidence) * 100)} · Model 2 compatible: ${record.model2_compatible_part_evidence ? "yes" : "no"}`;
    row.append(text);
    if (record.operator_label === "NOT_FISH") row.append(Object.assign(document.createElement("strong"), { textContent: "NOT_FISH" }));
    else { const mark = document.createElement("button"); mark.className = "text-button"; mark.type = "button"; mark.textContent = "Mark NOT_FISH"; mark.addEventListener("click", () => markHardNegative(record.capture_id)); row.append(mark); }
    elements.hardNegativeList.append(row);
  });
}
async function postRuntimeDiagnostics(payload) {
  try { const response = await fetch("/api/debug/runtime", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`); render(data); }
  catch (error) { elements.alert.classList.remove("hidden"); elements.alertTitle.textContent = "Runtime diagnostics unavailable"; elements.alertCopy.textContent = "The debug action was not applied."; elements.alertDetails.textContent = error instanceof Error ? error.message : "Unknown error."; }
}
async function markHardNegative(captureId) {
  if (!captureId) return;
  try { const response = await fetch(`/api/debug/hard-negatives/${encodeURIComponent(String(captureId))}/not-fish`, { method: "POST" }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`); await getStatus(); }
  catch (error) { elements.alert.classList.remove("hidden"); elements.alertTitle.textContent = "NOT_FISH label not saved"; elements.alertCopy.textContent = "The production prediction was not changed."; elements.alertDetails.textContent = error instanceof Error ? error.message : "Unknown error."; }
}

function renderGradingSettings(data) {
  let section = $("grading-settings-section");
  if (!section) {
    section = document.createElement("section");
    section.id = "grading-settings-section";
    section.className = "settings-section";
    section.innerHTML = "<h3>Grading policy</h3><p class=\"muted\">Read-only policy snapshot. Weighted support is not a calibrated probability.</p><dl class=\"settings-list\"><div><dt>Mode</dt><dd id=\"settings-grading-mode\">—</dd></div><div><dt>Part evidence threshold</dt><dd id=\"settings-part-evidence-threshold\">—</dd></div><div><dt>Final verdict threshold</dt><dd id=\"settings-final-verdict-threshold\">—</dd></div><div><dt>Minimum grade margin</dt><dd id=\"settings-grade-margin\">—</dd></div><div><dt>Required coverage</dt><dd id=\"settings-coverage\">—</dd></div><div><dt>Original weights</dt><dd id=\"settings-part-weights\">—</dd></div></dl>";
    const cameraSection = [...elements.settingsDrawer.querySelectorAll(".settings-section")]
      .find((candidate) => candidate.querySelector("h3")?.textContent?.trim() === "Camera");
    if (cameraSection) cameraSection.before(section); else elements.settingsDrawer.append(section);
  }
  const rules = data.grading_rules && typeof data.grading_rules === "object" ? data.grading_rules : {};
  const text = (id, value) => { const target = $(id); if (target) target.textContent = value; };
  const fraction = (value) => Number.isFinite(Number(value)) ? formatPercent(Number(value) * 100) : "—";
  const weights = rules.part_weights && typeof rules.part_weights === "object" ? rules.part_weights : {};
  text("settings-grading-mode", rules.grading_mode || "No production policy");
  text("settings-part-evidence-threshold", fraction(rules.minimum_part_confidence));
  text("settings-final-verdict-threshold", fraction(rules.final_verdict_threshold));
  text("settings-grade-margin", fraction(rules.minimum_grade_margin));
  text("settings-coverage", fraction(rules.minimum_original_weight_coverage));
  text("settings-part-weights", `Body ${fraction(weights.Body)} / Head ${fraction(weights.Head)} / Tail ${fraction(weights.Tail)}`);
}

function syncSettings(data) {
  const threshold = Math.round(Number(data.detection_confidence_threshold || 0) * 100);
  elements.slider.value = String(threshold); elements.settingsThreshold.textContent = `${threshold}%`;
  const qualityThreshold = Math.round(Number(data.quality_confidence_threshold || 0) * 100);
  elements.qualitySlider.value = String(qualityThreshold); elements.settingsQualityThreshold.textContent = `${qualityThreshold}%`;
  const qualityRuntime = data.model_info?.quality || {};
  elements.settingsQualityMode.textContent = qualityRuntime.quality_inference_mode || qualityRuntime.diagnostics?.quality_inference_mode || "—";
  const interval = Number(qualityRuntime.quality_interval);
  elements.settingsQualityInterval.textContent = Number.isFinite(interval) && interval > 0 ? `Every ${interval} processed frame${interval === 1 ? "" : "s"}` : "—";
  const padding = Number(qualityRuntime.roi_padding ?? qualityRuntime.diagnostics?.roi_padding);
  elements.settingsQualityRoiPadding.textContent = Number.isFinite(padding) ? `${padding} px` : "—";
  const policyLocked = Boolean(data.policy_settings_locked ?? ["starting", "running", "stopping"].includes(data.inspection_status));
  [elements.slider, elements.confidenceMinus, elements.confidencePlus, elements.resetConfidence, elements.qualitySlider, elements.qualityConfidenceMinus, elements.qualityConfidencePlus, elements.resetQualityConfidence]
    .forEach((control) => { if (control) { control.disabled = policyLocked; control.title = policyLocked ? "Stop inspection before changing this policy setting." : ""; } });
  const display = data.display_settings || {};
  Object.entries(overlayControls).forEach(([name, controls]) => controls.forEach((control) => { if (control) control.checked = Boolean(display[name]); }));
  renderGradingSettings(data);
}

function render(data) {
  const renderStarted = performance.now(); latestStatus = data; defaultConfidence = Number(data.default_confidence_threshold ?? defaultConfidence); defaultQualityConfidence = Number(data.default_quality_confidence_threshold ?? defaultQualityConfidence);
  const alertKey = JSON.stringify([data.model_status, data.segmenter_status, data.inspection_status, data.runtime_mode, data.message, data.segmenter_message, data.upload_analysis_available]);
  if (alertKey !== alertRenderKey) { renderAlert(data); alertRenderKey = alertKey; }
  const previewImageLoadFps = browserPreviewImageLoadFps();
  const cameraKey = JSON.stringify([data.inspection_status, data.camera_status, data.model_status, data.segmenter_status, data.runtime_mode, data.model_info?.quality?.status, data.model_info?.detector?.device, data.fps, data.frame_size, data.message, data.raw_preview_available, data.upload_analysis_available, Boolean(selectedUpload), uploadInFlight, streamReady, streamAttached, previewImageLoadFps == null ? null : previewImageLoadFps.toFixed(1), controlRequestInFlight]);
  if (cameraKey !== cameraRenderKey) { renderCamera(data); cameraRenderKey = cameraKey; }
  if (selectedView === "live") {
    renderLatest(data); renderKpis(data); renderFeatureCounters(data); renderResultsDashboard([...(data.active_tracks || []).filter((track) => track.finalized_state !== "counted"), ...(data.recent_history || [])], {metadata: {source_name: "Live inspection session", model_info: data.model_info, session_id: data.durable_session?.session_id}});
    Object.entries(overlayControls).forEach(([name, controls]) => controls.forEach((control) => { if (control) control.checked = Boolean(data.display_settings?.[name]); }));
    if ($("analytics-disclosure").open && data.analytics !== renderedAnalytics) {
      renderAnalytics(data.analytics); renderedAnalytics = data.analytics;
    }
    if ($("advanced-diagnostics").open) renderRuntimeDiagnostics(data);
  }
  if (selectedView === "model") renderModel(data);
  if (activePanel === elements.settingsDrawer) syncSettings(data);
  if (data.runtime_diagnostics?.enabled) fetch("/api/debug/frontend-metrics", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ render_ms: performance.now() - renderStarted }) }).catch(() => {});
  const reviewCount = Number(data.review_queue_count || 0);
  $("review-count").textContent = String(reviewCount);
  $("review-count").classList.toggle("hidden", reviewCount === 0);
  if (data.runtime_mode === "part_preview") {
    if (resultsSource === "live") elements.resultsSummary.textContent = "Fish counting is disabled in part preview.";
    $("analytics-disclosure").classList.add("hidden");
    $("analytics-section").classList.add("hidden");
    elements.featureCounterGrid.closest(".feature-section").classList.add("hidden");
  } else {
    $("analytics-disclosure").classList.remove("hidden");
    $("analytics-section").classList.remove("hidden");
    elements.featureCounterGrid.closest(".feature-section").classList.remove("hidden");
  }
  const dataRevision = analyticsVersion(data);
  if (selectedView === "history" && historyLoadedRevision !== dataRevision) loadHistory();
  else if (selectedView === "review" && reviewLoadedRevision !== dataRevision) loadReviewQueue();
}

function renderBackendUnavailable() {
  elements.alert.classList.remove("hidden"); elements.alertTitle.textContent = "Connection lost"; elements.alertCopy.textContent = "Cannot reach the local backend. Displayed results may be out of date."; elements.alertDetails.textContent = "Check that the local server is running. The dashboard will reconnect automatically.";
  setCompactStatus($("connection-pill"), "Server", "Offline", "error");
  setCompactStatus(elements.cameraPill, "Camera", "Unknown", "neutral");
  setCompactStatus(elements.modelPill, "Models", "Unknown", "neutral");
  elements.liveBadge.textContent = "CONNECTION LOST";
  elements.liveBadge.className = "live-badge error";
  detachStream();
  elements.placeholder.classList.remove("hidden");
  elements.placeholderTitle.textContent = "Waiting for the local server";
  elements.placeholderCopy.textContent = "The feed will reconnect when the backend is available.";
  [elements.start, elements.emptyStart, elements.reset, elements.analyze].forEach((button) => { button.disabled = true; });
}
async function getStatus() {
  // A slow response must never overtake the next poll and redraw stale UI.
  if (!lanReady || (lanEnabled && !lanCsrf) || document.hidden || statusRequestInFlight || controlRequestInFlight) return;
  statusRequestInFlight = true;
  const controller = new AbortController(); statusController = controller;
  const timeout = setTimeout(() => controller.abort(), 10000);
  const revision = controlRevision;
  try {
    const response = await fetch("/api/status/live", { cache: "no-store", signal: controller.signal });
    if (response.status === 401 && lanEnabled) { lanCsrf = null; showLanLogin(); }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (revision === controlRevision && !controlRequestInFlight) {
      const key = analyticsVersion(data);
      if (key === analyticsSnapshotKey) {
        data.analytics = analyticsSnapshot;
        data.feature_counters = analyticsSnapshot?.feature_counts || {};
      }
      render(data);
      if (key !== analyticsSnapshotKey) refreshAnalytics(key);
    }
  } catch (error) {
    if (!document.hidden && revision === controlRevision && !controlRequestInFlight) { cameraRenderKey = null; alertRenderKey = null; renderBackendUnavailable(); }
  } finally {
    clearTimeout(timeout); if (statusController === controller) statusController = null;
    statusRequestInFlight = false;
  }
}
function analyticsVersion(data) {
  const session = data?.durable_session?.session_id ?? null;
  // The legacy in-memory fallback has no SQLite revision before a session exists.
  return JSON.stringify([session, data?.event_revision ?? null, session ? null : data?.recent_history || []]);
}
async function refreshAnalytics(key) {
  if (document.hidden || analyticsRequestInFlight) return;
  analyticsRequestInFlight = true;
  const controller = new AbortController(); analyticsController = controller;
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch("/api/analytics?range_name=current_session", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const session = latestStatus?.durable_session?.session_id ?? null;
    if (analyticsVersion(latestStatus) !== key || (data.session_id ?? null) !== session ||
        (data.event_revision ?? null) !== (latestStatus?.event_revision ?? null)) return;
    analyticsSnapshot = data;
    analyticsSnapshotKey = key;
    render({ ...latestStatus, analytics: data, feature_counters: data.feature_counts || {} });
  } catch (_) {
    // Retry on the next status poll without replacing current live data.
  } finally {
    clearTimeout(timeout);
    if (analyticsController === controller) analyticsController = null;
    analyticsRequestInFlight = false;
  }
}
async function postControl(path) {
  if (modelSelectorChanging) {
    const feedback = $("control-feedback");
    feedback.textContent = "Wait for the selected Model 2 checkpoint to finish loading.";
    feedback.classList.remove("hidden");
    feedback.classList.remove("error");
    return;
  }
  if (controlRequestInFlight) return;
  statusController?.abort();
  controlRequestInFlight = true;
  controlRevision += 1;
  const feedback = $("control-feedback");
  const activity = path.endsWith("/start") ? "Starting inspection…" : path.endsWith("/stop") ? "Stopping inspection…" : "Resetting session…";
  feedback.textContent = activity;
  feedback.classList.remove("hidden");
  feedback.classList.remove("error");
  elements.inspectionState.setAttribute("aria-busy", "true");
  [elements.start, elements.emptyStart, elements.reset].forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(path, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    controlRequestInFlight = false;
    render(data);
    feedback.textContent = data.inspection_status === "errored" ? (data.message || "Inspection needs attention.") : path.endsWith("/reset") ? "New session ready. Previous records remain in local history." : path.endsWith("/stop") ? "" : "Inspection requested. Waiting for the camera.";
    feedback.classList.toggle("hidden", !feedback.textContent);
    feedback.classList.toggle("error", data.inspection_status === "errored");
  } catch (error) {
    feedback.textContent = error instanceof Error ? error.message : "Inspection request failed.";
    feedback.classList.remove("hidden");
    feedback.classList.add("error");
    controlRequestInFlight = false;
    await getStatus();
  } finally {
    controlRequestInFlight = false;
    elements.inspectionState.removeAttribute("aria-busy");
  }
}
async function postSettings(payload) {
  try { const response = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`); render(data); }
  catch (error) { elements.alert.classList.remove("hidden"); elements.alertTitle.textContent = "Settings not applied"; elements.alertCopy.textContent = "The active configuration could not be updated."; elements.alertDetails.textContent = error instanceof Error ? error.message : "Unknown settings error."; }
}

function showView(view) {
  if (!viewMeta[view]) return;
  if (selectedView !== view) {
    historyController?.abort(); reviewController?.abort();
    historyRequestVersion++; reviewRequestVersion++; historyRequestKey = null; reviewRequestKey = null;
  }
  selectedView = view;
  Object.keys(viewMeta).forEach((name) => $("view-" + name).classList.toggle("hidden", name !== view));
  const [title, subtitle] = viewMeta[view]; elements.pageTitle.textContent = title; elements.pageSubtitle.textContent = subtitle;
  document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (view === "history") { loadHistorySessions(); loadHistory(true); }
  if (view === "review") loadReviewQueue(true);
  if (view === "model") void loadModelSelector();
  if (latestStatus) render(latestStatus);
  window.scrollTo({ top: 0, behavior: motionPreference() });
}
function motionPreference() { return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"; }
function updateScrim() {
  const uploadOpen = !elements.uploadWorkspace.classList.contains("hidden");
  const anyOpen = elements.settingsDrawer.classList.contains("open") || elements.cameraCalibrationDrawer.classList.contains("open") || !elements.exportModal.classList.contains("hidden") || uploadOpen;
  elements.scrim.classList.toggle("hidden", !anyOpen);
  elements.shell.inert = anyOpen && !uploadOpen;
  document.body.classList.toggle("panel-open", anyOpen);
}
function openPanel(panel) {
  if (!activePanel) panelTrigger = document.activeElement;
  [elements.settingsDrawer, elements.cameraCalibrationDrawer, elements.exportModal, elements.uploadWorkspace].forEach((candidate) => {
    const selected = candidate === panel;
    candidate.inert = !selected;
    candidate.setAttribute("aria-hidden", String(!selected));
    if (candidate === elements.exportModal || candidate === elements.uploadWorkspace) {
      candidate.classList.toggle("hidden", !selected);
      candidate.classList.toggle("open", selected);
    }
    else candidate.classList.toggle("open", selected);
  });
  activePanel = panel;
  updateScrim();
  (panel.querySelector("button:not(:disabled)") || panel).focus();
}
function closePanel(panel) {
  if (panel !== activePanel) return;
  if (panel === elements.uploadWorkspace && uploadInFlight) return;
  panel.classList.remove("open");
  if (panel === elements.exportModal || panel === elements.uploadWorkspace) panel.classList.add("hidden");
  panel.inert = true;
  panel.setAttribute("aria-hidden", "true");
  activePanel = null;
  updateScrim();
  if (panel === elements.uploadWorkspace) {
    mountResultsDashboard(false);
    resetUploadWorkspace();
    elements.uploadMode.setAttribute("aria-expanded", "false");
    elements.uploadMode.textContent = "Analyze Media";
  }
  panelTrigger?.focus();
}
function openSettings() { if (latestStatus) syncSettings(latestStatus); openPanel(elements.settingsDrawer); }
function closeSettings() { closePanel(elements.settingsDrawer); }
function openExport() { syncExportRangeControls(); if (!exportSessionsLoading) void loadExportSessions(); openPanel(elements.exportModal); }
function closeExport() { closePanel(elements.exportModal); }
function openCameraCalibration() { openPanel(elements.cameraCalibrationDrawer); loadCameraCalibration(); }
function closeCameraCalibration() { closePanel(elements.cameraCalibrationDrawer); }
document.addEventListener("keydown", (event) => {
  if (!activePanel) return;
  if (event.key === "Escape") { event.preventDefault(); closePanel(activePanel); return; }
  if (event.key !== "Tab") return;
  const focusable = [...activePanel.querySelectorAll('button, input, select, summary, a[href], [tabindex="0"]')]
    .filter((control) => !control.disabled && control.getClientRects().length && !control.closest("[inert]"));
  const first = focusable[0], last = focusable.at(-1);
  if (!first) { event.preventDefault(); activePanel.focus(); }
  else if (event.shiftKey && (document.activeElement === first || !activePanel.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !activePanel.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
});

function cameraNumber(value) { return value == null || Number.isNaN(Number(value)) ? "-" : String(Number(value)); }
function setCameraCalibrationMessage(message, error = false) { elements.cameraCalibrationMessage.textContent = message; elements.cameraCalibrationMessage.classList.toggle("error", error); }
function cameraEditable(status) { return Boolean(status?.available && status?.calibration_mode && !status?.locked); }
function fillCameraField(input, value) { if (input && !input.value.trim() && value != null) input.value = String(value); }
function researchInstallationPayload() {
  return {
    device_identity: elements.cameraInstallationDeviceIdentity.value.trim(),
    camera_height: elements.cameraInstallationHeight.value.trim(),
    camera_angle: elements.cameraInstallationAngle.value.trim(),
    conveyor_position: elements.cameraInstallationConveyor.value.trim(),
    lighting_position: elements.cameraInstallationLighting.value.trim(),
  };
}

function renderCameraControls(status) {
  const properties = status?.capabilities?.properties || {};
  const actual = status?.actual || {};
  const requestedAutomatic = status?.requested_automatic || {};
  const editable = cameraEditable(status);
  elements.cameraControlList.replaceChildren();
  if (!Object.keys(properties).length) {
    const note = document.createElement("p"); note.className = "muted";
    note.textContent = "Camera controls will appear when the connected device reports its capabilities.";
    elements.cameraControlList.append(note);
  }
  Object.entries(properties).forEach(([key, capability]) => {
    const supported = Boolean(capability?.supported);
    const row = document.createElement("div"); row.className = `camera-control${supported ? "" : " unsupported"}`;
    const head = document.createElement("div"); head.className = "camera-control-head";
    const label = document.createElement("label"); label.textContent = capability?.label || titleCase(key);
    const output = document.createElement("output");
    const knownAutomatic = typeof actual[key] === "boolean";
    const requestedMode = requestedAutomatic[key];
    output.textContent = supported ? (capability?.control === "toggle" ? (knownAutomatic ? (actual[key] ? "ON" : "OFF") : typeof requestedMode === "boolean" ? `Requested ${requestedMode ? "ON" : "OFF"} (readback unavailable)` : "State unavailable") : cameraNumber(actual[key])) : "Not supported";
    head.append(label, output); row.append(head);
    if (!supported) {
      const note = document.createElement("small"); note.textContent = capability?.reason || "Not supported by this camera/backend"; row.append(note);
    } else if (capability?.control === "toggle") {
      const control = document.createElement("label"); control.className = "camera-control-toggle"; control.append(document.createTextNode("Physical camera control"));
      const input = document.createElement("input"); input.type = "checkbox"; input.checked = knownAutomatic ? actual[key] : requestedMode === true; input.indeterminate = !knownAutomatic && typeof requestedMode !== "boolean"; input.disabled = !editable; input.setAttribute("aria-label", capability?.label || key);
      input.id = `camera-control-${key}`; label.htmlFor = input.id;
      input.addEventListener("change", () => postCameraSettings({ [key]: input.checked })); control.append(input); row.append(control);
    } else {
      const range = Array.isArray(capability?.range) && capability.range.length === 2 ? capability.range : null;
      const input = document.createElement("input"); input.type = range ? "range" : "number"; input.value = actual[key] == null ? "" : String(actual[key]); input.disabled = !editable; input.setAttribute("aria-label", capability?.label || key);
      input.id = `camera-control-${key}`; label.htmlFor = input.id; output.htmlFor = input.id;
      if (range) { input.min = String(range[0]); input.max = String(range[1]); input.step = capability?.step == null ? "any" : String(capability.step); }
      else { input.step = "any"; input.placeholder = "Driver value"; }
      const apply = () => { if (input.value !== "") postCameraSettings({ [key]: Number(input.value) }); };
      if (range) input.addEventListener("input", () => { output.textContent = input.value; clearTimeout(cameraControlTimers.get(key)); cameraControlTimers.set(key, setTimeout(apply, 160)); });
      input.addEventListener("change", () => { clearTimeout(cameraControlTimers.get(key)); apply(); }); row.append(input);
      const note = document.createElement("small"); note.textContent = range ? "Hardware range reported by the active backend." : "This backend does not report a safe slider range; enter a value from the camera driver."; row.append(note);
    }
    elements.cameraControlList.append(row);
  });
}

function renderCameraCalibration(status) {
  cameraCalibrationStatus = status;
  const camera = status?.camera || {};
  const available = Boolean(status?.available);
  const locked = Boolean(status?.locked);
  const calibration = Boolean(status?.calibration_mode);
  const configuredIndex = finiteNumber(status?.configured_camera_index);
  const cameraName = camera.device_name || "Camera unavailable";
  elements.cameraDeviceName.textContent = configuredIndex == null ? cameraName : `Camera #${configuredIndex} — ${cameraName}`;
  elements.cameraConnection.textContent = available ? "Connected to the shared inspection capture" : (status?.capabilities?.reason || "Start inspection to connect");
  elements.cameraLockBadge.textContent = locked ? "LOCKED" : "UNLOCKED"; elements.cameraLockBadge.classList.toggle("locked", locked);
  elements.cameraCaptureResolution.textContent = Array.isArray(camera.capture_resolution) ? `${camera.capture_resolution[0]} x ${camera.capture_resolution[1]}` : "-";
  elements.cameraProcessingResolution.textContent = Array.isArray(latestStatus?.frame_size) ? `${latestStatus.frame_size[0]} x ${latestStatus.frame_size[1]}` : "-";
  elements.cameraHardwareFps.textContent = cameraNumber(camera.fps); elements.cameraBackend.textContent = camera.backend || "-";
  elements.cameraProfileName.textContent = camera.profile_name || "Not saved"; elements.cameraLockState.textContent = locked ? "Locked" : "Unlocked";
  elements.calibrationMode.checked = calibration; elements.calibrationMode.disabled = !available || locked;
  const attempts = Array.isArray(status?.open_attempts) ? status.open_attempts : [];
  const attemptSummary = attempts.map((attempt) => {
    const backend = typeof attempt?.backend === "string" && attempt.backend ? attempt.backend : "Unknown backend";
    const outcome = typeof attempt?.status === "string" && attempt.status ? attempt.status.replaceAll("_", " ") : "failed";
    return `${backend}: ${outcome}`;
  }).join("; ");
  elements.cameraControlNote.textContent = available
    ? (locked ? "Unlock to calibrate" : calibration ? "Validated hardware controls" : "Enable Calibration Mode to adjust")
    : [status?.configured_camera_note || "Camera is not running", attemptSummary ? `Open attempts: ${attemptSummary}.` : ""].filter(Boolean).join(" ");
  elements.imageStatistics.classList.toggle("hidden", !calibration);
  const stats = status?.image_statistics || {};
  elements.statFrameBrightness.textContent = cameraNumber(stats.frame_brightness); elements.statFishBrightness.textContent = cameraNumber(stats.fish_roi_brightness); elements.statBackgroundBrightness.textContent = cameraNumber(stats.background_brightness); elements.statContrast.textContent = cameraNumber(stats.fish_background_contrast);
  const warning = status?.condition_warning; elements.cameraConditionWarning.classList.toggle("hidden", !warning); elements.cameraConditionWarning.textContent = warning?.message || "";
  const editable = cameraEditable(status); elements.cameraReset.disabled = !editable; elements.cameraLoadProfile.disabled = !editable; elements.cameraSaveProfile.disabled = !editable; elements.cameraLock.disabled = !available;
  elements.cameraLock.textContent = locked ? "Unlock camera settings" : "Lock inspection camera";
  const profile = status?.profile || {};
  const confirmation = profile?.operator_confirmation || {};
  const references = status?.pending_reference_scenes || profile?.reference_scenes || {};
  const emptyReference = references?.empty_conveyor;
  elements.cameraProfileConfirmation.textContent = confirmation?.confirmed
    ? `Confirmed${confirmation.confirmed_at ? ` · ${confirmation.confirmed_at}` : ""}`
    : (emptyReference ? "Empty-conveyor reference recorded; save then confirm" : "Record an empty-conveyor reference first");
  const installation = profile?.installation || {};
  fillCameraField(elements.cameraOperatorName, confirmation?.operator_name);
  fillCameraField(elements.cameraInstallationDeviceIdentity, installation?.device_identity);
  fillCameraField(elements.cameraInstallationHeight, installation?.camera_height);
  fillCameraField(elements.cameraInstallationAngle, installation?.camera_angle);
  fillCameraField(elements.cameraInstallationConveyor, installation?.conveyor_position);
  fillCameraField(elements.cameraInstallationLighting, installation?.lighting_position);
  elements.cameraRecordEmptyReference.disabled = !editable;
  elements.cameraRecordFishReference.disabled = !editable;
  elements.cameraConfirmProfile.disabled = !editable;
  renderCameraControls(status);
}

async function loadCameraCalibration() {
  try {
    const response = await fetch("/api/camera/settings"); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Camera settings unavailable.");
    renderCameraCalibration(data);
  } catch (error) { setCameraCalibrationMessage(error instanceof Error ? error.message : "Camera settings unavailable.", true); }
}
async function cameraRequest(path, payload = undefined, successMessage = null) {
  try {
    const options = payload === undefined ? { method: "POST" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) };
    const response = await fetch(path, options); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Camera request was not accepted.");
    renderCameraCalibration(data.camera || data); setCameraCalibrationMessage(data.success === false ? "The camera returned a different value; review the readback." : successMessage || (data.policy_session_id ? "Camera setting applied. Active evidence was reset and a new policy session started." : "Camera setting applied."), data.success === false); return data;
  } catch (error) { setCameraCalibrationMessage(error instanceof Error ? error.message : "Camera request failed.", true); await loadCameraCalibration(); return null; }
}
function postCameraSettings(values) { return cameraRequest("/api/camera/settings", values); }


function ensureHistoryVerdictFilter() {
  const filters = elements.historyFilter?.parentElement; if (!filters) return;
  if (!$("history-verdict-status")) {
    const label = document.createElement("label"); label.textContent = "Verdict status"; const select = document.createElement("select"); select.id = "history-verdict-status";
    [["", "All verdicts"], ["NEEDS_REVIEW", "Needs review"]].forEach(([value, text]) => { const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option); });
    label.append(select); filters.insertBefore(label, elements.historyFilter);
  }
  elements.historyVerdict = $("history-verdict-status");
  const header = elements.historyBody?.closest("table")?.querySelector("thead tr");
  if (header && !header.dataset.verdictColumns) {
    header.dataset.verdictColumns = "true"; header.replaceChildren(); ["Fish ID", "Timestamp", "Original AI verdict", "Weighted support", "Model 1 detection", "Model 2 best evidence", "Coverage", "Verdict status", "Reason", "Manual final", "Processing"].forEach((name) => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = name; header.append(cell); });
  }
}
function renderHistoryRows(rows) {
  const key = JSON.stringify(rows); if (historyRowsKey === key) return; historyRowsKey = key;
  elements.historyBody.replaceChildren();
  rows.forEach((event) => {
    const evidence = model2BestEvidence(event); const reason = verdictReason(event); const row = document.createElement("tr"); const fish = fishHistoryCell(event);
    row.append(fish, historyCell(formatTime(event.timestamp)), historyCell(aiFinalGrade(event), "grade-cell"), historyCell(scoreText(weightedFinalSupport(event))), historyCell(scoreText(model1Confidence(event))), historyCell(`${evidence.grade || "-"} ${scoreText(evidence.score)}`, "status-note"), historyCell(coverageText(event)), historyCell(readableVerdictStatus(verdictStatus(event)), needsReview(event) ? "review-status" : "status-note"), historyCell(reason.text || reason.label || "-", "status-note"), historyCell(manualGrade(event) || "-", manualGrade(event) ? "manual-grade" : "status-note"), historyCell(formatMs(event.processing_time_ms)));
    elements.historyBody.append(row);
  });
  labelHistoryRows(elements.historyBody);
}
function reviewFilterMatches(event) {
  const search = elements.historySearch?.value.trim().replace(/fish|#/gi, "").trim(); if (search && !String(event.track_id ?? "").includes(search)) return false;
  const grade = elements.historyGrade?.value; if (grade && aiFinalGrade(event).toLowerCase() !== grade.toLowerCase()) return false;
  const feature = elements.historyFeature?.value; if (feature && !observedRegions(event).some((region) => region.toLowerCase() === feature.toLowerCase())) return false;
  const minimum = finiteNumber(elements.historyConfidence?.value); return minimum == null || (asFraction(weightedFinalSupport(event)) || 0) * 100 >= minimum;
}
function setHistoryPageState(state, total, itemCount) {
  state.totalPages = Math.max(1, Math.ceil(total / 25)); state.page = Math.min(Math.max(1, state.page), state.totalPages); elements.historyPage.textContent = `Page ${state.page} of ${state.totalPages}`; elements.historyPrev.disabled = state.page <= 1; elements.historyNext.disabled = state.page >= state.totalPages; return itemCount;
}
async function loadHistorySessions() {
  try {
    const response = await fetch("/api/sessions?limit=1000"); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Sessions unavailable");
    const selected = elements.historySession.value; elements.historySession.replaceChildren();
    const current = document.createElement("option"); current.value = ""; current.textContent = "Latest run"; elements.historySession.append(current);
    (data.items || []).forEach((session) => { const option = document.createElement("option"); option.value = session.session_id; option.textContent = `${session.started_at || "Unknown date"} · ${session.session_id}`; elements.historySession.append(option); });
    elements.historySession.value = selected;
  } catch (error) { elements.historyEmpty.textContent = error instanceof Error ? error.message : "Sessions unavailable."; }
}
function exportSessionLabel(session, currentSessionId) {
  const started = typeof session?.started_at === "string" && session.started_at ? session.started_at : "Unknown start";
  const state = session?.session_id === currentSessionId ? "current" : session?.ended_at ? "completed" : "open";
  return `${started} · ${state} · ${session.session_id}`;
}
async function loadExportSessions() {
  const version = ++exportSessionsRequestVersion;
  const selected = elements.exportSession.value;
  exportSessionsLoading = true; exportSessionsError = "";
  elements.exportSession.disabled = true;
  elements.exportSession.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "Loading inspection runs…" }));
  elements.exportSessionStatus.textContent = "Loading durable inspection runs…";
  updateExportSelection({ preserveFeedback: exportInFlight });
  try {
    const response = await fetch("/api/sessions?limit=1000"); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Inspection runs unavailable");
    if (version !== exportSessionsRequestVersion) return;
    const sessions = Array.isArray(data.items) ? data.items.filter((session) => session && typeof session.session_id === "string" && session.session_id) : [];
    elements.exportSession.replaceChildren();
    if (!sessions.length) {
      elements.exportSession.append(Object.assign(document.createElement("option"), { value: "", textContent: "No durable inspection runs available" }));
      elements.exportSession.disabled = true;
      exportSessionsError = "No durable inspection runs are available yet.";
      elements.exportSessionStatus.textContent = exportSessionsError;
      return;
    }
    sessions.forEach((session) => elements.exportSession.append(Object.assign(document.createElement("option"), {
      value: session.session_id, textContent: exportSessionLabel(session, data.current_session_id),
    })));
    const current = typeof data.current_session_id === "string" ? data.current_session_id : "";
    elements.exportSession.value = sessions.some((session) => session.session_id === selected) ? selected
      : sessions.some((session) => session.session_id === current) ? current : sessions[0].session_id;
    elements.exportSession.disabled = false;
    elements.exportSessionStatus.textContent = "Choose a durable inspection run to export its records and recorded configuration.";
  } catch (error) {
    if (version !== exportSessionsRequestVersion) return;
    exportSessionsError = error instanceof Error ? error.message : "Inspection runs unavailable.";
    elements.exportSession.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "Inspection runs unavailable" }));
    elements.exportSession.disabled = true;
    elements.exportSessionStatus.textContent = exportSessionsError;
  } finally {
    if (version === exportSessionsRequestVersion) {
      exportSessionsLoading = false;
      updateExportSelection({ preserveFeedback: exportInFlight });
    }
  }
}
async function loadHistory(resetPage = false) {
  ensureHistoryVerdictFilter(); if (resetPage) historyState.page = 1;
  if (document.hidden || selectedView !== "history") return;
  const dataRevision = analyticsVersion(latestStatus);
  const requestKey = JSON.stringify([historyState.page, elements.historySession.value, elements.historySearch.value, elements.historyGrade.value, elements.historyFeature.value, elements.historyConfidence.value, elements.historyVerdict?.value, dataRevision]);
  if (historyRequestKey === requestKey) return;
  historyController?.abort();
  const controller = new AbortController(); historyController = controller;
  historyRequestKey = requestKey;
  const version = ++historyRequestVersion;
  elements.historyEmpty.textContent = "No inspection records match these filters.";
  try {
    if (elements.historyVerdict?.value === "NEEDS_REVIEW") {
      const reviewQuery = new URLSearchParams({ include_reviewed: "true" }); if (elements.historySession.value) reviewQuery.set("session_id", elements.historySession.value);
      const response = await fetch(`/api/reviews?${reviewQuery}`, { signal: controller.signal }); const data = await response.json(); if (version !== historyRequestVersion || selectedView !== "history") return; if (!response.ok) throw new Error(data.detail || "Review filter unavailable");
      const filtered = (data.items || []).filter(reviewFilterMatches); const total = filtered.length; setHistoryPageState(historyState, total, total); const pageItems = filtered.slice((historyState.page - 1) * 25, historyState.page * 25);
      elements.historyEmpty.classList.toggle("hidden", pageItems.length > 0); elements.historyWrap.classList.toggle("hidden", pageItems.length === 0); renderHistoryRows(pageItems); historyLoadedRevision = dataRevision; return;
    }
    const query = new URLSearchParams({ page: String(historyState.page), page_size: "25" }); if (elements.historySession.value) query.set("session_id", elements.historySession.value); if (elements.historySearch.value.trim()) query.set("search", elements.historySearch.value.trim()); if (elements.historyGrade.value) query.set("grade", elements.historyGrade.value); if (elements.historyFeature.value) query.set("feature", elements.historyFeature.value); if (elements.historyConfidence.value) query.set("min_confidence", elements.historyConfidence.value);
    const response = await fetch(`/api/history?${query}`, { signal: controller.signal }); const data = await response.json(); if (version !== historyRequestVersion || selectedView !== "history") return; if (!response.ok) throw new Error(data.detail || "History unavailable"); historyState.totalPages = data.total_pages || 1; historyState.page = data.page || 1; elements.historyPage.textContent = `Page ${historyState.page} of ${historyState.totalPages}`; elements.historyPrev.disabled = historyState.page <= 1; elements.historyNext.disabled = historyState.page >= historyState.totalPages;
    const rows = data.items || []; elements.historyEmpty.classList.toggle("hidden", rows.length > 0); elements.historyWrap.classList.toggle("hidden", rows.length === 0); renderHistoryRows(rows); historyLoadedRevision = dataRevision;
  } catch (error) { if (error.name !== "AbortError" && version === historyRequestVersion) { elements.historyEmpty.textContent = error instanceof Error ? error.message : "History unavailable."; elements.historyEmpty.classList.remove("hidden"); elements.historyWrap.classList.add("hidden"); } }
  finally { if (version === historyRequestVersion) { historyRequestKey = null; historyController = null; } }
}
function renderReviewRows(rows) {
  const key = JSON.stringify(rows); if (reviewRowsKey === key) return; reviewRowsKey = key;
  elements.reviewBody.replaceChildren();
  rows.forEach((event) => {
    const reason = verdictReason(event); const row = document.createElement("tr"); const fish = fishHistoryCell(event);
    const action = document.createElement("button"); action.type = "button"; action.className = "button quiet review-action"; action.textContent = "Review"; action.addEventListener("click", () => openHistoryAnalysis(event)); const actionCell = document.createElement("td"); actionCell.append(action);
    row.append(fish, historyCell(formatTime(event.timestamp)), historyCell(aiFinalGrade(event), "grade-cell"), historyCell(scoreText(weightedFinalSupport(event))), historyCell(coverageText(event)), historyCell(reason.text || reason.label || "-", "status-note"), historyCell(manualGrade(event) || "-", manualGrade(event) ? "manual-grade" : "status-note"), actionCell); elements.reviewBody.append(row);
  });
  labelHistoryRows(elements.reviewBody);
}
async function loadReviewQueue(resetPage = false) {
  if (!elements.reviewBody) return; if (resetPage) reviewState.page = 1;
  if (document.hidden || selectedView !== "review") return;
  const dataRevision = analyticsVersion(latestStatus);
  const requestKey = JSON.stringify([reviewState.page, dataRevision]);
  if (reviewRequestKey === requestKey) return;
  reviewController?.abort();
  const controller = new AbortController(); reviewController = controller;
  reviewRequestKey = requestKey;
  const version = ++reviewRequestVersion;
  elements.reviewEmpty.textContent = "No fish currently need review.";
  try {
    const response = await fetch("/api/reviews", { signal: controller.signal }); const data = await response.json(); if (version !== reviewRequestVersion || selectedView !== "review") return; if (!response.ok) throw new Error(data.detail || "Review queue unavailable"); const allItems = Array.isArray(data.items) ? data.items : []; const total = finiteNumber(data.total) ?? allItems.length;
    reviewState.totalPages = Math.max(1, Math.ceil(total / 25)); reviewState.page = Math.min(Math.max(1, reviewState.page), reviewState.totalPages); elements.reviewPage.textContent = `Page ${reviewState.page} of ${reviewState.totalPages}`; elements.reviewPrev.disabled = reviewState.page <= 1; elements.reviewNext.disabled = reviewState.page >= reviewState.totalPages;
    const rows = allItems.slice((reviewState.page - 1) * 25, reviewState.page * 25); elements.reviewEmpty.classList.toggle("hidden", rows.length > 0); elements.reviewWrap.classList.toggle("hidden", rows.length === 0); renderReviewRows(rows); reviewLoadedRevision = dataRevision;
  } catch (error) { if (error.name !== "AbortError" && version === reviewRequestVersion) { elements.reviewEmpty.textContent = error instanceof Error ? error.message : "Review queue unavailable."; elements.reviewEmpty.classList.remove("hidden"); elements.reviewWrap.classList.add("hidden"); } }
  finally { if (version === reviewRequestVersion) { reviewRequestKey = null; reviewController = null; } }
}

function setConfidence(value, apply = false) {
  const normalized = Math.max(0, Math.min(100, Math.round(Number(value)))); elements.slider.value = String(normalized); elements.settingsThreshold.textContent = `${normalized}%`;
  if (apply) postSettings({ detection_confidence_threshold: normalized / 100 });
}
function setQualityConfidence(value, apply = false) {
  const normalized = Math.max(0, Math.min(100, Math.round(Number(value)))); elements.qualitySlider.value = String(normalized); elements.settingsQualityThreshold.textContent = `${normalized}%`;
  if (apply) postSettings({ quality_confidence_threshold: normalized / 100 });
}
function setOverlay(name, checked) { overlayControls[name].forEach((control) => { control.checked = checked; }); postSettings({ display_settings: { [name]: checked } }); }
function uploadAnalysisAvailable() { return Boolean(latestStatus?.upload_analysis_available); }
function updateUploadControls() {
  const canAnalyze = Boolean(selectedUpload && uploadAnalysisAvailable() && !uploadInFlight);
  elements.analyze.disabled = !canAnalyze;
  elements.selectUpload.disabled = uploadInFlight;
  elements.uploadInput.disabled = uploadInFlight;
  elements.closeUpload.disabled = uploadInFlight;
  elements.uploadMode.disabled = uploadInFlight;
  elements.uploadWorkspace.setAttribute("aria-busy", String(uploadInFlight));
  elements.uploadProgress.classList.toggle("hidden", !uploadInFlight);
  elements.uploadProgress.setAttribute("aria-hidden", String(!uploadInFlight));
}
function isVideoUpload(file) { return Boolean(file && (file.type.startsWith("video/") || /\.(mp4|mov|webm)$/i.test(file.name))); }
function revokeUploadPreview() {
  if (uploadPreviewUrl) URL.revokeObjectURL(uploadPreviewUrl);
  uploadPreviewUrl = null;
  elements.uploadImage.onerror = null;
  if (uploadFrameTimer) { clearInterval(uploadFrameTimer); uploadFrameTimer = null; }
  elements.uploadVideo.pause();
  elements.uploadVideo.removeAttribute("src");
  elements.uploadVideo.load();
}
function resetUploadWorkspace() {
  uploadSelectionVersion += 1;
  selectedUpload = null;
  elements.uploadInput.value = "";
  elements.uploadStatus.textContent = "";
  elements.uploadResults.classList.add("hidden");
  elements.uploadProgress.classList.add("hidden");
  elements.uploadProgress.setAttribute("aria-hidden", "true");
  mountResultsDashboard(false);
  revokeUploadPreview();
  elements.uploadImage.removeAttribute("src");
  elements.uploadImage.alt = "Selected or annotated fish photo";
  elements.uploadImage.classList.add("hidden");
  elements.uploadVideo.classList.add("hidden");
  updateUploadControls();
}
function setUploadSelection(file) {
  const selectionVersion = ++uploadSelectionVersion;
  selectedUpload = file || null;
  elements.uploadResults.classList.add("hidden");
  mountResultsDashboard(false);
  if (!selectedUpload) {
    resetUploadWorkspace();
    return;
  }
  elements.uploadStatus.textContent = "Ready to analyze";
  revokeUploadPreview();
  uploadPreviewUrl = URL.createObjectURL(selectedUpload);
  const videoUpload = isVideoUpload(selectedUpload);
  if (videoUpload) {
    elements.uploadImage.classList.add("hidden");
    elements.uploadVideo.src = uploadPreviewUrl;
    elements.uploadVideo.classList.remove("hidden");
    elements.uploadVideo.load();
  } else {
    elements.uploadVideo.classList.add("hidden");
    elements.uploadImage.src = uploadPreviewUrl;
    elements.uploadImage.alt = `Selected image preview: ${selectedUpload.name}`;
    elements.uploadImage.classList.remove("hidden");
  }
  elements.uploadImage.onerror = () => {
    if (selectionVersion !== uploadSelectionVersion) return;
    elements.uploadStatus.textContent = "Preview unavailable";
    elements.uploadImage.classList.add("hidden");
    elements.uploadVideo.classList.add("hidden");
  };
  updateUploadControls();
}
function toggleUpload(show) {
  if (!show && uploadInFlight) return;
  elements.uploadMode.setAttribute("aria-expanded", String(show));
  elements.uploadMode.textContent = show ? "Close media analysis" : "Analyze Media";
  if (show) {
    openPanel(elements.uploadWorkspace);
    requestAnimationFrame(() => elements.selectUpload.focus({ preventScroll: true }));
  } else {
    closePanel(elements.uploadWorkspace);
    resetUploadWorkspace();
    elements.uploadMode.focus({ preventScroll: true });
  }
}

document.querySelectorAll(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
elements.model2Selector.addEventListener("change", () => { void selectModel2(); });
elements.liveModelSelector?.addEventListener("change", () => { elements.model2Selector.value = elements.liveModelSelector.value; void selectModel2(); });
document.querySelectorAll(".nav-item[data-anchor]").forEach((button) => button.addEventListener("click", () => { showView("live"); $("analytics-disclosure").open = true; setTimeout(() => { $(button.dataset.anchor).scrollIntoView({ behavior: motionPreference(), block: "start" }); document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item === button)); }, 30); }));
$("analytics-disclosure").addEventListener("toggle", () => { if (selectedView === "live" && $("analytics-disclosure").open && latestStatus) render(latestStatus); });
$("advanced-diagnostics").addEventListener("toggle", () => { if (selectedView === "live" && $("advanced-diagnostics").open && latestStatus) render(latestStatus); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    statusController?.abort(); analyticsController?.abort(); historyController?.abort(); reviewController?.abort();
    historyRequestVersion++; reviewRequestVersion++; historyRequestKey = null; reviewRequestKey = null;
  } else {
    historyLoadedRevision = null; reviewLoadedRevision = null; getStatus();
  }
});
elements.sidebarToggle.addEventListener("click", () => {
  const collapsed = elements.shell.classList.toggle("sidebar-collapsed");
  elements.sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
  elements.sidebarToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
});
elements.start.addEventListener("click", () => postControl(latestStatus && ["starting", "running"].includes(latestStatus.inspection_status) ? "/api/inspection/stop" : "/api/inspection/start")); elements.emptyStart.addEventListener("click", () => postControl(latestStatus && ["starting", "running"].includes(latestStatus.inspection_status) ? "/api/inspection/stop" : "/api/inspection/start"));
elements.webcam.addEventListener("click", () => {
  if (!latestStatus || ["starting", "running"].includes(latestStatus.inspection_status)) return;
  postControl("/api/inspection/start");
});
elements.previewMode.addEventListener("click", () => { rawPreview = !rawPreview; detachStream(); if (latestStatus) renderCamera(latestStatus); });
elements.reset.addEventListener("click", () => { if (!hasEvents(latestStatus) || window.confirm("Reset this session? Live counters will reset. Saved inspection records will remain in the local database.")) postControl("/api/session/reset"); });
elements.uploadMode.addEventListener("click", () => toggleUpload(elements.uploadWorkspace.classList.contains("hidden")));
elements.closeUpload.addEventListener("click", () => toggleUpload(false));
elements.selectUpload.addEventListener("click", () => { if (!uploadInFlight) elements.uploadInput.click(); });
elements.uploadInput.addEventListener("change", () => setUploadSelection(elements.uploadInput.files?.[0] || null));
async function waitForVideoAnalysis(jobId, requestVersion, upload) {
  while (requestVersion === uploadRequestVersion && upload === selectedUpload) {
    const response = await fetch(`/api/analyze-video/${encodeURIComponent(jobId)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    elements.uploadStatus.textContent = payload.status === "complete"
      ? "Video analysis complete"
      : `Processing video: ${payload.progress || 0}% (${payload.processed_frames || 0} frames)`;
    if (payload.status === "error") throw new Error(payload.error || "Video analysis failed.");
    if (payload.status === "complete") return payload.result;
    await new Promise((resolve) => setTimeout(resolve, 450));
  }
  return null;
}
elements.analyze.addEventListener("click", async () => {
  if (!selectedUpload || uploadInFlight) return;
  const upload = selectedUpload;
  const requestVersion = ++uploadRequestVersion;
  uploadInFlight = true;
  elements.analyze.classList.add("is-analyzing");
  const videoUpload = isVideoUpload(upload);
  elements.uploadStatus.textContent = videoUpload ? "Uploading video" : "";
  updateUploadControls();
  try {
    const response = await fetch(videoUpload ? "/api/analyze-video" : "/api/analyze-image", {
      method: "POST",
      headers: { "Content-Type": upload.type || "application/octet-stream", "X-Filename": upload.name },
      body: upload,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    if (requestVersion !== uploadRequestVersion || upload !== selectedUpload) return;
    const analysis = videoUpload ? await waitForVideoAnalysis(payload.job_id, requestVersion, upload) : payload;
    if (!analysis) return;
    const isVideo = videoUpload;
    const isPartPreview = analysis.analysis_mode === "part_preview";
    revokeUploadPreview();
    if (isVideo && Array.isArray(analysis.annotated_frames) && analysis.annotated_frames.length) {
      let frameIndex = 0;
      elements.uploadImage.src = analysis.annotated_frames[0];
      elements.uploadImage.alt = `Annotated video analysis result: ${upload.name}`;
      elements.uploadImage.classList.remove("hidden");
      uploadFrameTimer = setInterval(() => {
        frameIndex = (frameIndex + 1) % analysis.annotated_frames.length;
        elements.uploadImage.src = analysis.annotated_frames[frameIndex];
      }, 120);
    } else {
      elements.uploadImage.src = analysis.annotated_image;
      elements.uploadImage.alt = `Annotated analysis result: ${upload.name}`;
      elements.uploadImage.classList.remove("hidden");
    }
    renderResultsDashboard(isPartPreview ? [] : analysis.fish, {source: "upload", complete: true, scope: `upload:${requestVersion}`, metadata: {source_name: upload.name, analyzed_at: analysis.analyzed_at || new Date().toISOString(), analysis_mode: analysis.analysis_mode || "whole_fish", model_info: latestStatus?.model_info}});
    elements.resultsSource.querySelector('option[value="upload"]').disabled = false;
    resultsFilter = "All"; selectResultsSource("upload"); mountResultsDashboard(true);
    elements.uploadResults.classList.remove("hidden");
    elements.uploadStatus.textContent = isPartPreview ? `Part preview: ${analysis.parts_detected || 0} parts; individual fish grading is unavailable.` : "";
  } catch (error) {
    if (requestVersion !== uploadRequestVersion) return;
    elements.uploadStatus.textContent = error instanceof Error ? error.message : `${videoUpload ? "Video" : "Image"} analysis failed.`;
  } finally {
    if (requestVersion !== uploadRequestVersion) return;
    uploadInFlight = false;
    elements.analyze.textContent = "Run analysis";
    elements.analyze.classList.remove("is-analyzing");
    updateUploadControls();
  }
});
function pixelBox(box) {
  if (!Array.isArray(box) || box.length < 4) return null;
  const [left, top, right, bottom] = box.slice(0, 4).map(finiteNumber);
  if ([left, top, right, bottom].some((value) => value == null)) return null;
  const width = right - left; const height = bottom - top;
  return width > 0 && height > 0 ? { left, top, right, bottom, width, height, area: width * height } : null;
}
function pixelBoxText(box) {
  const dimensions = pixelBox(box);
  return dimensions ? `${Math.round(dimensions.width)} x ${Math.round(dimensions.height)} px` : "Not available";
}

ensureHistoryVerdictFilter();
if (elements.viewAll) elements.viewAll.addEventListener("click", () => showView("history")); elements.historyFilter.addEventListener("click", () => loadHistory(true)); elements.historySession.addEventListener("change", () => loadHistory(true)); elements.historyPrev.addEventListener("click", () => { if (historyState.page > 1) { historyState.page -= 1; loadHistory(); } }); elements.historyNext.addEventListener("click", () => { if (historyState.page < historyState.totalPages) { historyState.page += 1; loadHistory(); } });
elements.resultsSource.addEventListener("change", () => selectResultsSource(elements.resultsSource.value));
elements.resultsExportCsv.addEventListener("click", exportResultsCsv); elements.resultsExportPdf.addEventListener("click", exportResultsPdf);
elements.reviewPrev.addEventListener("click", () => { if (reviewState.page > 1) { reviewState.page -= 1; loadReviewQueue(); } }); elements.reviewNext.addEventListener("click", () => { if (reviewState.page < reviewState.totalPages) { reviewState.page += 1; loadReviewQueue(); } });
elements.settingsButton.addEventListener("click", openSettings); elements.sidebarSettings.addEventListener("click", openSettings); elements.closeSettings.addEventListener("click", closeSettings); elements.openConfidence.addEventListener("click", openSettings); elements.closeCameraCalibration.addEventListener("click", closeCameraCalibration); elements.scrim.addEventListener("click", () => { closeSettings(); closeCameraCalibration(); closeExport(); closePanel(elements.uploadWorkspace); });
elements.exportButton.addEventListener("click", openExport); elements.sidebarExport.addEventListener("click", openExport); elements.closeExport.addEventListener("click", closeExport); elements.cancelExport.addEventListener("click", closeExport);
elements.calibrationMode.addEventListener("change", () => postCameraSettings({ calibration_mode: elements.calibrationMode.checked }));
  elements.cameraReset.addEventListener("click", () => cameraRequest("/api/camera/reset")); elements.cameraLoadProfile.addEventListener("click", () => cameraRequest("/api/camera/profile/load")); elements.cameraSaveProfile.addEventListener("click", () => cameraRequest("/api/camera/profile/save", undefined, "Inspection profile saved. Record references and explicitly confirm when the physical setup is reviewed.")); elements.cameraLock.addEventListener("click", () => cameraRequest("/api/camera/lock", { locked: !Boolean(cameraCalibrationStatus?.locked) }));
  elements.cameraRecordEmptyReference.addEventListener("click", () => cameraRequest("/api/camera/reference", { scene_type: "empty_conveyor" }, "Empty-conveyor reference recorded. Save the profile before confirmation."));
  elements.cameraRecordFishReference.addEventListener("click", () => cameraRequest("/api/camera/reference", { scene_type: "representative_fish" }, "Representative-fish reference recorded for acquisition monitoring only."));
  elements.cameraConfirmProfile.addEventListener("click", () => {
    const installation = researchInstallationPayload();
    const missing = Object.entries(installation).filter(([, value]) => !value).map(([key]) => key.replaceAll("_", " "));
    if (missing.length) { setCameraCalibrationMessage(`Confirmation needs: ${missing.join(", ")}.`, true); return; }
    cameraRequest("/api/camera/profile/confirm", { operator_confirmed: true, operator_name: elements.cameraOperatorName.value.trim() || null, installation }, "Calibration profile explicitly confirmed. Lock the camera before collecting study data.");
  });
elements.slider.addEventListener("input", () => setConfidence(elements.slider.value)); elements.slider.addEventListener("change", () => setConfidence(elements.slider.value, true)); elements.confidenceMinus.addEventListener("click", () => setConfidence(Number(elements.slider.value) - 1, true)); elements.confidencePlus.addEventListener("click", () => setConfidence(Number(elements.slider.value) + 1, true)); elements.resetConfidence.addEventListener("click", () => setConfidence(defaultConfidence * 100, true));
elements.qualitySlider.addEventListener("input", () => setQualityConfidence(elements.qualitySlider.value)); elements.qualitySlider.addEventListener("change", () => setQualityConfidence(elements.qualitySlider.value, true)); elements.qualityConfidenceMinus.addEventListener("click", () => setQualityConfidence(Number(elements.qualitySlider.value) - 1, true)); elements.qualityConfidencePlus.addEventListener("click", () => setQualityConfidence(Number(elements.qualitySlider.value) + 1, true)); elements.resetQualityConfidence.addEventListener("click", () => setQualityConfidence(defaultQualityConfidence * 100, true));
elements.debugRuntimeEnabled.addEventListener("change", () => postRuntimeDiagnostics({ enabled: elements.debugRuntimeEnabled.checked }));
elements.debugPause.addEventListener("click", () => postRuntimeDiagnostics({ paused: !Boolean(latestStatus?.runtime_diagnostics?.paused) }));
Object.entries(overlayControls).forEach(([name, controls]) => controls.filter(Boolean).forEach((control) => control.addEventListener("change", () => setOverlay(name, control.checked))));
function selectedExportRange() { return document.querySelector("input[name=export-range]:checked").value; }
function syncExportRangeControls() {
  const range = selectedExportRange();
  elements.dateRange.classList.toggle("hidden", range !== "custom");
  elements.exportSessionRange.classList.toggle("hidden", range !== "specific_session");
  if (range === "specific_session" && !exportSessionsLoading && (elements.exportSession.disabled || !elements.exportSession.options.length)) void loadExportSessions();
  updateExportSelection();
}
document.querySelectorAll("input[name=export-range]").forEach((input) => input.addEventListener("change", syncExportRangeControls));
function updateExportSelection({ preserveFeedback = false } = {}) {
  const hasFields = $("export-all-evidence").checked || Boolean(document.querySelector(".export-fields input:checked"));
  const range = selectedExportRange(); const custom = range === "custom"; const specificSession = range === "specific_session";
  const start = elements.exportStartDate.value, end = elements.exportEndDate.value;
  const datesValid = !custom || !start || !end || start <= end;
  const sessionValid = !specificSession || (!exportSessionsLoading && !exportSessionsError && !elements.exportSession.disabled && Boolean(elements.exportSession.value));
  $("confirm-export-button").disabled = exportInFlight || !hasFields || !datesValid || !sessionValid;
  $("export-fields-error").classList.toggle("hidden", hasFields);
  if (!preserveFeedback) $("export-feedback").textContent = !datesValid ? "Start date must be on or before end date."
    : !sessionValid ? (exportSessionsLoading ? "Loading inspection runs…" : exportSessionsError || "Choose an inspection run.") : "";
}
elements.exportForm.addEventListener("change", updateExportSelection);
elements.exportForm.addEventListener("input", updateExportSelection);
elements.exportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (exportInFlight) return;
  const button = $("confirm-export-button");
  const fields = [...document.querySelectorAll(".export-fields input:checked")].map((input) => input.value);
  const completeAnalysis = $("export-all-evidence").checked;
  const invalidSelection = !completeAnalysis && !fields.length;
  $("export-fields-error").classList.toggle("hidden", !invalidSelection);
  if (invalidSelection) return;
  const exportRange = selectedExportRange(); const isCustom = exportRange === "custom"; const specificSession = exportRange === "specific_session";
  if (specificSession && (exportSessionsLoading || exportSessionsError || elements.exportSession.disabled || !elements.exportSession.value)) { updateExportSelection(); return; }
  if (isCustom && elements.exportStartDate.value && elements.exportEndDate.value && elements.exportStartDate.value > elements.exportEndDate.value) { updateExportSelection(); return; }
  const payload = {
    format: document.querySelector("input[name=export-format]:checked").value,
    range: specificSession ? "current_session" : exportRange,
    fields,
    complete_analysis: completeAnalysis,
    start_date: elements.exportStartDate.value || null,
    end_date: elements.exportEndDate.value || null,
  };
  if (specificSession) payload.session_id = elements.exportSession.value;
  button.disabled = true;
  exportInFlight = true;
  $("export-feedback").textContent = "Preparing export…";
  try {
    const response = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Export failed."); }
    const blob = await response.blob();
    const anchor = document.createElement("a");
    const disposition = response.headers.get("content-disposition") || "";
    const name = disposition.match(/filename="?([^";]+)"?/)?.[1] || `sardinella_inspection.${payload.format}`;
    anchor.href = URL.createObjectURL(blob); anchor.download = name; document.body.append(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(anchor.href); closeExport();
  } catch (error) {
    $("export-feedback").textContent = error instanceof Error ? `Export unavailable: ${error.message}` : "Export unavailable.";
  } finally {
    exportInFlight = false;
    updateExportSelection({ preserveFeedback: true });
  }
});

function showLanLogin() {
  $("lan-logout").classList.add("hidden");
  const dialog = $("lan-login-dialog"); if (!dialog.open) dialog.showModal();
}
$("lan-login-dialog").addEventListener("cancel", (event) => event.preventDefault());
$("lan-login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const token = $("lan-token").value; $("lan-token").value = ""; $("lan-login-message").textContent = "Signing in...";
  try {
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Sign-in failed.");
    lanCsrf = data.csrf_token; $("lan-login-message").textContent = ""; $("lan-login-dialog").close();
    $("lan-logout").textContent = `Sign out (${data.role})`; $("lan-logout").classList.remove("hidden"); getStatus();
  } catch (error) { $("lan-login-message").textContent = error instanceof Error ? error.message : "Sign-in failed."; }
});
$("lan-logout").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    if (!response.ok) throw new Error("Sign out failed.");
    lanCsrf = null; detachStream(); showLanLogin();
  } catch (_) { $("lan-logout").textContent = "Sign out failed; try again"; }
});
async function initializeLanSecurity() {
  try {
    const response = await fetch("/api/auth/mode", { cache: "no-store" }); if (!response.ok) throw new Error("Security profile unavailable.");
    lanEnabled = Boolean((await response.json()).lan_security); lanReady = true;
    if (lanEnabled) {
      const sessionResponse = await fetch("/api/auth/session", { cache: "no-store" });
      if (sessionResponse.ok) { const session = await sessionResponse.json(); lanCsrf = session.csrf_token; $("lan-logout").textContent = `Sign out (${session.role})`; $("lan-logout").classList.remove("hidden"); }
      else showLanLogin();
    }
    void loadModelSelector();
    getStatus();
  } catch (_) { lanReady = false; setTimeout(initializeLanSecurity, 3000); }
}
initializeLanSecurity(); void loadModelSelector(); void loadResultsDashboard(); setInterval(getStatus, 900); setInterval(loadResultsDashboard, 2500);
