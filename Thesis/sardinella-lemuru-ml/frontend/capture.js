/* Independent research-photo workspace. No inspection endpoints or buffers. */
(() => {
  "use strict";
  const root = document.querySelector("[data-capture-root]");
  if (!root) return;
  const standalone = document.body.hasAttribute("data-capture-standalone");
  const API = "/api/capture";
  const PAGE_SIZE = 24;
  const grades = ["Unknown", "A", "B", "C", "Rejected", "Background", "Hard negative"];
  const gradeOptions = grades.map(grade => `<option>${grade}</option>`).join("");
  root.innerHTML = `
    <div class="dc-workspace">
      <div class="dc-heading"><div><p class="eyebrow">RESEARCH COLLECTION</p><h2>Camera Capture</h2><p>Save original camera photos with a traceable collection session. Operator grade tags are provisional; photos are not expert annotations.</p></div><span class="dc-pill" id="dc-camera-state">Camera closed</span></div>
      <div class="dc-notice" id="dc-isolation">Capture uses its own camera. If the camera is in use, stop inspection manually or choose a verified separate device. The standalone launcher requires an isolated camera setup before hardware access is enabled.</div>
      <p class="dc-feedback" id="dc-feedback" role="status" aria-live="polite"></p>
      <div class="dc-layout">
        <div class="dc-stack">
          <section class="dc-card" aria-labelledby="dc-preview-title">
            <div class="dc-card-head"><h3 id="dc-preview-title">Raw camera preview</h3><span class="dc-hint" id="dc-preview-state">No camera frames</span></div>
            <div class="dc-preview-wrap" id="dc-preview-wrap"><img class="dc-preview" id="dc-preview" alt="Live raw capture camera preview" hidden><div class="dc-preview-empty" id="dc-preview-empty"><strong>Ready for a new collection</strong>Create a session, then open the capture camera. Photos retain the camera's original dimensions.</div><div class="dc-grid" id="dc-grid" hidden aria-hidden="true"></div></div>
            <div class="dc-preview-options"><label class="dc-check"><input type="checkbox" id="dc-grid-toggle">Alignment grid · preview only</label><label class="dc-check"><input type="checkbox" id="dc-flash-toggle">Shutter flash</label><label class="dc-check"><input type="checkbox" id="dc-sound-toggle">Shutter sound</label></div>
            <div class="dc-card-body">
              <div class="dc-fields"><label>Device index<input id="dc-device" type="number" min="0" max="11" step="1" value="0"></label><label>Camera backend<select id="dc-backend"><option value="default">OpenCV default</option><option value="dshow">DirectShow · Windows</option><option value="msmf">Media Foundation · Windows</option><option value="v4l2">V4L2 · Linux</option></select></label><label>Requested width<input id="dc-width" type="number" min="64" max="4096" step="1" value="1920"></label><label>Requested height<input id="dc-height" type="number" min="64" max="4096" step="1" value="1080"></label></div>
              <p class="dc-hint">An index is not a verified physical camera name. Readbacks below show what the selected device actually delivers.</p>
              <div class="dc-actions"><button class="button quiet" id="dc-camera-open" type="button">Open capture camera</button><button class="button quiet" id="dc-camera-close" type="button" disabled>Close capture camera</button></div>
              <dl class="dc-readbacks"><div><dt>Actual camera</dt><dd id="dc-readback-device">—</dd></div><div><dt>Native frame size</dt><dd id="dc-readback-size">—</dd></div><div><dt>Camera acquisition</dt><dd id="dc-camera-fps">Not measured</dd></div><div><dt>Saved photo rate</dt><dd id="dc-capture-fps">Not measured</dd></div><div><dt>Exposure / focus readbacks</dt><dd id="dc-readback-controls">Unavailable until camera opens</dd></div><div><dt>Free storage</dt><dd id="dc-disk-free">—</dd></div></dl>
              <hr class="dc-divider">
              <button class="button primary dc-shutter" id="dc-snapshot" type="button" disabled aria-describedby="dc-manual-help"><span class="dc-shutter-mark" aria-hidden="true"></span>Capture Photo</button>
              <p class="dc-hint" id="dc-manual-help">Manual capture needs no countdown or automatic run. One click saves one fresh original. Space takes a photo when you are not typing.</p>
              <div class="dc-last-save" id="dc-last-save" hidden><img id="dc-last-thumb" alt="Last saved photo"><div><strong>Saved locally</strong><span id="dc-last-name"></span><span id="dc-last-sync"></span></div></div>
            </div>
          </section>
          <section class="dc-card" aria-labelledby="dc-session-title">
            <div class="dc-card-head"><h3 id="dc-session-title">Collection session</h3><button class="button quiet" id="dc-sessions-refresh" type="button">Refresh</button></div>
            <div class="dc-card-body"><label>Current session<select id="dc-session-select"><option value="">Create a collection session below</option></select></label>
              <form id="dc-metadata-form"><div class="dc-fields">
                <label class="dc-wide">Session name<input id="dc-session-name" maxlength="120" placeholder="Morning collection · batch 04" autocomplete="off"></label>
                <label>Batch / source ID<input id="dc-batch" maxlength="120" autocomplete="off"></label><label>Source / vendor code<input id="dc-source" maxlength="120" autocomplete="off" aria-describedby="dc-privacy-help"></label>
                <label>Specimen ID, if known<input id="dc-specimen" maxlength="120" autocomplete="off"></label><label>Provisional operator tag<select id="dc-grade">${gradeOptions}</select></label>
                <label class="dc-check dc-wide"><input type="checkbox" id="dc-specimen-confirmed">I confirmed this physical specimen ID</label>
              </div>
              <details><summary>Camera setup, provenance and notes</summary><div class="dc-fields">
                <label>Operator code (optional)<input id="dc-operator" maxlength="120" autocomplete="off"></label><label>Camera setup<input id="dc-setup" maxlength="256" placeholder="Fixed height and lens" autocomplete="off"></label>
                <label>Lighting<input id="dc-lighting" maxlength="256" placeholder="Fixed LED, diffuse" autocomplete="off"></label><label>Background<input id="dc-background" maxlength="256" autocomplete="off"></label>
                <label>Conveyor<select id="dc-conveyor"><option value="unknown">Unknown</option><option value="off">Stopped</option><option value="on">Running</option></select></label><label>Angle / orientation<input id="dc-angle" maxlength="256" autocomplete="off"></label>
                <label class="dc-check dc-wide"><input id="dc-consent" type="checkbox">Collection consent has been recorded</label><label class="dc-wide">Notes / privacy instructions<textarea id="dc-notes" maxlength="2000"></textarea></label>
              </div></details>
              <p class="dc-hint" id="dc-privacy-help">Use source and operator codes rather than personal names. 1,000 photos are not 1,000 independent fish. Confirm specimen identity separately.</p>
              <div class="dc-actions"><button class="button primary" id="dc-create-session" type="submit">Create new session</button><button class="button quiet" id="dc-save-metadata" type="button" disabled>Save session metadata</button></div></form>
            </div>
          </section>
        </div>
        <div class="dc-stack">
          <section class="dc-card" aria-labelledby="dc-auto-title"><div class="dc-card-head"><h3 id="dc-auto-title">Automatic collection</h3><span class="dc-pill" id="dc-run-state">Idle</span></div><div class="dc-card-body">
            <div class="dc-fields"><label>Countdown before first shot<select id="dc-countdown"><option value="0">No countdown</option><option value="5">5 seconds</option><option value="10">10 seconds</option></select></label><label>Shot interval<select id="dc-interval"><option value="1">Every 1 second</option><option value="2">Every 2 seconds</option><option value="5">Every 5 seconds</option></select></label><label>Capture duration after countdown<select id="dc-duration"><option value="">Until stopped / count reached</option><option value="5">5 seconds</option><option value="10">10 seconds</option><option value="30">30 seconds</option><option value="60">60 seconds</option></select></label><label>Automatic photo target<select id="dc-target"><option value="">No count target</option><option value="10">10 photos</option><option value="25">25 photos</option><option value="50">50 photos</option><option value="100">100 photos</option><option value="custom">Custom count</option></select></label><label class="dc-wide" id="dc-custom-wrap" hidden>Custom automatic photo count<input id="dc-custom-count" type="number" min="1" max="10000" value="25"></label></div>
            <p class="dc-hint">The countdown and capture duration are separate. A 5-second duration does not add a 5-second countdown. The server schedules fresh frames; missed shots are reported. Runs stop at the safety limit of one hour or 10,000 automatic photos.</p>
            <div class="dc-actions"><button class="button primary" id="dc-run-start" type="button" disabled>Start automatic</button><button class="button quiet" id="dc-run-pause" type="button" disabled>Pause</button><button class="button quiet" id="dc-run-resume" type="button" disabled>Resume</button><button class="button danger" id="dc-run-stop" type="button" disabled>Stop</button></div>
            <div class="dc-run-summary" aria-live="off"><strong id="dc-countdown-state">No automatic run</strong><output id="dc-run-progress">0 scheduled · 0 saved</output><output id="dc-run-timing">Next shot: — · late: 0 · skipped: 0</output><output id="dc-last-capture">Last saved: —</output></div>
            <p class="dc-hint">Manual shots remain available during an active run when the camera has a fresh frame. Esc stops automatic collection when focus is outside fields and dialogs.</p>
          </div></section>
          <section class="dc-card" aria-labelledby="dc-drive-title"><div class="dc-card-head"><h3 id="dc-drive-title">Google Drive backup</h3><span class="dc-pill" id="dc-drive-state">Not connected</span></div><div class="dc-card-body">
            <p class="dc-feedback" id="dc-drive-message">Photos save locally first. The durable upload queue remains available while Drive is disconnected.</p>
            <p class="dc-hint">Connect uses Google OAuth consent. Folder access is restricted to the server's configured destination. A folder link alone cannot authorize uploads. Credentials stay on the server.</p>
            <div class="dc-actions"><button class="button quiet" id="dc-drive-connect" type="button" disabled>Connect Google Drive</button><button class="button quiet" id="dc-drive-test" type="button" disabled>Test folder access</button><button class="button quiet" id="dc-drive-write-test" type="button" disabled>Upload a test image</button></div>
            <a id="dc-drive-consent" target="_blank" rel="noopener noreferrer" hidden>Continue to Google consent</a>
            <label class="dc-check"><input id="dc-drive-auto" type="checkbox" disabled>Automatically sync new photos (opt in)</label>
            <div class="dc-actions"><button class="button primary" id="dc-drive-sync" type="button" disabled>Sync now</button><button class="button quiet" id="dc-drive-retry" type="button" disabled>Retry failed</button><button class="button quiet" id="dc-drive-pause" type="button" disabled>Pause sync</button></div>
            <a id="dc-drive-folder" target="_blank" rel="noopener noreferrer" hidden>Open authorized Drive folder</a>
            <p class="dc-hint">Saved locally / Queued / Uploading / Synced to Drive / Failed are separate states. Only a confirmed remote file ID counts as synced.</p>
            <p class="dc-feedback" id="dc-drive-feedback" role="status" aria-live="polite"></p>
          </div></section>
          <details class="dc-card dc-details"><summary>Collection and annotation checklist</summary><p class="dc-hint">Keep LED lighting, camera height, background, white balance and exposure stable. Record readbacks and setup changes. Collect varied A/B/C/Rejected specimens, background and hard negatives, and touching or overlapping fish.</p><p class="dc-hint">Review expert grades before annotation. Draw parent fish and head/body/tail masks with clear ownership. Distinguish missing anatomy from occlusion. Keep specimen, vendor, session and augmentation lineage together for future splits.</p><p class="dc-hint">Focus, exposure, clipping, background drift and similarity are warnings, not true grade or proof of fish identity. Raw originals are never enhanced, relabeled as expert truth, or automatically added to an existing dataset.</p></details>
        </div>
      </div>
      <dl class="dc-counters"><div class="dc-counter"><dt>Raw photos</dt><dd id="dc-count-frames">0</dd></div><div class="dc-counter"><dt>Manual photos</dt><dd id="dc-count-manual">0</dd></div><div class="dc-counter"><dt>Reviewed photos</dt><dd id="dc-count-reviewed">0</dd></div><div class="dc-counter"><dt>Confirmed specimens</dt><dd id="dc-count-specimens">0</dd></div><div class="dc-counter"><dt>Skipped scheduled shots</dt><dd id="dc-count-skipped">0</dd></div><div class="dc-counter"><dt>Upload backlog</dt><dd id="dc-count-backlog">0</dd></div></dl>
      <section class="dc-card" aria-labelledby="dc-gallery-title"><div class="dc-card-head"><div><h3 id="dc-gallery-title">Session photo gallery</h3><p class="dc-hint" id="dc-provisional-counts">Provisional tags are operator notes, not expert ground truth.</p></div><button class="button quiet" id="dc-gallery-refresh" type="button">Refresh gallery</button></div><div class="dc-card-body">
        <div class="dc-pagination"><label class="dc-check"><input id="dc-select-all" type="checkbox">Select this page</label><span id="dc-selection-count">0 selected</span><div class="dc-export"><a class="button quiet" id="dc-export-zip" hidden>ZIP + manifest</a><a class="button quiet" id="dc-export-csv" hidden>CSV</a><a class="button quiet" id="dc-export-json" hidden>JSON</a></div></div>
        <div class="dc-bulk"><div class="dc-fields"><label>Review selected photos<select id="dc-bulk-review"><option value="">Keep review state</option><option value="keep">Keep for training review</option><option value="review">Needs review</option><option value="exclude">Exclude from training</option></select></label><label>Provisional operator tag<select id="dc-bulk-grade"><option value="">Keep current tag</option>${gradeOptions}</select></label><label>Replace notes (optional)<input id="dc-bulk-notes" maxlength="2000"></label><label>Known specimen ID (optional)<input id="dc-bulk-specimen" maxlength="120"></label><label class="dc-check"><input id="dc-bulk-confirmed" type="checkbox">Confirm supplied specimen ID</label><button class="button quiet" id="dc-bulk-save" type="button" disabled>Apply to selected</button></div><p class="dc-hint">Excluding is non-destructive. Every raw original remains saved; metadata changes do not overwrite it.</p></div>
        <div class="dc-empty" id="dc-gallery-empty">No captured photos yet. Create a session and use Capture Photo without starting a timer.</div><div class="dc-gallery" id="dc-gallery"></div>
        <div class="dc-pagination"><button class="button quiet" id="dc-page-prev" type="button" disabled>Previous</button><span id="dc-page-info">0 photos</span><button class="button quiet" id="dc-page-next" type="button" disabled>Next</button></div>
      </div></section>
    </div>
    <dialog class="dc-viewer" id="dc-viewer" aria-labelledby="dc-viewer-title"><div class="dc-viewer-header"><div><h2 id="dc-viewer-title">Original photo</h2><p class="dc-hint">Native file · preview guides are not included</p></div><button class="button quiet" id="dc-viewer-close" type="button">Close</button></div><div class="dc-viewer-body"><div class="dc-viewer-image"><img id="dc-viewer-image" alt="Selected original capture photo"></div><div class="dc-viewer-details"><dl id="dc-viewer-details"></dl><a class="button quiet" id="dc-viewer-download" download>Download original</a><p class="dc-warning" id="dc-viewer-warnings"></p></div></div></dialog>
    ${standalone ? '<dialog class="dc-auth" id="dc-auth" aria-labelledby="dc-auth-title"><form id="dc-auth-form"><h2 id="dc-auth-title">Sign in to Camera Capture</h2><p class="dc-hint">Use your LAN operator access token. Google credentials are configured on the server, never entered here.</p><label>Operator access token<input id="dc-auth-token" type="password" autocomplete="off" required></label><button class="button primary" type="submit">Sign in</button><p id="dc-auth-message" class="dc-feedback" role="status"></p></form></dialog>' : ''}`;

  const el = id => root.querySelector(`#dc-${id}`);
  let active = standalone, status = null, sessionId = null, sessions = [], items = [];
  let offset = 0, total = 0, selected = new Set(), mutationBusy = false, statusBusy = false, galleryBusy = false;
  let pollTimer = null, previewTimer = null, csrf = null, lanEnabled = false, securityReady = !standalone;
  let lastGalleryCapture = -1, drive = {}, lastDrivePoll = 0, metadataLoadedFor = null;
  let requestGeneration = 0, audioContext = null;

  function runActive(value = status) {
    return ["countdown", "running", "paused", "capturing"].includes(value?.run?.state);
  }
  function text(id, value) { el(id).textContent = value == null ? "—" : String(value); }
  function number(value) { return value == null || !Number.isFinite(Number(value)) ? null : Number(value); }
  function decimal(value, suffix = "") { const result = number(value); return result == null ? "Not measured" : `${result.toFixed(1)}${suffix}`; }
  function timestamp(value) { if (!value) return "—"; const date = new Date(value); return Number.isFinite(date.valueOf()) ? date.toLocaleString() : String(value); }
  function itemId(item) { return String(item.image_id ?? item.item_id ?? item.id ?? ""); }
  function itemName(item) { return String(item.filename ?? item.local_filename ?? item.local_path ?? itemId(item)); }
  function itemTime(item) { return item.captured_utc ?? item.timestamp ?? item.captured_at ?? item.utc_timestamp; }
  function syncState(item) { return String(item.sync_status ?? item.drive_status ?? item.drive?.status ?? "saved_locally"); }
  function syncLabel(state) { return ({saved_locally: "Saved locally", saved_local: "Saved locally", local: "Saved locally", queued: "Queued", uploading: "Uploading", synced: "Synced to Drive", synced_to_drive: "Synced to Drive", failed: "Failed", not_connected: "Drive not connected"})[state] || state.replaceAll("_", " "); }
  function warningList(item) {
    const warnings = item.quality?.warnings ?? item.quality_warnings ?? item.warnings ?? [];
    return (Array.isArray(warnings) ? warnings : [warnings]).map(value => typeof value === "string" ? value.replaceAll("_", " ") : String(value?.message ?? value?.code ?? "Quality warning"));
  }
  function imageUrl(item, thumbnail = false) { return `${API}/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId(item))}/image${thumbnail ? "?thumbnail=true" : ""}`; }
  function feedback(message, error = false) { text("feedback", message); el("feedback").dataset.error = String(error); }
  function driveFeedback(message, error = false) { text("drive-feedback", message); el("drive-feedback").dataset.error = String(error); }
  function errorText(error) { return error instanceof Error ? error.message : String(error); }

  async function request(path, method = "GET", payload) {
    const headers = {Accept: "application/json"};
    if (method !== "GET") {
      headers["X-Capture-Request"] = "1";
      if (payload !== undefined) headers["Content-Type"] = "application/json";
      if (standalone && csrf) headers["X-CSRF-Token"] = csrf;
    }
    const response = await window.fetch(`${API}${path}`, {method, headers, cache: "no-store", credentials: "same-origin", ...(payload === undefined ? {} : {body: JSON.stringify(payload)})});
    let data = {};
    try { data = await response.json(); } catch (_) { /* Report the actual HTTP state below. */ }
    if (!response.ok) {
      if (standalone && response.status === 401) { securityReady = false; csrf = null; showLogin(); }
      const detail = data.detail ?? data.message ?? `Capture request failed (HTTP ${response.status})`;
      const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(value => value.msg ?? String(value)).join("; ") : String(detail.message ?? detail.code ?? JSON.stringify(detail));
      const error = new Error(message); error.status = response.status; throw error;
    }
    return data;
  }

  async function mutate(path, payload, message, method = "POST") {
    if (mutationBusy) return null;
    mutationBusy = true; renderControls();
    try {
      const data = await request(path, method, payload);
      if (message) feedback(message);
      return data;
    } catch (error) { feedback(errorText(error), true); return null; }
    finally { mutationBusy = false; await refreshStatus(); renderControls(); }
  }

  function metadata() {
    return {session_name: el("session-name").value.trim(), operator: el("operator").value.trim(), source_code: el("source").value.trim(), batch_id: el("batch").value.trim(), specimen_id: el("specimen").value.trim(), specimen_confirmed: el("specimen-confirmed").checked, camera_setup: el("setup").value.trim(), lighting: el("lighting").value.trim(), background: el("background").value.trim(), conveyor: el("conveyor").value, angle: el("angle").value.trim(), provisional_grade: el("grade").value, notes: el("notes").value.trim(), consent: el("consent").checked};
  }
  function fillMetadata(value = {}) {
    for (const [id, key] of Object.entries({"session-name": "session_name", operator: "operator", source: "source_code", batch: "batch_id", specimen: "specimen_id", setup: "camera_setup", lighting: "lighting", background: "background", angle: "angle", notes: "notes"})) el(id).value = value[key] ?? "";
    el("consent").checked = Boolean(value.consent);
    el("specimen-confirmed").checked = Boolean(value.specimen_confirmed);
    el("grade").value = grades.includes(value.provisional_grade) ? value.provisional_grade : "Unknown";
    el("conveyor").value = ["on", "off", "unknown"].includes(value.conveyor) ? value.conveyor : "unknown";
  }
  function renderSessions() {
    const select = el("session-select"); select.replaceChildren();
    const empty = document.createElement("option"); empty.value = ""; empty.textContent = sessions.length ? "Select a collection session" : "Create a collection session below"; select.append(empty);
    for (const session of sessions) {
      const id = String(session.session_id ?? session.id ?? ""); if (!id) continue;
      const option = document.createElement("option"); option.value = id;
      option.textContent = `${session.metadata?.session_name || session.session_name || id} · ${timestamp(session.created_utc ?? session.created_at)}`;
      select.append(option);
    }
    if (sessionId && !sessions.some(session => String(session.session_id ?? session.id) === sessionId)) { const option = document.createElement("option"); option.value = sessionId; option.textContent = sessionId; select.append(option); }
    select.value = sessionId ?? "";
    for (const format of ["zip", "csv", "json"]) { const link = el(`export-${format}`); link.hidden = !sessionId; if (sessionId) link.href = `${API}/sessions/${encodeURIComponent(sessionId)}/export?format=${format}`; }
  }
  async function loadSessions() {
    try {
      const result = await request("/sessions"); sessions = Array.isArray(result) ? result : result.sessions ?? [];
      renderSessions();
      if (sessionId && metadataLoadedFor !== sessionId) {
        const session = sessions.find(value => String(value.session_id ?? value.id) === sessionId);
        if (session) { fillMetadata(session.metadata ?? session); metadataLoadedFor = sessionId; }
      }
    } catch (error) { feedback(errorText(error), true); }
  }
  function renderControls() {
    const cameraOpen = status?.camera?.state === "open";
    const manual = Boolean(status?.manual_available && sessionId && securityReady);
    el("snapshot").disabled = mutationBusy || !manual;
    el("camera-open").disabled = mutationBusy || cameraOpen || !securityReady;
    el("camera-close").disabled = mutationBusy || !cameraOpen;
    for (const id of ["device", "backend", "width", "height"]) el(id).disabled = mutationBusy || cameraOpen;
    for (const id of ["session-select", "create-session"]) el(id).disabled = mutationBusy || runActive() || !securityReady;
    el("save-metadata").disabled = mutationBusy || !sessionId || !securityReady;
    el("run-start").disabled = mutationBusy || !manual || runActive();
    el("run-pause").disabled = mutationBusy || !["running", "countdown", "capturing"].includes(status?.run?.state);
    el("run-resume").disabled = mutationBusy || status?.run?.state !== "paused";
    el("run-stop").disabled = mutationBusy || !runActive();
    for (const id of ["countdown", "interval", "duration", "target", "custom-count"]) el(id).disabled = mutationBusy || runActive();
    el("bulk-save").disabled = mutationBusy || selected.size === 0 || !sessionId;
    if (manual) text("manual-help", "One click saves one fresh original. No timer required. Space captures when you are not typing.");
    else text("manual-help", status?.manual_unavailable_reason || status?.camera?.error?.detail || (typeof status?.camera?.error === "string" ? status.camera.error : null) || (!sessionId ? "Create or select a collection session first. No automatic timer is required." : "Open an available capture camera with a fresh frame before taking a photo."));
    renderDriveControls();
  }
  function renderStatus() {
    if (!status) { renderControls(); return; }
    const camera = status.camera ?? {}, readbacks = camera.readbacks ?? {}, run = status.run ?? {}, stats = status.stats ?? {};
    const state = camera.state ?? "closed";
    text("camera-state", `Camera ${state}`); el("camera-state").dataset.state = state;
    text("readback-device", camera.device_index == null && readbacks.device_index == null ? "—" : `Index ${camera.device_index ?? readbacks.device_index} · ${camera.backend ?? readbacks.backend ?? "backend unavailable"}`);
    const width = camera.width ?? readbacks.width, height = camera.height ?? readbacks.height;
    text("readback-size", width && height ? `${width} × ${height} px` : "—");
    text("camera-fps", decimal(status.camera_fps, " FPS")); text("capture-fps", decimal(status.capture_fps, " photos/s"));
    const controls = ["exposure", "focus", "gain", "auto_exposure", "auto_focus"].filter(key => readbacks[key] != null).map(key => `${key.replaceAll("_", " ")}: ${readbacks[key]}`);
    text("readback-controls", controls.join(" · ") || "Not supported / not measured");
    text("disk-free", stats.disk_free_bytes == null ? "Unavailable" : `${(Number(stats.disk_free_bytes) / (1024 ** 3)).toFixed(2)} GB free`);
    text("run-state", run.state ?? "idle"); el("run-state").dataset.state = run.state ?? "idle";
    const countdown = number(run.countdown_remaining);
    text("countdown-state", run.state === "countdown" ? `First shot in ${Math.max(0, Math.ceil(countdown ?? 0))} seconds` : run.state === "paused" ? "Automatic collection paused" : ["running", "capturing"].includes(run.state) ? "Automatic collection running" : "No automatic run");
    text("run-progress", `${run.scheduled ?? 0} scheduled · ${run.captured ?? 0} automatic saved${run.target_count ? ` / ${run.target_count} target` : ""}`);
    const next = number(run.next_shot_in ?? run.next_shot_seconds);
    text("run-timing", `Next shot: ${next == null ? "—" : `${Math.max(0, next).toFixed(1)}s`} · late: ${run.late ?? 0} · skipped: ${run.skipped ?? 0}`);
    const last = status.last_capture_utc ?? stats.last_capture_utc ?? run.last_capture_utc;
    if (last) text("last-capture", `Last saved: ${timestamp(last)}`);
    for (const [id, value] of Object.entries({frames: stats.frames ?? stats.raw_frames, manual: stats.manual ?? stats.manual_photos, reviewed: stats.reviewed ?? stats.reviewed_photos, specimens: stats.confirmed_specimens ?? stats.unique_specimens_confirmed, skipped: run.skipped ?? stats.skipped, backlog: stats.backlog ?? stats.upload_backlog})) text(`count-${id}`, value ?? 0);
    const counts = stats.provisional_grades ?? stats.specimens_per_provisional_grade;
    text("provisional-counts", counts && Object.keys(counts).length ? `Confirmed specimens by provisional tag: ${Object.entries(counts).map(([key, value]) => `${key}: ${value}`).join(" · ")}. Tags are operator notes, not expert ground truth.` : "Provisional tags are operator notes, not expert ground truth.");
    if (camera.error || camera.isolation_note || status.last_error?.detail) { text("isolation", camera.error?.detail || (typeof camera.error === "string" ? camera.error : null) || status.last_error?.detail || camera.isolation_note); el("isolation").hidden = false; }
    renderControls();
    if (active && state === "open" && !document.hidden) startPreview(); else stopPreview();
  }
  async function refreshStatus() {
    if (statusBusy || !securityReady) return;
    statusBusy = true;
    try {
      const next = await request("/status"); status = next;
      const nextId = next.session_id == null ? null : String(next.session_id);
      if (nextId !== sessionId) { sessionId = nextId; selected.clear(); items = []; total = 0; offset = 0; metadataLoadedFor = null; lastGalleryCapture = -1; renderGallery(); renderSessions(); await loadSessions(); }
      renderStatus();
      const count = next.stats?.frames ?? next.stats?.raw_frames;
      if (active && sessionId && count !== lastGalleryCapture && !galleryBusy) { await loadItems(); lastGalleryCapture = count; }
      if (active && Date.now() - lastDrivePoll > 5000) await loadDrive();
    } catch (error) { status = null; stopPreview(); renderControls(); feedback(errorText(error), true); }
    finally { statusBusy = false; }
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!active && !runActive()) return;
    pollTimer = setTimeout(async () => { await refreshStatus(); schedulePoll(); }, 800);
  }
  function startPreview() {
    if (previewTimer != null || el("preview").hasAttribute("data-loading")) return;
    const img = el("preview"); img.setAttribute("data-loading", "true");
    img.src = `${API}/preview.jpg?v=${Date.now()}`;
  }
  function schedulePreview(delay) {
    el("preview").removeAttribute("data-loading"); clearTimeout(previewTimer);
    previewTimer = setTimeout(() => { previewTimer = null; if (active && !document.hidden && status?.camera?.state === "open") startPreview(); }, delay);
  }
  function stopPreview() {
    clearTimeout(previewTimer); previewTimer = null;
    el("preview").removeAttribute("data-loading"); el("preview").removeAttribute("src"); el("preview").hidden = true; el("preview-empty").hidden = false;
    text("preview-state", "No camera preview attached");
  }
  el("preview").addEventListener("load", () => { el("preview").hidden = false; el("preview-empty").hidden = true; text("preview-state", `Preview · ${el("preview").naturalWidth} × ${el("preview").naturalHeight} px`); schedulePreview(300); });
  el("preview").addEventListener("error", () => { if (!el("preview").getAttribute("src")) return; el("preview").hidden = true; el("preview-empty").hidden = false; text("preview-state", "Preview unavailable · reconnecting"); schedulePreview(1200); });

  function selectionChanged() {
    text("selection-count", `${selected.size} selected`);
    el("select-all").checked = items.length > 0 && items.every(item => selected.has(itemId(item)));
    el("select-all").indeterminate = items.some(item => selected.has(itemId(item))) && !el("select-all").checked;
    renderControls();
  }
  function renderGallery() {
    const gallery = el("gallery"); gallery.replaceChildren();
    el("gallery-empty").hidden = items.length > 0;
    for (const item of items) {
      const card = document.createElement("article"); card.className = "dc-photo"; card.dataset.excluded = String(item.metadata?.review_state === "exclude" || item.review_state === "exclude");
      const top = document.createElement("div"); top.className = "dc-photo-top";
      const selectLabel = document.createElement("label"); selectLabel.className = "dc-check";
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = selected.has(itemId(item)); checkbox.setAttribute("aria-label", `Select ${itemName(item)}`);
      checkbox.addEventListener("change", () => { if (checkbox.checked) selected.add(itemId(item)); else selected.delete(itemId(item)); selectionChanged(); });
      selectLabel.append(checkbox, document.createTextNode("Select"));
      const sync = document.createElement("span"); sync.className = "dc-sync"; sync.dataset.state = syncState(item); sync.textContent = syncLabel(syncState(item)); top.append(selectLabel, sync);
      const open = document.createElement("button"); open.className = "dc-photo-open"; open.type = "button"; open.setAttribute("aria-label", `View original ${itemName(item)}`);
      const img = document.createElement("img"); img.src = imageUrl(item, true); img.loading = "lazy"; img.alt = `Captured ${item.capture_mode ?? "raw"} photo`; open.append(img); open.addEventListener("click", () => openViewer(item));
      const name = document.createElement("p"); name.className = "dc-photo-name"; name.textContent = itemName(item);
      const info = document.createElement("p"); info.className = "dc-photo-info"; info.textContent = `${timestamp(itemTime(item))} · ${item.width ?? "?"} × ${item.height ?? "?"} · ${item.capture_mode ?? "raw"} · ${item.metadata?.provisional_grade ?? item.provisional_grade ?? "Unknown"} (provisional) · ${item.metadata?.review_state ?? item.review_state ?? "review"}`;
      const warnings = document.createElement("p"); warnings.className = "dc-warning"; warnings.textContent = warningList(item).join(" · ");
      card.append(top, open, name, info, warnings); gallery.append(card);
    }
    text("page-info", total ? `${offset + 1}–${Math.min(offset + items.length, total)} of ${total} photos` : "0 photos");
    el("page-prev").disabled = offset === 0 || galleryBusy; el("page-next").disabled = offset + PAGE_SIZE >= total || galleryBusy;
    selectionChanged();
  }
  async function loadItems() {
    if (galleryBusy) return;
    if (!sessionId) { items = []; total = 0; renderGallery(); return; }
    const generation = ++requestGeneration, requestedSession = sessionId;
    galleryBusy = true;
    try {
      const result = await request(`/sessions/${encodeURIComponent(requestedSession)}/items?limit=${PAGE_SIZE}&offset=${offset}`);
      if (requestedSession !== sessionId || generation !== requestGeneration) return;
      items = Array.isArray(result) ? result : result.items ?? []; total = result.total ?? items.length;
      renderGallery();
    } catch (error) { feedback(errorText(error), true); }
    finally { galleryBusy = false; el("page-prev").disabled = offset === 0; el("page-next").disabled = offset + PAGE_SIZE >= total; }
  }
  function openViewer(item) {
    const viewer = el("viewer"); text("viewer-title", itemName(item));
    el("viewer-image").src = imageUrl(item); el("viewer-image").alt = `Original ${itemName(item)}`;
    el("viewer-download").href = imageUrl(item); el("viewer-download").download = itemName(item);
    const detail = el("viewer-details"); detail.replaceChildren();
    const values = {"Captured (UTC)": itemTime(item), "Native dimensions": `${item.width ?? "?"} × ${item.height ?? "?"} px`, "Capture mode": item.capture_mode, "Camera frame ID": item.frame_id ?? item.camera_frame_id, "Image ID": itemId(item), "SHA-256": item.sha256, "Provisional operator tag": item.metadata?.provisional_grade ?? item.provisional_grade ?? "Unknown", "Review state": item.metadata?.review_state ?? item.review_state ?? "review", "Source / batch": [item.metadata?.source_code, item.metadata?.batch_id].filter(Boolean).join(" / ") || "Not recorded", "Physical specimen": item.metadata?.specimen_id ? `${item.metadata.specimen_id}${item.metadata.specimen_confirmed ? " · confirmed by operator" : " · unconfirmed"}` : "Not confirmed", "Sync state": syncLabel(syncState(item)), "Drive file ID": item.drive_file_id ?? item.remote_file_id, "Focus score (diagnostic)": item.quality?.focus_score ?? item.quality?.focus_variance, "Exposure / clipping (diagnostic)": JSON.stringify(item.quality?.exposure ?? {underexposed_ratio: item.quality?.underexposed_ratio, overexposed_ratio: item.quality?.overexposed_ratio, clipped_ratio: item.quality?.clipped_ratio}), "Notes": item.metadata?.notes};
    for (const [key, value] of Object.entries(values)) { if (value == null || value === "{}") continue; const group = document.createElement("div"), term = document.createElement("dt"), description = document.createElement("dd"); term.textContent = key; description.textContent = String(value); group.append(term, description); detail.append(group); }
    text("viewer-warnings", warningList(item).join(" · ") || "Quality checks are diagnostic only. No warning proves true grade or specimen identity.");
    if (!viewer.open) viewer.showModal();
  }
  function shutterFeedback() {
    if (el("flash-toggle").checked) { el("preview-wrap").classList.add("dc-flash"); setTimeout(() => el("preview-wrap").classList.remove("dc-flash"), 100); }
    if (el("sound-toggle").checked) {
      try { const Context = window.AudioContext || window.webkitAudioContext; if (!Context) return; audioContext ??= new Context(); const oscillator = audioContext.createOscillator(), gain = audioContext.createGain(); oscillator.frequency.value = 740; gain.gain.value = .025; oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start(); oscillator.stop(audioContext.currentTime + .06); } catch (_) { /* Sound is optional and has no bearing on the save. */ }
    }
  }
  async function snapshot() {
    if (el("snapshot").disabled || mutationBusy) return;
    const data = await mutate("/snapshot", {}, null);
    if (!data) return;
    const item = data.item ?? data.capture ?? data;
    el("last-save").hidden = false; text("last-name", itemName(item)); text("last-sync", syncLabel(syncState(item))); text("last-capture", `Last saved: ${timestamp(itemTime(item))}`);
    if (itemId(item)) el("last-thumb").src = imageUrl(item, true);
    feedback(`Saved locally: ${itemName(item)} · ${syncLabel(syncState(item))}`);
    shutterFeedback(); await loadItems();
  }

  function renderDriveControls() {
    const connected = Boolean(drive.connected), canUpload = Boolean(drive.can_upload);
    el("drive-connect").disabled = mutationBusy || !drive.oauth_configured || !drive.destination_configured;
    for (const id of ["drive-test", "drive-write-test"]) el(id).disabled = mutationBusy || !connected || !drive.destination_configured;
    for (const id of ["drive-sync", "drive-retry", "drive-auto"]) el(id).disabled = mutationBusy || !connected || !canUpload;
    el("drive-pause").disabled = mutationBusy || !connected;
  }
  function renderDrive() {
    const state = drive.connected ? (drive.can_upload ? "Connected" : "Connected · check folder access") : "Not connected";
    text("drive-state", state);
    text("drive-message", drive.setup_message || (drive.connected ? "Local files remain the durable source. Review the session before syncing." : "Drive is not connected. Configure the desktop OAuth client on the server, then connect with Google consent. Photos remain saved locally."));
    el("drive-auto").checked = Boolean(drive.auto_sync);
    text("drive-pause", drive.paused ? "Resume sync" : "Pause sync");
    let folder = null; try { const url = new URL(drive.folder_url); if (url.protocol === "https:" && url.hostname === "drive.google.com") folder = url.href; } catch (_) { /* Absent destination. */ }
    el("drive-folder").hidden = !folder; if (folder) el("drive-folder").href = folder;
    renderDriveControls();
  }
  async function loadDrive() {
    lastDrivePoll = Date.now();
    try { drive = await request("/drive/status"); renderDrive(); }
    catch (error) { drive = {}; renderDrive(); driveFeedback(errorText(error), true); }
  }
  async function driveAction(path, payload, message, method = "POST") {
    if (mutationBusy) return null;
    mutationBusy = true; renderControls();
    try { const result = await request(`/drive/${path}`, method, payload); if (message) driveFeedback(message); return result; }
    catch (error) { driveFeedback(errorText(error), true); return null; }
    finally { mutationBusy = false; await loadDrive(); await refreshStatus(); renderControls(); }
  }

  el("grid-toggle").addEventListener("change", () => { el("grid").hidden = !el("grid-toggle").checked; });
  el("snapshot").addEventListener("click", () => { void snapshot(); });
  el("camera-open").addEventListener("click", async () => {
    const payload = {device_index: Number(el("device").value), width: Number(el("width").value), height: Number(el("height").value), backend: el("backend").value};
    if (!Number.isInteger(payload.device_index) || payload.device_index < 0 || payload.device_index > 11 || !Number.isInteger(payload.width) || payload.width < 64 || payload.width > 4096 || !Number.isInteger(payload.height) || payload.height < 64 || payload.height > 4096) { feedback("Use a camera index from 0 to 11 and frame dimensions from 64 to 4096 pixels.", true); return; }
    await mutate("/camera/start", payload, "Capture camera opened. Check actual readbacks before collecting.");
  });
  el("camera-close").addEventListener("click", () => { void mutate("/camera/stop", {}, "Capture camera closed. Saved photos remain available."); });
  el("metadata-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (runActive()) return;
    const data = await mutate("/sessions", {metadata: metadata()}, "Collection session created. Manual capture needs no automatic timer.");
    if (data) { const id = data.session_id ?? data.id ?? data.session?.session_id; if (id) sessionId = String(id); metadataLoadedFor = null; offset = 0; selected.clear(); await loadSessions(); await loadItems(); renderControls(); }
  });
  el("save-metadata").addEventListener("click", async () => { if (!sessionId) return; await mutate(`/sessions/${encodeURIComponent(sessionId)}/metadata`, {metadata: metadata()}, "Session metadata saved. Existing original files remain unchanged.", "PATCH"); metadataLoadedFor = sessionId; await loadSessions(); });
  el("session-select").addEventListener("change", async () => { const id = el("session-select").value; if (!id || runActive()) return; const data = await mutate(`/sessions/${encodeURIComponent(id)}/select`, {}, "Collection session selected."); if (data) { sessionId = id; offset = 0; selected.clear(); metadataLoadedFor = null; await loadSessions(); await loadItems(); } });
  el("sessions-refresh").addEventListener("click", () => { void loadSessions(); });
  el("target").addEventListener("change", () => { el("custom-wrap").hidden = el("target").value !== "custom"; });
  el("run-start").addEventListener("click", async () => {
    const target = el("target").value, targetCount = target === "custom" ? Number(el("custom-count").value) : target ? Number(target) : null;
    if (targetCount != null && (!Number.isInteger(targetCount) || targetCount < 1 || targetCount > 10000)) { feedback("Choose a photo count from 1 to 10,000.", true); return; }
    await mutate("/session/start", {session_id: sessionId, countdown: Number(el("countdown").value), interval: Number(el("interval").value), duration: el("duration").value ? Number(el("duration").value) : null, target_count: targetCount}, "Automatic collection requested. Scheduling and saved-frame counts are reported by the server."); schedulePoll();
  });
  for (const action of ["pause", "resume", "stop"]) el(`run-${action}`).addEventListener("click", () => { void mutate(`/session/${action}`, {}, action === "stop" ? "Automatic collection stopped. Manual capture and saved files remain available." : `Automatic collection ${action === "pause" ? "paused" : "resumed"}.`); });
  el("gallery-refresh").addEventListener("click", () => { void loadItems(); });
  el("select-all").addEventListener("change", () => { for (const item of items) { if (el("select-all").checked) selected.add(itemId(item)); else selected.delete(itemId(item)); } renderGallery(); });
  el("page-prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE_SIZE); void loadItems(); });
  el("page-next").addEventListener("click", () => { if (offset + PAGE_SIZE < total) { offset += PAGE_SIZE; void loadItems(); } });
  el("bulk-save").addEventListener("click", async () => {
    if (!sessionId || !selected.size) return;
    const update = {};
    if (el("bulk-review").value) update.review_state = el("bulk-review").value;
    if (el("bulk-grade").value) update.provisional_grade = el("bulk-grade").value;
    if (el("bulk-notes").value.trim()) update.notes = el("bulk-notes").value.trim();
    if (el("bulk-specimen").value.trim()) { update.specimen_id = el("bulk-specimen").value.trim(); update.specimen_confirmed = el("bulk-confirmed").checked; }
    if (!Object.keys(update).length) { feedback("Choose a review state, provisional tag, note or specimen ID for the selected photos.", true); return; }
    const data = await mutate(`/sessions/${encodeURIComponent(sessionId)}/items`, {item_ids: [...selected], metadata: update}, "Selected photo metadata updated. Raw originals retained.", "PATCH");
    if (data) { selected.clear(); await loadItems(); }
  });
  el("viewer-close").addEventListener("click", () => { el("viewer").close(); });
  el("viewer").addEventListener("close", () => { el("viewer-image").removeAttribute("src"); });
  el("drive-connect").addEventListener("click", async () => {
    const data = await driveAction("connect", {}, "Continue with Google consent in the new tab. Collection stays available locally.");
    if (!data?.authorization_url) return;
    try { const url = new URL(data.authorization_url); if (url.protocol !== "https:" || url.hostname !== "accounts.google.com") throw new Error("Unexpected Google authorization destination."); el("drive-consent").href = url.href; el("drive-consent").hidden = false; window.open(url.href, "_blank", "noopener,noreferrer"); }
    catch (error) { driveFeedback(errorText(error), true); }
  });
  el("drive-test").addEventListener("click", async () => { const result = await driveAction("test", {write_test: false}, null); if (result) driveFeedback(result.message || result.detail || "Folder access checked. No test file was uploaded."); });
  el("drive-write-test").addEventListener("click", async () => {
    if (!window.confirm("Upload one generated test image to the configured Drive folder to verify write access? Existing files will remain unchanged.")) return;
    const result = await driveAction("test", {write_test: true}, null);
    if (result) {
      const fileId = result.test_file_id ?? result.file_id;
      driveFeedback(result.write_test_verified && fileId ? `Write access verified · Drive test file ID: ${fileId}` : result.message || result.detail || "Write access was not confirmed. Check folder permission and retry.", !result.write_test_verified);
    }
  });
  el("drive-auto").addEventListener("change", async () => { const wanted = el("drive-auto").checked; await driveAction("settings", {auto_sync: wanted}, wanted ? "Automatic sync enabled for the configured destination." : "Automatic sync disabled. Local capture continues.", "PATCH"); });
  for (const action of ["sync", "retry", "pause"]) el(`drive-${action}`).addEventListener("click", async () => {
    const requestedAction = action === "pause" && drive.paused ? "resume" : action;
    const result = await driveAction(requestedAction, {}, null);
    if (result) {
      const counts = result.processed != null || result.synced != null || result.failed != null ? `Processed: ${result.processed ?? 0} · synced: ${result.synced ?? 0} · failed: ${result.failed ?? 0}.` : null;
      const message = counts || result.message || result.detail || (requestedAction === "pause" ? "Drive sync paused." : requestedAction === "resume" ? "Drive sync resumed." : "Sync requested. Photos show Synced to Drive only after a confirmed upload.");
      driveFeedback(message, Number(result.failed ?? 0) > 0);
    }
    await loadItems();
  });

  function keyboardSafe(event) {
    const target = event.target;
    return !event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey && !target?.isContentEditable && !target?.closest?.("input,textarea,select,button,a,[contenteditable],dialog,[role=dialog]") && !root.querySelector("dialog[open]");
  }
  document.addEventListener("keydown", event => {
    if (!active || !keyboardSafe(event)) return;
    if (event.code === "Space" && !el("snapshot").disabled) { event.preventDefault(); void snapshot(); }
    if (event.key === "Escape" && !el("run-stop").disabled) { event.preventDefault(); void mutate("/session/stop", {}, "Automatic collection stopped."); }
  });
  window.addEventListener("beforeunload", event => { if (runActive() || mutationBusy) { event.preventDefault(); event.returnValue = ""; } });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopPreview(); else if (active) { void refreshStatus(); schedulePoll(); } });

  function showLogin() { const dialog = el("auth"); if (dialog && !dialog.open) dialog.showModal(); }
  async function initializeSecurity() {
    if (!standalone) return;
    try {
      const response = await window.fetch("/api/auth/mode", {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw new Error("Capture security profile is unavailable.");
      lanEnabled = Boolean((await response.json()).lan_security);
      if (lanEnabled) {
        const session = await window.fetch("/api/auth/session", {cache: "no-store", credentials: "same-origin"});
        if (!session.ok) { showLogin(); return; }
        csrf = (await session.json()).csrf_token;
      }
      securityReady = true; await loadSessions(); await refreshStatus(); schedulePoll();
    } catch (error) { feedback(errorText(error), true); }
  }
  if (standalone) {
    el("auth").addEventListener("cancel", event => { event.preventDefault(); });
    el("auth-form").addEventListener("submit", async event => {
      event.preventDefault(); const token = el("auth-token").value; el("auth-token").value = ""; text("auth-message", "Signing in…");
      try {
        const response = await window.fetch("/api/auth/login", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token})});
        const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Sign-in failed.");
        csrf = data.csrf_token; securityReady = true; text("auth-message", ""); el("auth").close(); await loadSessions(); await refreshStatus(); schedulePoll();
      } catch (error) { text("auth-message", errorText(error)); }
    });
  }
  window.TambanCapture = {
    onView(view) {
      active = view === "capture";
      if (active) { void loadSessions(); void refreshStatus(); schedulePoll(); }
      else { stopPreview(); schedulePoll(); }
    },
    canNavigate(view) {
      if (!active || view === "capture" || (!runActive() && !mutationBusy)) return true;
      return window.confirm("Leave Camera Capture? The collection run continues on the server. Stop it here first if you want collection to end.");
    },
  };
  renderDrive(); renderControls();
  if (standalone) void initializeSecurity();
})();
