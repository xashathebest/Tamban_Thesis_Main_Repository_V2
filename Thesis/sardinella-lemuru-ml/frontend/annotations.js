/* Annotation management is intentionally separate from the inspection application. */
(() => {
  "use strict";
  const STATUS = {not_annotated: "Not Annotated", ai_annotated: "AI Annotated", needs_review: "Needs Review", approved: "Approved", edited: "Edited", rejected: "Rejected", needs_correction: "Needs Correction"};
  const COLORS = ["#287db0", "#d1832c", "#548345", "#b55d83", "#7b66b5", "#288f8a", "#bf653c", "#699b36", "#bb5281", "#607eac", "#9b7c38", "#8267a4"];
  const copy = value => JSON.parse(JSON.stringify(value));
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const classColor = (id, registry = []) => {
    const registered = registry?.find(category => Number(category.id ?? category.class_id) === Number(id))?.color;
    return typeof registered === "string" && /^#[0-9a-f]{6}$/i.test(registered) ? registered : COLORS[Math.abs(Number(id) || 0) % COLORS.length];
  };
  function polygons(value, width, height) {
    if (!Array.isArray(value) || !value.length) throw new Error("Enter at least one polygon.");
    return value.map(ring => {
      if (!Array.isArray(ring) || ring.length < 6 || ring.length % 2 || !ring.every(Number.isFinite)) throw new Error("Each polygon needs at least three finite [x, y] points.");
      if (ring.some((n, i) => n < 0 || n > (i % 2 ? height : width))) throw new Error("Polygon coordinates must be inside the image.");
      let twiceArea = 0;
      for (let i = 0; i < ring.length; i += 2) { const j = (i + 2) % ring.length; twiceArea += ring[i] * ring[j + 1] - ring[j] * ring[i + 1]; }
      if (Math.abs(twiceArea) < 0.01) throw new Error("A polygon must enclose an area.");
      return ring.slice();
    });
  }
  function polygonBox(rings) {
    const xs = [], ys = [];
    rings.forEach(ring => { for (let i = 0; i < ring.length; i += 2) { xs.push(ring[i]); ys.push(ring[i + 1]); } });
    const x = Math.min(...xs), y = Math.min(...ys);
    return [x, y, Math.max(...xs) - x, Math.max(...ys) - y];
  }
  function decodeRLE(rle) {
    if (!rle || !Array.isArray(rle.size) || rle.size.length !== 2 || !rle.size.every(v => Number.isSafeInteger(v) && v > 0)) throw new Error("Invalid RLE mask dimensions.");
    const [height, width] = rle.size, total = height * width;
    if (!Number.isSafeInteger(total) || total > 100000000) throw new Error("This mask is too large to preview safely. The saved RLE remains intact.");
    let counts;
    if (Array.isArray(rle.counts)) counts = rle.counts.slice();
    else if (typeof rle.counts === "string") {
      counts = [];
      for (let p = 0; p < rle.counts.length;) {
        let x = 0, shift = 0, c;
        do {
          if (p >= rle.counts.length || shift > 50) throw new Error("Invalid compressed RLE.");
          c = rle.counts.charCodeAt(p++) - 48;
          if (c < 0 || c > 63) throw new Error("Invalid compressed RLE character.");
          x += (c & 31) * 2 ** shift; shift += 5;
        } while (c & 32);
        if (c & 16) x -= 2 ** shift;
        if (counts.length > 2) x += counts[counts.length - 2];
        counts.push(x);
      }
    } else throw new Error("Unsupported RLE counts. The saved mask remains intact.");
    if (!counts.every(v => Number.isSafeInteger(v) && v >= 0) || counts.reduce((a, b) => a + b, 0) !== total) throw new Error("RLE runs do not match the saved mask dimensions.");
    return {width, height, counts};
  }
  function maskContains(segmentation, x, y, width, height) {
    if (x < 0 || y < 0 || x >= width || y >= height || !segmentation) return false;
    if (Array.isArray(segmentation)) return segmentation.some(ring => {
      let inside = false;
      for (let i = 0, j = ring.length - 2; i < ring.length; j = i, i += 2) {
        const xi = ring[i], yi = ring[i + 1], xj = ring[j], yj = ring[j + 1];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
      }
      return inside;
    });
    const decoded = decodeRLE(segmentation), index = Math.floor(x / width * decoded.width) * decoded.height + Math.floor(y / height * decoded.height);
    let offset = 0, on = false;
    for (const count of decoded.counts) { offset += count; if (index < offset) return on; on = !on; }
    return false;
  }
  function fishAssociation(annotation, fishId, annotations, classDefinitions) {
    const kinds = new Map(classDefinitions.map(category => [category.id, category.kind]));
    if (kinds.get(annotation.class_id) === "whole_fish") return annotation.annotation_id;
    const parent = String(fishId || "").trim();
    if (!parent) return null;
    if (!annotations.some(item => String(item.annotation_id) === parent && kinds.get(item.class_id) === "whole_fish" && item.status !== "rejected")) throw new Error("Choose an existing whole-fish annotation ID, or leave the association unassigned.");
    return parent;
  }
  function drawingTarget(drawing, annotations) {
    const target = annotations.find(annotation => String(annotation.annotation_id) === String(drawing.replace));
    if (!target) throw new Error("The annotation selected for redrawing is no longer available. Cancel this drawing and select it again.");
    return target;
  }
  function validateExport(data) {
    if (!data || typeof data !== "object" || !data.dataset || !Array.isArray(data.images)) throw new Error("The server returned an invalid annotation dataset.");
    const imageIds = new Set(), annotationIds = new Set();
    for (const image of data.images) {
      if (!image.image_id || imageIds.has(String(image.image_id)) || typeof image.file_name !== "string" || !(image.width > 0) || !(image.height > 0) || !Array.isArray(image.annotations)) throw new Error("The export has an invalid or duplicate image record.");
      imageIds.add(String(image.image_id));
      for (const ann of image.annotations) {
        if (!ann.annotation_id || annotationIds.has(`${image.image_id}:${ann.annotation_id}`) || !Number.isInteger(ann.class_id) || !ann.class_name) throw new Error("The export has an invalid annotation identity or class.");
        annotationIds.add(`${image.image_id}:${ann.annotation_id}`);
        if (Array.isArray(ann.segmentation) && ann.segmentation.length) polygons(ann.segmentation, image.width, image.height);
        else if (ann.segmentation && !Array.isArray(ann.segmentation)) decodeRLE(ann.segmentation);
        if (ann.bbox != null && (!Array.isArray(ann.bbox) || ann.bbox.length !== 4 || !ann.bbox.every(Number.isFinite))) throw new Error("The export has an invalid bounding box.");
      }
    }
    return data;
  }
  if (typeof module !== "undefined" && module.exports) module.exports = {polygons, polygonBox, decodeRLE, maskContains, fishAssociation, drawingTarget, validateExport, escapeHTML, classColor};
  if (typeof document === "undefined") return;

  const $ = id => document.getElementById(id), API = "/api/annotation-library", NS = "http://www.w3.org/2000/svg";
  const state = {view: "dashboard", page: 1, pages: 1, total: 0, rows: [], selected: new Map(), image: null, liveImage: null, selectedAnnotation: null, dirty: false, editRevision: 0, savePromise: null, saveTimer: null, saveError: null, conflict: false, csrf: null, request: 0, opening: 0, readOnly: false, history: [], historyRequest: 0, historyLoading: false, undoStack: [], redoStack: [], editBaseline: null, objectReviewBusy: false, draft: null, zoom: 1, centerX: 0, centerY: 0, drag: null, drawing: null, masks: new Map(), maskWarnings: new Set(), busy: false};
  state.datasetId = ""; state.datasets = [];
  const VIEW = {dashboard: ["Annotation dashboard", "Review your progress and pick up where you left off."], annotate: ["Annotate & review", "Inspect masks, correct classes, and approve your annotations."], completed: ["Completed annotations", "Reopen saved work without running annotation again."], dataset: ["Your dataset", "Original images and saved annotation versions, in one place."], export: ["Export annotations", "Download saved annotations and the original images you need."]};
  const errorText = error => error instanceof Error ? error.message : String(error);
  const dateText = value => value ? new Date(value).toLocaleString(undefined, {month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit"}) : "Date unavailable";
  const statusOf = image => image.review_status === "needs_correction" ? "needs_correction" : image.status;
  const statusLabel = image => STATUS[statusOf(image)] || image.status || "Not Annotated";
  const mediaURL = (id, thumbnail = false) => `${API}/images/${encodeURIComponent(id)}/media${thumbnail ? "?thumbnail=true" : ""}`;
  const draftKey = id => `sardinella.annotation.draft.${id}`;
  function notice(message, error = false) { $("notice").textContent = message; $("notice").className = `notice${error ? " error" : ""}${message ? "" : " hidden"}`; }
  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.csrf && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) headers.set("X-CSRF-Token", state.csrf);
    const response = await fetch(path.startsWith("/api/") ? path : `${API}${path}`, {...options, headers, cache: "no-store", credentials: "same-origin"});
    if (!response.ok) {
      let detail;
      try { const body = await response.json(); detail = body.detail || body.error; } catch (_) { /* Preserve HTTP status when the response is not JSON. */ }
      if (response.status === 401 || response.status === 403) $("auth-message").classList.remove("hidden");
      const error = new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${response.status}).`); error.status = response.status; throw error;
    }
    return response;
  }
  const getJSON = async path => (await request(path)).json();
  const postJSON = async (path, body, method = "POST") => (await request(path, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})).json();
  function svgNode(tag, attrs = {}, text = null) { const node = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, String(v))); if (text != null) node.textContent = text; return node; }
  function badge(image) { return `<span class="badge ${escapeHTML(statusOf(image))}">${escapeHTML(statusLabel(image))}</span>`; }
  function setBusy(busy) { state.busy = busy; ["scan-button", "discover-button", "empty-discover", "upload-input"].forEach(id => { $(id).disabled = busy; }); }
  async function loadDatasets(preserve = false) {
    let data;
    try { data = await getJSON("/datasets"); }
    catch (error) { if (error.status !== 404) throw error; data = {datasets: [], primary_dataset_id: null}; }
    state.datasets = data.datasets || [];
    if (!preserve || state.datasetId && !state.datasets.some(item => String(item.id || item.dataset_id) === state.datasetId)) state.datasetId = data.primary_dataset_id || "";
    if (!$("dataset-select")) return;
    $("dataset-select").innerHTML = '<option value="">All saved datasets</option>' + state.datasets.map(item => `<option value="${escapeHTML(item.id || item.dataset_id)}">${escapeHTML(item.name || item.id || item.dataset_id)}${item.primary || String(item.id || item.dataset_id) === String(data.primary_dataset_id) ? " (Primary)" : ""}</option>`).join("");
    $("dataset-select").value = state.datasetId;
    const active = state.datasets.find(item => String(item.id || item.dataset_id) === state.datasetId);
    if ($("dataset-scope-note")) $("dataset-scope-note").textContent = active?.status === "importing" ? "Indexing source images. Completed saves remain available; refresh to see progress." : ["error", "failed", "needs_review"].includes(active?.status) ? "Source indexing needs attention. Existing saved annotations remain available; inspect the Dataset import report." : "Review and export the selected dataset. Source libraries remain separate.";
  }
  async function summary() {
    const data = await getJSON(`/summary${state.datasetId ? `?dataset_id=${encodeURIComponent(state.datasetId)}` : ""}`);
    const entries = [["Total images", data.total_images, "All registered originals", "▧"], ["Completed annotations", data.completed_annotations, "Images with saved annotations", "✓"], ["Pending annotations", data.pending_annotations, "Images awaiting annotation", "◷"], ["Approved annotations", data.approved_annotations, "Human-approved images", "✓"], ["Needs correction", data.needs_correction, "Flagged during review", "✎"], ["Rejected images", data.rejected_images, "Excluded by a reviewer", "−"], ["Saved datasets", data.saved_datasets, "Registered dataset sources", "▤"], ["Annotated objects", data.total_annotated_objects, "Saved object annotations", "◇"]];
    $("summary-cards").innerHTML = entries.map(([label, value, caption, icon], i) => `<div class="summary-card${i === 3 ? " highlight" : ""}"><span class="summary-label">${label}</span><span class="summary-icon" aria-hidden="true">${icon}</span><strong>${Number(value || 0).toLocaleString()}</strong><small>${caption}</small></div>`).join("");
    const total = Number(data.total_images || 0), approved = Number(data.approved_annotations || 0), percent = total ? Math.round(approved / total * 100) : 0;
    $("progress-fill").style.width = `${percent}%`; $("progress-value").textContent = `${percent}%`; $("review-progress").setAttribute("aria-valuenow", String(percent));
    $("progress-caption").textContent = `${approved.toLocaleString()} of ${total.toLocaleString()} images approved · AI output remains separate from approval`;
    if (data.storage_path || data.storage_location) $("storage-location").textContent = `Saved library: ${data.storage_path || data.storage_location}`;
    $("library-state").textContent = "Library connected";
  }
  function selectionUI() {
    const count = state.selected.size;
    $("selection-count").textContent = `${count} selected`; $("export-selected").disabled = !count; $("approve-selected").disabled = !count;
    const selectedPage = state.rows.filter(row => state.selected.has(String(row.image_id))).length;
    $("select-page").checked = state.rows.length > 0 && selectedPage === state.rows.length;
    $("select-page").indeterminate = selectedPage > 0 && selectedPage < state.rows.length;
    $("gallery").querySelectorAll(".image-card").forEach(card => { const selected = state.selected.has(card.dataset.imageId); card.classList.toggle("selected", selected); card.querySelector("input").checked = selected; });
  }
  function renderGallery() {
    $("gallery").innerHTML = state.rows.map(row => {
      const id = String(row.image_id), annotationCount = Number(row.annotation_count ?? row.annotations?.length ?? 0), fishCount = Number(row.fish_count || 0), parts = Number(row.part_count || 0), saved = row.saved === true;
      const fishLabel = fishCount ? `${fishCount} fish` : annotationCount ? "Fish unassigned" : "0 fish";
      return `<article class="image-card${state.selected.has(id) ? " selected" : ""}" data-image-id="${escapeHTML(id)}"><label class="image-checkbox"><input type="checkbox" data-select="${escapeHTML(id)}" aria-label="Select ${escapeHTML(row.file_name)}"${state.selected.has(id) ? " checked" : ""}></label><button type="button" class="thumbnail-button" data-open="${escapeHTML(id)}" aria-label="Open annotations for ${escapeHTML(row.file_name)}"><img src="${mediaURL(id, true)}" loading="lazy" decoding="async" alt="${escapeHTML(row.file_name)}">${annotationCount && saved ? '<span class="thumbnail-badge">✓ Completed · Saved</span>' : ""}</button><div class="card-body"><button type="button" class="file-button" data-open="${escapeHTML(id)}" title="${escapeHTML(row.file_name)}">${escapeHTML(row.file_name)}</button><div class="card-status">${badge(row)}${row.review_status === "reviewed" ? '<span class="badge approved">Reviewed</span>' : ""}</div><div class="card-meta"><span>${fishLabel}</span><span>${parts} anatomical parts</span><span>${annotationCount} objects</span></div><div class="card-date"><time>${escapeHTML(dateText(row.updated_at || row.modified_at))}</time><span class="${saved ? "saved-check" : ""}">${saved ? "✓ Saved" : "Not saved"}</span></div></div></article>`;
    }).join("");
    $("gallery").querySelectorAll("img").forEach(img => img.addEventListener("error", () => { const placeholder = document.createElement("span"); placeholder.className = "thumbnail-failure"; placeholder.textContent = "Image unavailable"; img.replaceWith(placeholder); }));
    $("gallery").querySelectorAll("[data-open]").forEach(button => button.addEventListener("click", () => void openImage(button.dataset.open)));
    $("gallery").querySelectorAll("[data-select]").forEach(input => input.addEventListener("change", () => { const id = input.dataset.select; if (input.checked) state.selected.set(id, state.rows.find(row => String(row.image_id) === id)); else state.selected.delete(id); selectionUI(); }));
    $("empty-library").classList.toggle("hidden", state.total !== 0);
    $("empty-library").querySelector("h3").textContent = $("search-input").value || $("status-filter").value ? "No matching images" : state.view === "completed" ? "No completed annotations yet" : "No images yet";
    $("empty-library").querySelector("p").textContent = $("search-input").value || $("status-filter").value ? "Try a different filename or annotation status." : "Discover existing annotations or add images from the Dataset page.";
    $("page-caption").textContent = state.total ? `Page ${state.page} of ${state.pages} · ${state.total.toLocaleString()} images` : "0 images";
    $("previous-page").disabled = state.page <= 1; $("next-page").disabled = state.page >= state.pages; selectionUI();
  }
  async function loadGallery() {
    const revision = ++state.request;
    $("gallery").setAttribute("aria-busy", "true");
    if (!state.rows.length) $("gallery").innerHTML = '<div class="skeleton-card"></div>'.repeat(6);
    const query = new URLSearchParams({page: String(state.page), page_size: "24", search: $("search-input").value.trim(), status: $("status-filter").value, sort: $("sort-order").value});
    if (state.datasetId) query.set("dataset_id", state.datasetId);
    if (state.view === "completed") query.set("completed", "true");
    try {
      const data = await getJSON(`/images?${query}`);
      if (revision !== state.request) return;
      state.rows = data.images || []; state.total = Number(data.total || 0); state.pages = Math.max(1, Number(data.pages || Math.ceil(state.total / 24))); state.page = Number(data.page || state.page);
      state.rows.forEach(row => { if (state.selected.has(String(row.image_id))) state.selected.set(String(row.image_id), row); });
      renderGallery();
    } catch (error) { if (revision === state.request) { $("gallery").innerHTML = ""; notice(`Could not load the image library: ${errorText(error)}`, true); } }
    finally { if (revision === state.request) $("gallery").setAttribute("aria-busy", "false"); }
  }
  async function refresh() { try { await Promise.all([summary(), loadGallery()]); } catch (error) { notice(errorText(error), true); $("library-state").textContent = "Connection unavailable"; } }
  async function navigate(view) {
    if (!await leaveImage()) return;
    state.view = view; state.page = 1; state.rows = [];
    document.querySelectorAll("[data-view]").forEach(button => { const active = button.dataset.view === view; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
    $("page-title").textContent = VIEW[view][0]; $("page-description").textContent = VIEW[view][1];
    $("summary-section").classList.toggle("hidden", view !== "dashboard"); $("dataset-section").classList.toggle("hidden", view !== "dataset"); $("export-section").classList.toggle("hidden", view !== "export");
    $("library-title").textContent = view === "completed" ? "Completed & saved images" : "Your images";
    $("library-caption").textContent = view === "completed" ? "AI annotations, corrections, and approvals are labeled separately." : "Saved annotations stay here between sessions.";
    await refresh();
  }
  function readDraft(id) { try { const draft = JSON.parse(localStorage.getItem(draftKey(id)) || "null"); return draft && draft.image_id === id && Array.isArray(draft.annotations) ? draft : null; } catch (_) { return null; } }
  function stashDraft() {
    if (!state.image || !state.dirty || state.readOnly) return;
    try { localStorage.setItem(draftKey(state.image.image_id), JSON.stringify({image_id: state.image.image_id, base_version: state.image.version, annotations: state.image.annotations, status: state.image.status, review_status: state.image.review_status, saved_at: new Date().toISOString()})); }
    catch (_) { notice("Browser draft recovery is unavailable. Use Save to persist changes on the server.", true); }
  }
  function removeDraft(id) { try { localStorage.removeItem(draftKey(id)); } catch (_) { /* Server saving does not depend on browser storage. */ } }
  function saveIndicator(mode) {
    const labels = {saved: "✓ Saved", saving: "Saving…", unsaved: "Unsaved Changes", failed: "Save Failed", history: "Saved historical version"};
    $("save-state").textContent = labels[mode]; $("save-state").className = `save-state ${mode}`;
    $("save-button").disabled = state.readOnly || state.historyLoading || (!state.dirty && !state.savePromise); $("retry-save").disabled = Boolean(state.savePromise) || state.historyLoading;
    $("save-error").classList.toggle("hidden", !state.saveError); $("save-error-message").textContent = state.saveError || "";
    $("retry-save").classList.toggle("hidden", state.conflict);
    updateEditControls();
  }
  function updateEditControls() {
    const locked = !state.image || state.readOnly || state.historyLoading || state.objectReviewBusy || state.busy || Boolean(state.drawing) || state.drag?.kind === "vertex";
    if ($("undo-edit")) $("undo-edit").disabled = locked || !state.undoStack.length;
    if ($("redo-edit")) $("redo-edit").disabled = locked || !state.redoStack.length;
  }
  function resetEditHistory() {
    state.undoStack = []; state.redoStack = []; state.editBaseline = state.image ? copy(state.image.annotations) : null; updateEditControls();
  }
  function checkpoint() {
    const annotations = state.image.annotations;
    if (state.editBaseline && JSON.stringify(state.editBaseline) !== JSON.stringify(annotations)) {
      state.undoStack.push(copy(state.editBaseline)); if (state.undoStack.length > 50) state.undoStack.shift(); state.redoStack = [];
    }
    state.editBaseline = copy(annotations); updateEditControls();
  }
  function changed({review = true, track = true} = {}) {
    if (state.readOnly || state.historyLoading) return;
    state.editRevision++; state.dirty = true;
    if (review) { state.image.status = "edited"; state.image.review_status = "needs_review"; }
    if (track) checkpoint();
    stashDraft(); saveIndicator(state.saveError ? "failed" : "unsaved"); updateWorkspaceHeader();
    clearTimeout(state.saveTimer);
    if (!state.conflict && !state.saveError) state.saveTimer = setTimeout(() => void save(), 600);
  }
  function editAnnotation(ann, patch) {
    if (!ann || state.readOnly || state.historyLoading || state.objectReviewBusy) return;
    Object.assign(ann, patch, {updated_at: new Date().toISOString(), status: "edited", review_status: "needs_review", source: ann.source === "manual" ? "manual" : "human_corrected"});
    changed(); renderAnnotations(); renderViewer();
  }
  function restoreEdit(direction) {
    if (!state.image || state.readOnly || state.historyLoading || state.objectReviewBusy || state.busy || state.drawing || state.drag?.kind === "vertex") return;
    const from = direction === "undo" ? state.undoStack : state.redoStack, to = direction === "undo" ? state.redoStack : state.undoStack;
    if (!from.length) return;
    const target = from.pop(), current = state.image.annotations, byId = new Map(current.map(ann => [ann.annotation_id, ann])), timestamp = new Date().toISOString();
    to.push(copy(current));
    const fields = ["class_id", "fish_id", "bbox", "segmentation", "confidence", "status", "review_status"];
    state.image.annotations = target.map(snapshot => {
      const present = byId.get(snapshot.annotation_id);
      if (present && fields.every(field => JSON.stringify(present[field]) === JSON.stringify(snapshot[field]))) return copy(present);
      return {...copy(snapshot), status: "edited", review_status: "needs_review", source: snapshot.source === "manual" ? "manual" : "human_corrected", updated_at: timestamp};
    });
    if (!state.image.annotations.some(ann => String(ann.annotation_id) === state.selectedAnnotation)) state.selectedAnnotation = null;
    state.editBaseline = copy(state.image.annotations); changed({track: false}); renderAnnotations(); renderViewer(); updateEditControls();
    notice(`${direction === "undo" ? "Undo" : "Redo"} applied. Changes will be saved as a new version.`);
  }
  async function save() {
    clearTimeout(state.saveTimer);
    if (state.drag?.kind === "vertex") { notice("Finish the vertex edit before saving.", true); return false; }
    if (state.savePromise) return state.savePromise;
    if (!state.image || state.readOnly || !state.dirty) return true;
    if (state.conflict) return false;
    state.saveError = null;
    const imageId = state.image.image_id;
    state.savePromise = (async () => {
      while (state.image?.image_id === imageId && state.dirty) {
        const revision = state.editRevision, snapshot = copy(state.image);
        saveIndicator("saving");
        try {
          const result = await postJSON(`/images/${encodeURIComponent(imageId)}`, {base_version: snapshot.version, status: snapshot.status, review_status: snapshot.review_status, annotations: snapshot.annotations}, "PUT");
          const record = result.image || result;
          if (!Number.isInteger(record.version) || record.saved !== true) throw new Error("The server did not confirm a saved annotation version. Your draft is retained.");
          state.liveImage = copy(record);
          if (state.editRevision === revision) { state.image = copy(record); state.editBaseline = copy(record.annotations); state.dirty = false; removeDraft(imageId); }
          else { state.image.version = record.version; stashDraft(); }
          if (state.selected.has(String(imageId))) state.selected.set(String(imageId), record);
          updateWorkspaceHeader();
        } catch (error) {
          state.conflict = error.status === 409; state.saveError = state.conflict ? "A newer version was saved elsewhere. Your draft is retained. Reload the saved version to review the changes; download your draft first if needed." : `${errorText(error)} Your changes remain in this workspace and in browser recovery storage when available.`;
          stashDraft(); saveIndicator("failed"); return false;
        }
      }
      saveIndicator("saved"); renderAnnotations(); void loadHistory(); void summary().catch(() => {}); return true;
    })();
    try { return await state.savePromise; } finally { state.savePromise = null; saveIndicator(state.saveError ? "failed" : state.dirty ? "unsaved" : state.readOnly ? "history" : "saved"); }
  }
  async function leaveImage() {
    if (state.objectReviewBusy) { notice("Wait for the object review to finish saving."); return false; }
    if (state.drawing) { notice("Finish or cancel the polygon before leaving the image.", true); return false; }
    if (state.drag?.kind === "vertex") { notice("Finish the vertex edit before leaving the image.", true); return false; }
    if (state.dirty && !await save()) { notice("Save the current image, or download its recovery draft and reload the saved version, before leaving.", true); return false; }
    if (state.savePromise && !await state.savePromise) return false;
    state.historyRequest++; state.historyLoading = false; state.image = null; state.liveImage = null; state.selectedAnnotation = null; state.readOnly = false; state.masks.clear(); resetEditHistory();
    $("workspace").classList.add("hidden"); $("library-section").classList.remove("hidden"); return true;
  }
  function updateWorkspaceHeader() {
    if (!state.image) return;
    const image = state.image;
    $("workspace-title").textContent = image.file_name; $("image-details").textContent = `${image.width} × ${image.height} px · Version ${image.version} · Modified ${dateText(image.updated_at || image.modified_at)}`;
    $("image-status").textContent = statusLabel(image); $("image-status").className = `badge ${statusOf(image)}`;
    const locked = state.readOnly || state.busy || state.historyLoading || state.objectReviewBusy;
    ["review-button", "needs-correction", "reject-image", "run-ai", "add-polygon", "new-class"].forEach(id => { $(id).disabled = locked; });
    $("approve-button").disabled = locked || !image.annotations.length || image.review_status !== "reviewed";
    $("approve-button").title = image.review_status === "reviewed" ? "Approve the reviewed annotations" : "Inspect the annotations and mark this image reviewed before approval";
    $("review-button").textContent = image.review_status === "reviewed" ? "✓ Reviewed" : "Mark reviewed";
    $("run-ai").disabled = locked || image.annotations.length > 0;
    $("run-ai").title = image.annotations.length ? "Existing annotations are preserved. AI annotation is available for unannotated images." : "Generate annotations with the existing automation pipeline";
    updateEditControls();
  }
  async function openImage(id) {
    if (state.image && !await leaveImage()) return;
    const opening = ++state.opening;
    notice(""); $("library-state").textContent = "Opening image…";
    try {
      const image = await getJSON(`/images/${encodeURIComponent(id)}`);
      if (opening !== state.opening) return;
      state.image = copy(image.image || image); state.liveImage = copy(state.image); state.selectedAnnotation = null; state.dirty = false; state.saveError = null; state.conflict = false; state.readOnly = false; state.editRevision = 0; state.zoom = 1; state.centerX = state.image.width / 2; state.centerY = state.image.height / 2; state.masks.clear(); state.maskWarnings.clear(); resetEditHistory();
      $("library-section").classList.add("hidden"); $("summary-section").classList.add("hidden"); $("dataset-section").classList.add("hidden"); $("export-section").classList.add("hidden"); $("workspace").classList.remove("hidden");
      $("original-link").href = mediaURL(id); $("history-note").textContent = ""; $("restore-version").classList.add("hidden");
      state.draft = readDraft(String(id)); $("draft-recovery").classList.toggle("hidden", !state.draft);
      if (state.draft) { const matching = state.draft.base_version === state.image.version; $("draft-message").textContent = matching ? `Unsaved work from ${dateText(state.draft.saved_at)} can be restored and saved as a new version.` : `This draft was based on version ${state.draft.base_version}; the server has version ${state.image.version}. Download it to recover your work without overwriting newer annotations.`; $("restore-draft").disabled = !matching; }
      populateCategories(); updateWorkspaceHeader(); renderAnnotations(); renderViewer(true); saveIndicator("saved"); await loadHistory();
      $("workspace-title").scrollIntoView({block: "start"});
    } catch (error) { notice(`Could not open this image: ${errorText(error)}`, true); }
    finally { $("library-state").textContent = "Library connected"; }
  }
  function categories() {
    const result = new Map((state.image?.categories || []).map(c => [Number(c.id ?? c.class_id), {...c, id: Number(c.id ?? c.class_id), name: c.name || c.class_name}]));
    (state.image?.annotations || []).forEach(ann => { if (!result.has(ann.class_id)) result.set(ann.class_id, {id: ann.class_id, name: ann.class_name}); });
    return [...result.values()].sort((a, b) => a.id - b.id);
  }
  function populateCategories() {
    const markup = categories().filter(c => c.active !== false).map(c => `<option value="${c.id}">${escapeHTML(c.name)} · ID ${c.id}</option>`).join("");
    $("class-editor").innerHTML = markup; $("new-class").innerHTML = markup;
    $("add-polygon").disabled = state.readOnly || state.historyLoading || !markup;
  }
  const currentAnnotation = () => state.image?.annotations.find(ann => String(ann.annotation_id) === state.selectedAnnotation);
  function selectAnnotation(id) { state.selectedAnnotation = id == null ? null : String(id); renderAnnotations(); renderViewer(); }
  function renderAnnotations() {
    const image = state.image; if (!image) return;
    const selected = currentAnnotation(), groups = new Map();
    const definitions = categories(), wholeFish = image.annotations.filter(ann => definitions.some(category => category.id === ann.class_id && category.kind === "whole_fish") && ann.status !== "rejected");
    if ($("fish-options")) $("fish-options").innerHTML = wholeFish.map(ann => `<option value="${escapeHTML(ann.annotation_id)}">${escapeHTML(ann.class_name)}</option>`).join("");
    image.annotations.forEach(ann => { const key = ann.fish_id == null || ann.fish_id === "" ? "" : String(ann.fish_id); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(ann); });
    $("annotation-total").textContent = String(image.annotations.length); $("object-count").textContent = `${image.annotations.length} annotated objects`;
    $("annotation-list").innerHTML = [...groups.entries()].map(([fish, annotations]) => `<div class="fish-group"><button type="button" class="fish-heading${selected && (selected.fish_id == null ? "" : String(selected.fish_id)) === fish ? " active" : ""}" data-fish="${escapeHTML(fish)}"><span>${fish ? `Fish ${escapeHTML(fish)}` : "Unassigned fish"}</span><span>${annotations.length} objects</span></button>${annotations.map(ann => `<button type="button" class="annotation-row${String(ann.annotation_id) === state.selectedAnnotation ? " active" : ""}" data-annotation="${escapeHTML(ann.annotation_id)}" aria-pressed="${String(ann.annotation_id) === state.selectedAnnotation}"><span class="class-swatch" style="background:${classColor(ann.class_id, state.image?.categories)}"></span><span>${escapeHTML(ann.class_name)}</span><span class="annotation-confidence">${Number.isFinite(ann.confidence) ? `${Math.round(ann.confidence * 100)}%` : ""}</span></button>`).join("")}</div>`).join("") || '<p class="annotation-empty">No annotations yet. Draw a mask or run AI annotation to begin.</p>';
    $("annotation-list").querySelectorAll("[data-annotation]").forEach(button => button.addEventListener("click", () => selectAnnotation(button.dataset.annotation)));
    $("annotation-list").querySelectorAll("[data-fish]").forEach(button => button.addEventListener("click", () => { const group = groups.get(button.dataset.fish); if (group?.length) selectAnnotation(group[0].annotation_id); }));
    $("annotation-editor").classList.toggle("hidden", !selected);
    if (selected) {
      $("selected-id").textContent = `ID ${selected.annotation_id}`; $("selected-source").textContent = `${String(selected.source || "unknown").replaceAll("_", " ")} · ${selected.status === "approved" ? "Approved" : selected.status === "rejected" ? "Rejected" : "Needs review"}`;
      $("class-editor").value = String(selected.class_id); $("fish-editor").value = selected.fish_id ?? ""; $("bbox-editor").value = selected.bbox ? selected.bbox.join(", ") : "";
      const rle = selected.segmentation && !Array.isArray(selected.segmentation);
      $("polygon-editor").value = JSON.stringify(selected.segmentation || []); $("polygon-editor").readOnly = Boolean(rle) || state.readOnly || state.historyLoading || state.objectReviewBusy; $("apply-polygon").disabled = Boolean(rle) || state.readOnly || state.historyLoading || state.objectReviewBusy;
      $("editor-feedback").textContent = rle ? "RLE mask preserved, including holes and disconnected regions. Redraw explicitly to replace it with a polygon." : "Drag a visible vertex to correct a polygon, or edit its coordinates.";
      ["class-editor", "fish-editor", "bbox-editor", "replace-polygon", "delete-annotation"].forEach(id => { $(id).disabled = state.readOnly || state.historyLoading || state.objectReviewBusy; });
      if ($("approve-object")) $("approve-object").disabled = state.readOnly || state.historyLoading || state.objectReviewBusy || selected.status === "approved" || !selected.segmentation || Array.isArray(selected.segmentation) && !selected.segmentation.length;
      if ($("reject-object")) $("reject-object").disabled = state.readOnly || state.historyLoading || state.objectReviewBusy || selected.status === "rejected";
      if (definitions.some(category => category.id === selected.class_id && category.kind === "whole_fish")) { $("fish-editor").disabled = true; $("fish-editor").title = "This whole-fish annotation's ID is the association ID for its anatomical parts."; }
      else $("fish-editor").title = "Choose an existing whole-fish annotation ID, or leave this field empty.";
    }
  }
  function rleImage(ann) {
    const key = `${ann.annotation_id}:${JSON.stringify(ann.segmentation)}:${classColor(ann.class_id, state.image?.categories)}`;
    if (state.masks.has(key)) return state.masks.get(key);
    const {width, height, counts} = decodeRLE(ann.segmentation), canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext("2d"), pixels = ctx.createImageData(width, height), rgb = classColor(ann.class_id, state.image?.categories).slice(1).match(/../g).map(h => parseInt(h, 16));
    let index = 0, on = false;
    counts.forEach(count => { if (on) { for (let p = index; p < index + count; p++) { const x = Math.floor(p / height), y = p % height, offset = (y * width + x) * 4; pixels.data[offset] = rgb[0]; pixels.data[offset + 1] = rgb[1]; pixels.data[offset + 2] = rgb[2]; pixels.data[offset + 3] = 255; } } index += count; on = !on; });
    ctx.putImageData(pixels, 0, 0); const data = {url: canvas.toDataURL("image/png"), width, height}; state.masks.set(key, data); return data;
  }
  function updateViewBox() {
    if (!state.image) return;
    const w = state.image.width / state.zoom, h = state.image.height / state.zoom;
    $("annotation-svg").setAttribute("viewBox", `${state.centerX - w / 2} ${state.centerY - h / 2} ${w} ${h}`);
    $("zoom-label").textContent = state.zoom === 1 ? "Fit" : `${Math.round(state.zoom * 100)}%`;
  }
  function renderViewer(newImage = false) {
    const image = state.image; if (!image) return;
    const svg = $("annotation-svg"), selected = currentAnnotation(), selectedFish = selected?.fish_id;
    svg.replaceChildren(svgNode("title", {}, `${image.file_name}: ${image.annotations.length} annotations`));
    const original = svgNode("image", {href: mediaURL(image.image_id), x: 0, y: 0, width: image.width, height: image.height, "data-original": "true"});
    if (newImage) { $("viewer-loading").textContent = "Loading original image…"; $("viewer-loading").classList.remove("hidden"); original.addEventListener("load", () => $("viewer-loading").classList.add("hidden"), {once: true}); original.addEventListener("error", () => { $("viewer-loading").textContent = "Original image unavailable. Saved annotations remain accessible."; }, {once: true}); }
    svg.append(original);
    const stroke = Math.max(image.width, image.height) / 550 / state.zoom;
    const labels = svgNode("g", {"pointer-events": "none"}), labelBoxes = [];
    image.annotations.forEach(ann => {
      const active = String(ann.annotation_id) === state.selectedAnnotation, related = selectedFish != null && ann.fish_id != null && String(ann.fish_id) === String(selectedFish), dim = selected && !active && !related;
      const group = svgNode("g", {"data-ann": ann.annotation_id, opacity: dim ? 0.3 : 1}), color = classColor(ann.class_id, state.image?.categories);
      if ($("show-masks").checked && Array.isArray(ann.segmentation)) ann.segmentation.forEach(ring => { if (Array.isArray(ring) && ring.length >= 6) group.append(svgNode("polygon", {points: ring.reduce((s, v, i) => s + (i % 2 ? `${v} ` : `${v},`), ""), fill: color, "fill-opacity": active ? .47 : .25, stroke: active ? "#ffffff" : color, "stroke-width": stroke * (active ? 1.8 : .8), class: "mask-shape"})); });
      else if ($("show-masks").checked && ann.segmentation) {
        try { const mask = rleImage(ann); group.append(svgNode("image", {href: mask.url, x: 0, y: 0, width: image.width, height: image.height, opacity: active ? .65 : .35, "pointer-events": "none", "image-rendering": "pixelated"})); }
        catch (error) { if (!state.maskWarnings.has(String(ann.annotation_id))) { state.maskWarnings.add(String(ann.annotation_id)); notice(`Mask preview unavailable for ${ann.class_name}: ${errorText(error)} The saved segmentation is preserved.`, true); } }
      }
      if (ann.bbox && ($("show-boxes").checked || active)) { const [x, y, width, height] = ann.bbox; group.append(svgNode("rect", {x, y, width, height, fill: "none", stroke: active ? "#fff" : color, "stroke-width": stroke * (active ? 1.8 : 1), "stroke-dasharray": active ? "" : `${stroke * 4} ${stroke * 2}`, "pointer-events": $("show-boxes").checked ? "stroke" : "none", class: "annotation-box"})); }
      if ($("show-labels").checked) {
        const box = ann.bbox || (Array.isArray(ann.segmentation) && ann.segmentation.length ? polygonBox(ann.segmentation) : null);
        if (box) {
          const text = `${ann.class_name}${ann.fish_id != null ? ` · Fish ${ann.fish_id}` : ""}`, font = stroke * 10, height = font * 1.55;
          const width = Math.min(image.width, text.length * font * .65 + stroke * 6), x = Math.max(0, Math.min(image.width - width, box[0]));
          const preferred = Math.max(0, Math.min(image.height - height, box[1] - height - stroke * 2));
          let y = preferred;
          for (let step = 0; step <= Math.ceil(image.height / height) * 2; step++) {
            const candidate = preferred + Math.ceil(step / 2) * height * (step % 2 ? 1 : -1);
            if (candidate < 0 || candidate + height > image.height) continue;
            if (!labelBoxes.some(other => x < other.x + other.width && x + width > other.x && candidate < other.y + other.height && candidate + height > other.y)) { y = candidate; break; }
          }
          labelBoxes.push({x, y, width, height});
          const label = svgNode("g", {opacity: dim ? .35 : 1});
          label.append(svgNode("rect", {x, y, width, height, rx: stroke * 2, fill: "#142f29", "fill-opacity": .92, stroke: color, "stroke-width": stroke * .5, class: "annotation-label-background"}));
          label.append(svgNode("text", {x: x + stroke * 3, y: y + font * 1.1, fill: "#fff", "font-size": font, "font-family": "system-ui, sans-serif", "font-weight": 600, class: "annotation-label", ...(text.length * font * .65 > width - stroke * 6 ? {textLength: Math.max(stroke, width - stroke * 6), lengthAdjust: "spacingAndGlyphs"} : {})}, text));
          labels.append(label);
        }
      }
      svg.append(group);
      if (active && !state.readOnly && !state.historyLoading && !state.drawing && $("show-masks").checked && Array.isArray(ann.segmentation)) ann.segmentation.forEach((ring, ringIndex) => { for (let i = 0; i < ring.length; i += 2) svg.append(svgNode("circle", {cx: ring[i], cy: ring[i + 1], r: stroke * 2.8, fill: "#fff", stroke: color, "stroke-width": stroke, "data-ring": ringIndex, "data-vertex": i, class: "vertex-handle"})); });
    });
    svg.append(labels);
    if (state.drawing?.points.length) svg.append(svgNode("polyline", {points: state.drawing.points.reduce((s, n, i) => s + (i % 2 ? `${n} ` : `${n},`), ""), fill: "#fff", "fill-opacity": ".12", stroke: "#fff", "stroke-width": stroke * 1.5, "stroke-dasharray": `${stroke * 4} ${stroke * 2}`, "pointer-events": "none"}));
    updateViewBox();
  }
  function imagePoint(event) { const matrix = $("annotation-svg").getScreenCTM(); if (!matrix) return {x: 0, y: 0}; const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()); return {x: Math.max(0, Math.min(state.image.width, point.x)), y: Math.max(0, Math.min(state.image.height, point.y))}; }
  function zoom(factor) { if (!state.image) return; state.zoom = Math.max(1, Math.min(16, state.zoom * factor)); if (state.zoom === 1) { state.centerX = state.image.width / 2; state.centerY = state.image.height / 2; } renderViewer(); }
  function startDrawing(replace) {
    if (state.readOnly || state.historyLoading || state.objectReviewBusy || !state.image) return;
    if (!categories().length) { notice("No class definitions are available. Import a dataset with its original categories before drawing.", true); return; }
    if (replace && !currentAnnotation()) return;
    if (replace && !window.confirm("Replace this annotation's complete mask with a newly drawn polygon? Its previous mask remains in saved version history.")) return;
    state.drawing = {points: [], replace: replace ? state.selectedAnnotation : null}; $("image-stage").classList.add("drawing"); $("drawing-hint").textContent = "Click to place vertices · Enter to finish · Escape to cancel"; $("drawing-hint").classList.remove("hidden"); $("finish-polygon").classList.remove("hidden"); $("cancel-polygon").classList.remove("hidden"); $("add-polygon").classList.add("hidden"); $("annotation-svg").focus(); updateEditControls(); renderViewer();
  }
  function cancelDrawing() { state.drawing = null; $("image-stage").classList.remove("drawing"); ["drawing-hint", "finish-polygon", "cancel-polygon"].forEach(id => $(id).classList.add("hidden")); $("add-polygon").classList.remove("hidden"); updateEditControls(); renderViewer(); }
  function finishDrawing() {
    if (!state.drawing) return;
    try {
      const rings = polygons([state.drawing.points], state.image.width, state.image.height), box = polygonBox(rings), replace = state.drawing.replace;
      if (replace) editAnnotation(drawingTarget(state.drawing, state.image.annotations), {segmentation: rings, bbox: box});
      else {
        const category = categories().find(c => c.id === Number($("new-class").value)); if (!category) throw new Error("Choose a class for the new annotation.");
        const time = new Date().toISOString(), id = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `manual-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        state.image.annotations.push({annotation_id: id, object_id: id, fish_id: null, class_id: category.id, class_name: category.name, bbox: box, segmentation: rings, confidence: null, status: "edited", review_status: "needs_review", source: "manual", created_at: time, updated_at: time, metadata: {}}); state.selectedAnnotation = id; changed();
      }
      cancelDrawing(); renderAnnotations();
    } catch (error) { notice(errorText(error), true); }
  }
  async function loadHistory() {
    if (!state.image) return;
    const id = state.image.image_id;
    try {
      const data = await getJSON(`/images/${encodeURIComponent(id)}/history`); if (state.image?.image_id !== id) return;
      state.history = data.versions || [];
      $("history-select").innerHTML = '<option value="">Current version</option>' + state.history.filter(v => v.version !== state.liveImage.version).sort((a, b) => b.version - a.version).map(v => `<option value="${v.version}">Version ${v.version} · ${escapeHTML(dateText(v.created_at || v.updated_at))}</option>`).join("");
      if (state.readOnly) $("history-select").value = String(state.image.version);
    } catch (error) { $("history-note").textContent = `Saved history could not be loaded: ${errorText(error)}`; }
  }
  async function showHistory(version) {
    if (!state.image || state.objectReviewBusy || state.drawing || state.drag?.kind === "vertex") return;
    if (state.dirty && !await save()) return;
    const id = state.image.image_id, requestId = ++state.historyRequest, editRevision = state.editRevision;
    state.historyLoading = true; updateWorkspaceHeader(); renderAnnotations(); saveIndicator(state.readOnly ? "history" : "saved");
    try {
      const result = version ? await getJSON(`/images/${encodeURIComponent(id)}?version=${encodeURIComponent(version)}`) : await getJSON(`/images/${encodeURIComponent(id)}`);
      if (requestId !== state.historyRequest || state.image?.image_id !== id) return;
      if (state.editRevision !== editRevision || state.dirty) { notice("Saved-version loading was cancelled because newer edits are present. Your current edits are preserved.", true); return; }
      state.image = copy(result.image || result); state.readOnly = Boolean(version); state.selectedAnnotation = null; state.dirty = false; resetEditHistory();
      if (!version) state.liveImage = copy(state.image);
      populateCategories(); updateWorkspaceHeader(); renderAnnotations(); renderViewer(); saveIndicator(version ? "history" : "saved");
      $("restore-version").classList.toggle("hidden", !version); $("history-note").textContent = version ? `Viewing saved version ${version}. Editing is disabled until you restore it as a new version or return to the current version.` : "";
    } catch (error) { if (requestId === state.historyRequest) notice(`Could not load this version: ${errorText(error)}`, true); }
    finally { if (requestId === state.historyRequest) { state.historyLoading = false; updateWorkspaceHeader(); renderAnnotations(); saveIndicator(state.saveError ? "failed" : state.dirty ? "unsaved" : state.readOnly ? "history" : "saved"); $("history-select").value = state.readOnly ? String(state.image.version) : ""; } }
  }
  async function setReview(reviewStatus, status) {
    if (!state.image || state.readOnly || state.historyLoading) return;
    if (state.drawing) { notice("Finish or cancel the polygon before changing review state.", true); return; }
    if (reviewStatus === "reviewed" && !state.image.annotations.length) { notice("Add annotations before marking this image reviewed.", true); return; }
    state.image.review_status = reviewStatus; if (status) state.image.status = status;
    changed({review: false}); updateWorkspaceHeader(); await save();
  }
  async function approveCurrent() {
    if (!state.image || state.readOnly || state.historyLoading || state.image.review_status !== "reviewed") return;
    if (!await save()) return;
    $("approve-button").disabled = true;
    try { await postJSON("/approve", {images: [{image_id: state.image.image_id, base_version: state.image.version}]}); const id = state.image.image_id; await openImage(id); notice("Annotations approved and saved."); }
    catch (error) { notice(`Approval failed: ${errorText(error)}`, true); updateWorkspaceHeader(); }
  }
  async function reviewObject(action) {
    const selected = currentAnnotation();
    if (!selected || state.readOnly || state.historyLoading || state.objectReviewBusy || state.busy) return false;
    if (state.drawing || state.drag?.kind === "vertex") { notice("Finish the mask edit before reviewing this object.", true); return false; }
    const imageId = state.image.image_id, annotationId = selected.annotation_id;
    try {
      if (action === "approve") {
        if (!selected.segmentation || Array.isArray(selected.segmentation) && !selected.segmentation.length) throw new Error("A segmentation mask is required before approving this object.");
        if (Array.isArray(selected.segmentation)) polygons(selected.segmentation, state.image.width, state.image.height);
        else { const mask = decodeRLE(selected.segmentation); if (mask.width !== state.image.width || mask.height !== state.image.height || !mask.counts.some((count, index) => index % 2 && count > 0)) throw new Error("The segmentation mask must contain object pixels and match the original image dimensions."); }
      }
      state.objectReviewBusy = true; updateWorkspaceHeader(); renderAnnotations();
      if (!await save() || state.image?.image_id !== imageId) return false;
      const annotation = state.image.annotations.find(ann => ann.annotation_id === annotationId); if (!annotation) throw new Error("This annotation is no longer available. Reload the saved image.");
      if (action === "reject") {
        const children = state.image.annotations.filter(ann => ann !== annotation && String(ann.fish_id) === String(annotationId));
        if (children.length && !window.confirm(`Reject this whole fish and leave its ${children.length} associated part(s) unassigned? Saved versions will remain available.`)) return false;
        children.forEach(ann => { ann.fish_id = null; ann.status = "edited"; ann.review_status = "needs_review"; });
      }
      annotation.status = action === "approve" ? "approved" : "rejected"; annotation.review_status = annotation.status; annotation.updated_at = new Date().toISOString();
      changed(); renderAnnotations(); renderViewer();
      if (!await save()) { notice(`Object ${action === "approve" ? "approval" : "rejection"} could not be saved. Your changes are retained; retry Save.`, true); return false; }
      notice(`Selected object ${action === "approve" ? "approved" : "rejected"} and saved. The image still requires review.`); return true;
    } catch (error) { notice(`Object review failed: ${errorText(error)}`, true); return false; }
    finally { state.objectReviewBusy = false; updateWorkspaceHeader(); renderAnnotations(); }
  }
  async function approveSelected() {
    if (state.dirty && !await save()) return;
    $("approve-selected").disabled = true;
    try {
      const records = await Promise.all([...state.selected.keys()].map(id => getJSON(`/images/${encodeURIComponent(id)}`)));
      const eligible = records.filter(record => record.review_status === "reviewed" && record.annotations?.length);
      if (!eligible.length) { notice("Open and inspect the selected images, then mark them reviewed before bulk approval.", true); return; }
      await postJSON("/approve", {images: eligible.map(record => ({image_id: record.image_id, base_version: record.version}))});
      notice(`${eligible.length} reviewed image${eligible.length === 1 ? "" : "s"} approved and saved.${eligible.length < records.length ? ` ${records.length - eligible.length} unreviewed or empty image(s) were skipped.` : ""}`); await refresh();
    } catch (error) { notice(`Bulk approval failed: ${errorText(error)}`, true); } finally { selectionUI(); }
  }
  function download(blob, name) { const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url; anchor.download = name; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function downloadDraft(draft = null) {
    const data = draft || {image_id: state.image?.image_id, base_version: state.image?.version, status: state.image?.status, review_status: state.image?.review_status, annotations: state.image?.annotations, recovered_at: new Date().toISOString(), recovery_draft: true};
    download(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}), `annotation-recovery-${data.image_id || "draft"}.json`);
  }
  async function exportSaved(scope, packageImages = false) {
    let ids = scope === "current" ? state.image ? [state.image.image_id] : [] : scope === "selected" ? [...state.selected.keys()] : [];
    if (["current", "selected"].includes(scope) && !ids.length) { notice(scope === "current" ? "Open an image before exporting its annotations." : "Select at least one image before exporting.", true); return; }
    if (state.dirty || state.savePromise || state.drawing || state.drag?.kind === "vertex" || state.historyLoading) { notice("Save the current image and finish any drawing or version loading before exporting. Exports always use the saved server version.", true); return; }
    if (state.readOnly && scope === "current") { notice("Return to the current version or restore this version before exporting. Exports use the latest saved version.", true); return; }
    $("export-feedback").textContent = "Validating saved annotations…"; $("download-export").disabled = true;
    try {
      const payload = {scope, image_ids: ids, package: false, ...(state.datasetId ? {dataset_id: state.datasetId} : {})}, jsonResponse = await request("/export", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}), data = validateExport(await jsonResponse.json());
      if (!data.images.length) throw new Error("No saved annotations match this export scope.");
      let blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}), disposition = jsonResponse.headers.get("content-disposition") || "";
      if (packageImages) { const response = await request("/export", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...payload, package: true})}); blob = await response.blob(); disposition = response.headers.get("content-disposition") || ""; const signature = new Uint8Array(await blob.slice(0, 4).arrayBuffer()); if (signature[0] !== 80 || signature[1] !== 75) throw new Error("The server did not return a valid dataset package."); }
      const name = disposition.match(/filename="?([^";]+)"?/)?.[1] || `sardinella-annotations-${scope}-${new Date().toISOString().slice(0, 10)}.${packageImages ? "zip" : "json"}`;
      download(blob, name); $("export-feedback").textContent = `Downloaded ${data.images.length} saved image annotation record(s).`; notice(`${packageImages ? "Dataset package" : "JSON annotations"} downloaded from saved data.`);
    } catch (error) { $("export-feedback").textContent = `Export failed: ${errorText(error)}`; notice(`Export failed: ${errorText(error)}`, true); }
    finally { $("download-export").disabled = false; }
  }
  async function scan() {
    if (state.busy) return; setBusy(true); notice("Discovering existing images and COCO annotations. Original files are preserved…");
    try { const result = await postJSON("/scan", state.datasetId ? {dataset_id: state.datasetId} : {}), errors = Array.isArray(result.errors) ? result.errors : []; notice(`Discovery complete: ${Number(result.imported ?? result.imported_images ?? 0)} image(s) imported, ${Number(result.existing ?? 0)} already indexed.${errors.length ? ` ${errors.length} source error(s): ${errors.map(error => typeof error === "string" ? error : JSON.stringify(error)).join("; ")}` : " Original files and saved edits are preserved."}`, errors.length > 0); await loadDatasets(true); await refresh(); }
    catch (error) { notice(`Discovery failed: ${errorText(error)}`, true); } finally { setBusy(false); }
  }
  async function uploadImages(files) {
    if (!files.length || state.busy) return; setBusy(true); let count = 0; const errors = [];
    for (const file of files) { try { notice(`Adding image ${count + errors.length + 1} of ${files.length}: ${file.name}`); await request("/upload", {method: "POST", headers: {"Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name), ...(state.datasetId ? {"X-Dataset-ID": state.datasetId} : {})}, body: file}); count++; } catch (error) { errors.push(`${file.name}: ${errorText(error)}`); } }
    $("upload-input").value = ""; setBusy(false); notice(`Added ${count} image(s).${errors.length ? ` ${errors.length} failed: ${errors.join("; ")}` : " Original images are ready to annotate."}`, Boolean(errors.length)); await refresh();
  }
  async function runAI() {
    if (!state.image || state.image.annotations.length || state.readOnly || state.busy) return;
    if (state.dirty && !await save()) return;
    setBusy(true); updateWorkspaceHeader(); $("run-ai").textContent = "Generating masks…"; notice("Running the existing annotation pipeline. This may take a moment.");
    const id = state.image.image_id;
    try { await postJSON(`/api/annotations/images/${encodeURIComponent(id)}/auto`, {expected_revision: state.image.version}); await openImage(id); notice("AI annotations saved. Inspect each mask and class before marking this image reviewed."); }
    catch (error) { notice(`AI annotation failed: ${errorText(error)} Your saved annotations are preserved.`, true); }
    finally { setBusy(false); $("run-ai").textContent = "Run AI annotation"; updateWorkspaceHeader(); }
  }
  function bindEvents() {
    $("annotation-editor").addEventListener("submit", event => event.preventDefault());
    if ($("dataset-select")) $("dataset-select").addEventListener("change", async () => {
      const selected = $("dataset-select").value;
      if (!await leaveImage()) { $("dataset-select").value = state.datasetId; return; }
      state.datasetId = selected; state.selected.clear(); await navigate(state.view);
    });
    document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => void navigate(button.dataset.view)));
    $("refresh-button").addEventListener("click", () => { if (state.image) { notice("Use the saved-version controls to reload the open image. The library counts have been refreshed."); void summary().catch(error => notice(errorText(error), true)); } else void refresh(); });
    ["scan-button", "discover-button", "empty-discover"].forEach(id => $(id).addEventListener("click", () => void scan()));
    $("upload-input").addEventListener("change", () => void uploadImages([...$("upload-input").files]));
    let searchTimer; $("search-input").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.page = 1; void loadGallery(); }, 250); });
    ["status-filter", "sort-order"].forEach(id => $(id).addEventListener("change", () => { state.page = 1; void loadGallery(); }));
    $("previous-page").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); void loadGallery(); }); $("next-page").addEventListener("click", () => { state.page++; void loadGallery(); });
    $("select-page").addEventListener("change", () => { state.rows.forEach(row => { if ($("select-page").checked) state.selected.set(String(row.image_id), row); else state.selected.delete(String(row.image_id)); }); selectionUI(); });
    $("clear-selection").addEventListener("click", () => { state.selected.clear(); selectionUI(); }); $("approve-selected").addEventListener("click", () => void approveSelected());
    $("export-selected").addEventListener("click", () => void exportSaved("selected")); $("export-current").addEventListener("click", () => void exportSaved("current"));
    $("download-export").addEventListener("click", () => void exportSaved($("export-scope").value, $("export-package").checked)); $("export-package").addEventListener("change", () => { $("download-export").textContent = $("export-package").checked ? "Download dataset package" : "Download JSON"; });
    $("back-library").addEventListener("click", () => void navigate(state.view)); $("save-button").addEventListener("click", () => void save()); $("retry-save").addEventListener("click", () => void save());
    $("review-button").addEventListener("click", () => void setReview("reviewed", "needs_review")); $("needs-correction").addEventListener("click", () => void setReview("needs_correction", "needs_review")); $("approve-button").addEventListener("click", () => void approveCurrent());
    if ($("approve-object")) $("approve-object").addEventListener("click", () => void reviewObject("approve"));
    if ($("reject-object")) $("reject-object").addEventListener("click", () => void reviewObject("reject"));
    if ($("undo-edit")) $("undo-edit").addEventListener("click", () => restoreEdit("undo"));
    if ($("redo-edit")) $("redo-edit").addEventListener("click", () => restoreEdit("redo"));
    $("reject-image").addEventListener("click", () => { if (window.confirm("Mark this image rejected? Its image, annotations, and previous saved versions will be retained.")) void setReview("rejected", "rejected"); });
    $("run-ai").addEventListener("click", () => void runAI());
    $("reload-image").addEventListener("click", () => { if (!state.image || !window.confirm("Reload the server's saved version? Download the recovery draft first if you need to keep unsaved edits.")) return; const id = state.image.image_id; state.dirty = false; state.conflict = false; state.saveError = null; void openImage(id); });
    $("restore-draft").addEventListener("click", () => { if (!state.draft || !state.image || state.readOnly || state.historyLoading || state.draft.image_id !== state.image.image_id || state.draft.base_version !== state.image.version) return; Object.assign(state.image, {annotations: copy(state.draft.annotations), status: state.draft.status, review_status: state.draft.review_status}); $("draft-recovery").classList.add("hidden"); state.selectedAnnotation = null; populateCategories(); changed({review: false}); renderAnnotations(); renderViewer(); });
    $("discard-draft").addEventListener("click", () => { removeDraft(state.image.image_id); state.draft = null; $("draft-recovery").classList.add("hidden"); }); $("download-draft").addEventListener("click", () => downloadDraft(state.draft)); $("download-unsaved").addEventListener("click", () => downloadDraft());
    $("history-select").addEventListener("change", () => void showHistory($("history-select").value));
    $("restore-version").addEventListener("click", () => { if (!state.readOnly || state.historyLoading) return; state.editBaseline = copy(state.liveImage.annotations); state.image.version = state.liveImage.version; state.image.status = "edited"; state.image.review_status = "needs_review"; state.image.annotations.forEach(ann => { if (ann.status !== "rejected") { ann.status = "edited"; ann.review_status = "needs_review"; } }); state.readOnly = false; $("restore-version").classList.add("hidden"); $("history-select").value = ""; $("history-note").textContent = "Historical annotations restored as an editable new version. Previous saved versions remain available."; changed(); populateCategories(); renderAnnotations(); renderViewer(); void save(); });
    $("class-editor").addEventListener("change", () => {
      const ann = currentAnnotation(), category = categories().find(c => c.id === Number($("class-editor").value)); if (!ann || !category) return;
      const wasFish = categories().some(c => c.id === ann.class_id && c.kind === "whole_fish"), children = state.image.annotations.filter(item => item !== ann && String(item.fish_id) === String(ann.annotation_id));
      if (wasFish && category.kind !== "whole_fish" && children.length) {
        if (!window.confirm(`Changing this whole-fish class will leave ${children.length} associated part(s) unassigned. Continue?`)) { renderAnnotations(); return; }
        children.forEach(item => { item.fish_id = null; });
      }
      editAnnotation(ann, {class_id: category.id, class_name: category.name, fish_id: category.kind === "whole_fish" ? ann.annotation_id : wasFish ? null : ann.fish_id});
    });
    $("fish-editor").addEventListener("change", () => { const ann = currentAnnotation(); if (!ann) return; try { editAnnotation(ann, {fish_id: fishAssociation(ann, $("fish-editor").value, state.image.annotations, categories())}); } catch (error) { $("fish-editor").value = ann.fish_id ?? ""; $("editor-feedback").textContent = errorText(error); } });
    $("bbox-editor").addEventListener("change", () => { const ann = currentAnnotation(); if (!ann) return; try { const text = $("bbox-editor").value.trim(), box = text ? text.replace(/[\[\]]/g, "").split(/[,\s]+/).map(Number) : null; if (box && (box.length !== 4 || !box.every(Number.isFinite) || box[0] < 0 || box[1] < 0 || box[2] <= 0 || box[3] <= 0 || box[0] + box[2] > state.image.width || box[1] + box[3] > state.image.height)) throw new Error("Enter [x, y, width, height] inside the image."); editAnnotation(ann, {bbox: box}); } catch (error) { $("editor-feedback").textContent = errorText(error); } });
    $("apply-polygon").addEventListener("click", () => { const ann = currentAnnotation(); if (!ann || state.readOnly) return; try { const rings = polygons(JSON.parse($("polygon-editor").value), state.image.width, state.image.height); editAnnotation(ann, {segmentation: rings, bbox: polygonBox(rings)}); $("editor-feedback").textContent = "Polygon coordinates updated."; } catch (error) { $("editor-feedback").textContent = errorText(error); } });
    $("delete-annotation").addEventListener("click", () => { const ann = currentAnnotation(); if (!ann || state.readOnly || state.historyLoading) return; const children = state.image.annotations.filter(item => item !== ann && String(item.fish_id) === String(ann.annotation_id)); if (!window.confirm(`Delete this ${ann.class_name} annotation?${children.length ? ` Its ${children.length} associated part(s) will become unassigned.` : ""} Its earlier saved version remains in history.`)) return; children.forEach(item => { item.fish_id = null; }); state.image.annotations = state.image.annotations.filter(item => item !== ann); state.selectedAnnotation = null; changed(); renderAnnotations(); renderViewer(); });
    $("add-polygon").addEventListener("click", () => startDrawing(false)); $("replace-polygon").addEventListener("click", () => startDrawing(true)); $("finish-polygon").addEventListener("click", finishDrawing); $("cancel-polygon").addEventListener("click", cancelDrawing);
    ["show-masks", "show-boxes", "show-labels"].forEach(id => $(id).addEventListener("change", () => renderViewer())); $("zoom-in").addEventListener("click", () => zoom(1.3)); $("zoom-out").addEventListener("click", () => zoom(1 / 1.3)); $("fit-image").addEventListener("click", () => { state.zoom = 1; state.centerX = state.image.width / 2; state.centerY = state.image.height / 2; renderViewer(); });
    const svg = $("annotation-svg");
    svg.addEventListener("wheel", event => { if (!state.image) return; event.preventDefault(); zoom(event.deltaY < 0 ? 1.12 : 1 / 1.12); }, {passive: false});
    svg.addEventListener("pointerdown", event => {
      if (!state.image || event.button !== 0) return;
      const point = imagePoint(event), vertex = event.target.closest("[data-vertex]"), ann = event.target.closest("[data-ann]");
      if (state.drawing) { state.drawing.points.push(Math.round(point.x * 100) / 100, Math.round(point.y * 100) / 100); renderViewer(); return; }
      if (vertex && !state.readOnly && !state.historyLoading && !state.objectReviewBusy) {
        if (state.savePromise) { notice("Wait for the current save to finish before moving a vertex."); return; }
        clearTimeout(state.saveTimer);
        const selected = currentAnnotation(); state.drag = {kind: "vertex", annotationId: selected.annotation_id, originalSegmentation: copy(selected.segmentation), ring: Number(vertex.dataset.ring), index: Number(vertex.dataset.vertex), moved: false}; updateEditControls(); svg.setPointerCapture(event.pointerId); event.preventDefault(); return;
      }
      // Select the actual topmost mask pixels, including holes in RLE masks.
      if ($("show-masks").checked) { const hit = [...state.image.annotations].reverse().find(item => { try { return maskContains(item.segmentation, point.x, point.y, state.image.width, state.image.height); } catch (_) { return false; } }); if (hit) { selectAnnotation(hit.annotation_id); return; } }
      if (ann && ($("show-boxes").checked || event.target.closest(".annotation-label"))) { selectAnnotation(ann.dataset.ann); return; }
      state.drag = {kind: "pan", x: event.clientX, y: event.clientY, centerX: state.centerX, centerY: state.centerY}; svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", event => {
      if (!state.drag || !state.image) return;
      if (state.drag.kind === "vertex") { const ann = state.image.annotations.find(item => item.annotation_id === state.drag.annotationId); if (!ann) return; const point = imagePoint(event), ring = ann.segmentation[state.drag.ring]; ring[state.drag.index] = Math.round(point.x * 100) / 100; ring[state.drag.index + 1] = Math.round(point.y * 100) / 100; state.drag.moved = true; renderViewer(); }
      else { const rect = svg.getBoundingClientRect(), unit = Math.max(state.image.width / state.zoom / rect.width, state.image.height / state.zoom / rect.height); state.centerX = state.drag.centerX - (event.clientX - state.drag.x) * unit; state.centerY = state.drag.centerY - (event.clientY - state.drag.y) * unit; updateViewBox(); }
    });
    function endPointer(event) {
      const drag = state.drag; state.drag = null;
      if (drag?.kind === "vertex") {
        const ann = state.image?.annotations.find(item => item.annotation_id === drag.annotationId); if (!ann) return;
        if (event?.type === "pointercancel") { ann.segmentation = drag.originalSegmentation; renderViewer(); }
        else if (drag.moved) { try { const rings = polygons(ann.segmentation, state.image.width, state.image.height); editAnnotation(ann, {segmentation: rings, bbox: polygonBox(rings)}); } catch (error) { ann.segmentation = drag.originalSegmentation; notice(`Invalid polygon edit: ${errorText(error)} The previous mask has been restored.`, true); renderAnnotations(); renderViewer(); } }
        if (state.dirty && !state.saveError && !state.conflict) state.saveTimer = setTimeout(() => void save(), 600);
      }
      updateEditControls();
    }
    svg.addEventListener("pointerup", endPointer); svg.addEventListener("pointercancel", endPointer);
    document.addEventListener("keydown", event => {
      const modified = event.ctrlKey || event.metaKey, typing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) || event.target?.isContentEditable || Boolean(event.target?.closest?.('[contenteditable="true"], [role="textbox"]'));
      if (modified && event.key.toLowerCase() === "s") { event.preventDefault(); void save(); }
      if (modified && !typing && event.key.toLowerCase() === "z" && state.image) { event.preventDefault(); restoreEdit(event.shiftKey ? "redo" : "undo"); }
      if (state.drawing && event.key === "Escape") { event.preventDefault(); cancelDrawing(); }
      if (state.drawing && event.key === "Enter" && !typing) { event.preventDefault(); finishDrawing(); }
    });
    window.addEventListener("beforeunload", event => { if (state.dirty) { stashDraft(); event.preventDefault(); event.returnValue = ""; } });
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden" && state.dirty) { stashDraft(); void save(); } });
    window.addEventListener("online", () => { if (state.dirty && !state.conflict) void save(); });
  }
  async function initialize() {
    bindEvents();
    try {
      const mode = await (await fetch("/api/auth/mode", {credentials: "same-origin", cache: "no-store"})).json();
      if (mode.lan_security) { const response = await fetch("/api/auth/session", {credentials: "same-origin", cache: "no-store"}); if (!response.ok) { $("auth-message").classList.remove("hidden"); $("library-state").textContent = "Sign in required"; return; } state.csrf = (await response.json()).csrf_token; }
      await loadDatasets(); await refresh();
    } catch (error) { notice(`Unable to initialize the annotation library: ${errorText(error)}`, true); $("library-state").textContent = "Connection unavailable"; }
  }
  // Other annotation panels use this small bridge to the same persistence queue.
  // Return copies so class/export controls cannot mutate editor state silently.
  window.annotationLibrary = Object.freeze({
    getSelection: () => [...state.selected.keys()],
    getCurrent: () => state.image ? copy(state.image) : null,
    getDataset: () => state.datasetId,
    getCSRF: () => state.csrf,
    canExport: () => !state.dirty && !state.savePromise && !state.drawing && !state.historyLoading && !state.readOnly && !state.objectReviewBusy && state.drag?.kind !== "vertex",
    flush: async () => {
      if (state.drawing || state.historyLoading || state.readOnly || state.drag?.kind === "vertex") return false;
      return save();
    },
    request,
    refresh: async () => {
      await loadDatasets(true);
      const id = state.image?.image_id, editRevision = state.editRevision;
      if (id && !state.dirty && !state.savePromise && !state.readOnly && !state.drawing && !state.historyLoading) {
        const record = await getJSON(`/images/${encodeURIComponent(id)}`);
        if (state.image?.image_id === id && state.editRevision === editRevision && !state.dirty && !state.drawing && !state.readOnly) {
          state.image = copy(record); state.liveImage = copy(record); resetEditHistory();
          populateCategories(); updateWorkspaceHeader(); renderAnnotations(); renderViewer();
        }
      }
      await refresh();
    }
  });
  void initialize();
})();
