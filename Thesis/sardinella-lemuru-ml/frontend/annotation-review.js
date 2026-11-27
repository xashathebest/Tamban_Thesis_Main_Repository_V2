/* Local verified annotation review. No prediction is approved by opening the image. */
((root) => {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const copy = value => JSON.parse(JSON.stringify(value));
  const clamp = (value, max) => Math.max(0, Math.min(max, value));
  const percent = value => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Not measured";
  const validRing = mask => Array.isArray(mask) && mask.length >= 3 && mask.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite));
  const maskValid = item => Boolean(item && validRing(item.mask));
  const hasMask = item => Boolean(item && (maskValid(item) || item.segmentation && Array.isArray(item.contours) && item.contours.length && item.contours.every(contour => Array.isArray(contour) && contour.length && contour.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)))));
  const editableMask = item => maskValid(item) && item.mask_complete !== false;
  const rings = item => item.mask_changed && maskValid(item) ? [item.mask] : item.contours?.length ? item.contours : maskValid(item) ? [item.mask] : [];
  function replaceMask(item, mask) { item.mask = mask; item.contours = [mask]; item.mask_complete = true; item.mask_changed = true; item.bbox = bbox(mask); }
  function bbox(mask) {
    return mask.reduce((bounds, [x, y]) => [Math.min(bounds[0], x), Math.min(bounds[1], y), Math.max(bounds[2], x), Math.max(bounds[3], y)], [Infinity, Infinity, -Infinity, -Infinity]);
  }
  function pointInImage(svg, event, width, height) {
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const local = point.matrixTransform(matrix.inverse());
    return [Math.round(clamp(local.x, width) * 100) / 100, Math.round(clamp(local.y, height) * 100) / 100];
  }
  function nearestEdge(mask, point) {
    let best = {index: 0, distance: Infinity};
    for (let i = 0; i < mask.length; i++) {
      const a = mask[i], b = mask[(i + 1) % mask.length], dx = b[0] - a[0], dy = b[1] - a[1];
      const t = clamp(((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy || 1), 1);
      const distance = (point[0] - a[0] - t * dx) ** 2 + (point[1] - a[1] - t * dy) ** 2;
      if (distance < best.distance) best = {index: i + 1, distance};
    }
    return best.index;
  }
  function classEntries(mapping) {
    if (Array.isArray(mapping)) return mapping.map((name, id) => typeof name === "object" ? [Number(name.class_id ?? name.id ?? id), String(name.class_name ?? name.name)] : [id, String(name)]);
    return Object.entries(mapping || {}).map(([id, name]) => [Number(id), String(name)]).filter(([id]) => Number.isInteger(id));
  }
  function reviewProblem(annotations, classes, width, height) {
    if (!annotations.length) return "Add at least one annotation before approving this image.";
    const mapping = new Map(classes), ids = new Set();
    for (const item of annotations) {
      if (!item.id || ids.has(item.id)) return "Every annotation must have a unique identifier.";
      ids.add(item.id);
      if (!mapping.has(item.class_id) || mapping.get(item.class_id) !== item.class_name) return "Choose a valid class from the dataset class mapping.";
      if (!hasMask(item)) return "Some annotations have no valid segmentation mask. Use Edit to draw their boundaries before approval.";
      if (rings(item).some(mask => mask.some(([x, y]) => x < 0 || y < 0 || x > width || y > height))) return "A mask extends outside the original image.";
      const area = rings(item).reduce((total, mask) => total + Math.abs(mask.reduce((sum, p, i, points) => sum + p[0] * points[(i + 1) % points.length][1] - points[(i + 1) % points.length][0] * p[1], 0)) / 2, 0);
      if (area < 1 && (!item.segmentation || item.mask_changed)) return "A mask has no usable area. Redraw its boundary.";
    }
    return null;
  }
  async function request(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : data.detail ? JSON.stringify(data.detail) : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return data;
  }
  class Review {
    constructor(document) {
      this.document = document;
      this.el = {};
      for (const id of ["review", "upload", "refresh", "learning-status", "message", "empty", "current", "filename", "next", "layout", "canvas", "editor", "object", "fish", "class", "redraw", "add", "remove", "remove-point", "drawing-actions", "finish", "cancel-drawing", "cancel-edit", "labels", "warnings", "approve", "edit", "decline", "reason", "reference-details", "references", "progress-values"]) this.el[id] = document.getElementById(`annotation-${id}`);
      this.item = null; this.annotations = []; this.classes = []; this.classKinds = {}; this.pending = []; this.total = 0;
      this.selected = null; this.vertex = null; this.drag = null; this.drawing = null;
      this.editing = false; this.busy = false; this.ready = false; this.startedAt = 0; this.initialized = false;
      this.bind();
    }
    message(text, error = false) { this.el.message.textContent = text; this.el.message.dataset.error = String(error); }
    selectedAnnotation() { return this.annotations.find(item => item.id === this.selected); }
    visible() { return !this.document.getElementById("view-review").classList.contains("hidden"); }
    setBusy(busy) {
      this.busy = busy; this.el.review.setAttribute("aria-busy", String(busy)); this.controls();
    }
    controls() {
      const active = Boolean(this.item && this.ready), selected = this.selectedAnnotation();
      for (const control of this.el.review.querySelectorAll("button, input, select")) control.disabled = this.busy;
      this.el.approve.disabled = this.busy || !active || this.editing;
      this.el.edit.disabled = this.busy || !active || Boolean(this.drawing);
      this.el.decline.disabled = this.busy || !active;
      this.el.refresh.disabled = this.busy || this.editing;
      this.el.upload.disabled = this.busy || this.editing;
      for (const key of ["redraw", "remove"]) this.el[key].disabled = this.busy || !selected || Boolean(this.drawing);
      this.el.object.disabled = this.busy || Boolean(this.drawing);
      this.el.fish.disabled = this.busy || !this.drawing && selected?.kind === "whole_fish";
      this.el.add.disabled = this.busy || !this.classes.length || Boolean(this.drawing);
      this.el.finish.disabled = this.busy || !this.drawing || this.drawing.points.length < 3;
      this.el["remove-point"].disabled = this.busy || !selected || !maskValid(selected) || selected.mask.length <= 3;
      this.el["remove-point"].classList.toggle("hidden", !this.editing || this.vertex === null || Boolean(this.drawing));
      this.el.edit.textContent = this.editing ? "Save verified edits" : "Edit";
      if (!this.editing) { const key = this.document.createElement("kbd"); key.textContent = "E"; this.el.edit.append(key); }
    }
    bind() {
      this.el.refresh.addEventListener("click", () => this.refresh());
      this.el.upload.addEventListener("change", () => this.upload());
      this.el.approve.addEventListener("click", () => this.review("approve"));
      this.el.edit.addEventListener("click", () => this.editing ? this.review("edit") : this.beginEdit());
      this.el.decline.addEventListener("click", () => this.review("decline"));
      this.el.object.addEventListener("change", () => this.select(this.el.object.value));
      this.el.class.addEventListener("change", () => this.updateSelected());
      this.el.fish.addEventListener("input", () => this.updateSelected());
      this.el.redraw.addEventListener("click", () => this.beginDrawing(this.selected));
      this.el.add.addEventListener("click", () => this.beginDrawing(null));
      this.el.remove.addEventListener("click", () => { this.annotations = this.annotations.filter(item => item.id !== this.selected); this.select(this.annotations[0]?.id || null); });
      this.el["cancel-edit"].addEventListener("click", () => { if (this.busy) return; this.annotations = copy(this.item.annotations || this.item.predictions || []); this.editing = false; this.drawing = null; this.select(this.annotations[0]?.id || null); this.message("Unsaved edits discarded. The saved annotation set is shown."); });
      this.el["remove-point"].addEventListener("click", () => this.removePoint());
      this.el.finish.addEventListener("click", () => this.finishDrawing());
      this.el["cancel-drawing"].addEventListener("click", () => { this.drawing = null; this.render(); });
      this.el.canvas.addEventListener("pointerdown", event => this.pointerDown(event));
      this.el.canvas.addEventListener("pointermove", event => this.pointerMove(event));
      this.el.canvas.addEventListener("pointerup", event => this.pointerUp(event));
      this.el.canvas.addEventListener("pointercancel", event => this.pointerUp(event));
      this.el.canvas.addEventListener("dblclick", event => this.insertPoint(event));
      this.el.canvas.addEventListener("contextmenu", event => {
        if (!this.editing || event.target.dataset.vertex === undefined) return;
        event.preventDefault(); this.vertex = Number(event.target.dataset.vertex); this.removePoint();
      });
      this.document.addEventListener("keydown", event => {
        if (!this.visible() || this.busy || !this.ready || this.editing || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target.closest("input, select, textarea, [contenteditable], [role=dialog]")) return;
        if (this.document.querySelector('[role="dialog"][aria-hidden="false"]')) return;
        const key = event.key.toLowerCase();
        if (!["a", "e", "d"].includes(key)) return;
        event.preventDefault(); if (key === "e") this.beginEdit(); else this.review(key === "a" ? "approve" : "decline");
      });
    }
    async refresh(preferredId = null) {
      if (this.busy || this.editing) return;
      this.setBusy(true); this.message("Loading pending annotations…");
      try { await this.loadQueue(preferredId); this.initialized = true; }
      catch (error) { this.message(error.message, true); }
      finally { this.setBusy(false); }
    }
    async loadQueue(preferredId = null) {
      const results = await Promise.allSettled([request("/api/annotations/pending"), request("/api/annotations/learning/status")]);
      if (results[1].status === "fulfilled") this.renderLearning(results[1].value);
      else this.el["learning-status"].textContent = `Learning status unavailable: ${results[1].reason.message}`;
      if (results[0].status === "rejected") throw results[0].reason;
      const queue = results[0].value; this.pending = queue.items || []; this.total = queue.total ?? this.pending.length;
      const id = this.pending.some(item => item.image_id === preferredId) ? preferredId : queue.next_image_id || this.pending[0]?.image_id;
      if (id) await this.loadItem(id);
      else { this.item = null; this.ready = false; this.el.current.classList.add("hidden"); this.el.empty.classList.remove("hidden"); this.message("All annotation images have been reviewed. Add more images when ready."); }
    }
    async loadItem(id) {
      this.ready = false;
      const item = await request(`/api/annotations/${encodeURIComponent(id)}`);
      const imageUrl = `/api/annotations/${encodeURIComponent(id)}/image`;
      await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => image.naturalWidth === item.width && image.naturalHeight === item.height ? resolve() : reject(new Error("Original image dimensions do not match its masks. Review is withheld."));
        image.onerror = () => reject(new Error("The original image could not be loaded. No annotation was approved."));
        image.src = imageUrl;
      });
      this.item = item; this.imageUrl = imageUrl;
      this.annotations = copy(item.annotations || item.predictions || []);
      this.editing = false; this.drawing = null; this.drag = null; this.vertex = null;
      this.selected = this.annotations[0]?.id || null; this.ready = true; this.startedAt = performance.now();
      this.el.reason.value = ""; this.el.empty.classList.add("hidden"); this.el.current.classList.remove("hidden");
      this.render(); this.message(`Inspect ${item.filename}: ${this.annotations.length} annotation${this.annotations.length === 1 ? "" : "s"}.`);
    }
    async upload() {
      if (this.busy || this.editing) return;
      const files = Array.from(this.el.upload.files || []); if (!files.length) return;
      this.setBusy(true); let successes = 0; const failures = [];
      for (const [index, file] of files.entries()) {
        this.message(`Adding image ${index + 1} of ${files.length}: ${file.name}…`);
        try {
          await request("/api/annotations/upload", {method: "POST", headers: {"Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name)}, body: file}); successes++;
        } catch (error) { failures.push(`${file.name}: ${error.message}`); }
      }
      try { await this.loadQueue(); }
      catch (error) { failures.push(error.message); }
      finally { this.el.upload.value = ""; this.setBusy(false); }
      this.message(`${successes} image${successes === 1 ? "" : "s"} added.${failures.length ? ` ${failures.join("; ")}` : " Review the next image below."}`, Boolean(failures.length));
    }
    async review(action) {
      if (this.busy || !this.ready || !this.item || this.drawing && action !== "decline" || action === "approve" && this.editing) return;
      if (action !== "decline") {
        const problem = reviewProblem(this.annotations, this.classes, this.item.width, this.item.height);
        if (problem) { this.message(problem, true); return; }
      }
      const item = this.item;
      const body = {action, revision: item.revision, review_time_ms: Math.max(0, Math.round(performance.now() - this.startedAt))};
      if (action === "edit") body.annotations = copy(this.annotations).map(annotation => ({...annotation, bbox: annotation.mask_changed && maskValid(annotation) ? bbox(annotation.mask) : annotation.bbox}));
      if (action === "decline") body.reason = this.el.reason.value.trim();
      this.setBusy(true); this.message(action === "decline" ? "Saving decline…" : "Saving verified annotations…");
      try {
        const result = await request(`/api/annotations/${encodeURIComponent(item.image_id)}/review`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
        this.editing = false; this.ready = false; this.item = null; this.el.current.classList.add("hidden");
        this.message(action === "decline" ? "Declined. Source image preserved." : "Verified annotations saved.");
        try { await this.loadQueue(result.next_image_id); }
        catch (error) { this.message(`Decision saved. Next image could not load: ${error.message}. Use Refresh to continue.`, true); }
      } catch (error) { this.message(`Decision was not saved: ${error.message}. Your edits are still open.`, true); }
      finally { this.setBusy(false); }
    }
    beginEdit() {
      if (this.busy || !this.ready) return;
      this.editing = true; this.render(); this.message("Edit only the affected fish or part, then save the verified annotation set.");
    }
    select(id) { this.selected = id; this.vertex = null; this.render(); }
    updateSelected() {
      if (this.busy || !this.editing || this.drawing) return;
      const item = this.selectedAnnotation(); if (!item) return;
      item.class_id = Number(this.el.class.value); item.class_name = new Map(this.classes).get(item.class_id);
      const oldKind = item.kind; item.kind = this.classKinds[item.class_id] || item.kind;
      item.fish_id = item.kind === "whole_fish" ? item.id : oldKind === "whole_fish" ? null : this.el.fish.value.trim() || null;
      this.el.fish.value = item.fish_id || ""; this.renderCanvas(); this.renderLabels(); this.renderObjects(); this.controls();
    }
    beginDrawing(id) {
      if (this.busy || !this.editing) return;
      this.drawing = {id, points: []}; this.vertex = null; this.render();
      this.message(id && this.selectedAnnotation()?.mask_complete === false ? "This mask has holes or disconnected pieces. Redrawing replaces the entire mask with the new polygon; class-only edits preserve every original piece." : "Click points around the missing or corrected boundary, then choose Finish mask.");
    }
    finishDrawing() {
      if (this.busy || !this.drawing || this.drawing.points.length < 3) return;
      const points = copy(this.drawing.points), classId = Number(this.el.class.value), className = new Map(this.classes).get(classId);
      if (!className) { this.message("Choose the class for this mask.", true); return; }
      let item = this.annotations.find(annotation => annotation.id === this.drawing.id);
      if (!item) { item = {id: `human-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`, class_id: classId, class_name: className}; this.annotations.push(item); }
      replaceMask(item, points); item.class_id = classId; item.class_name = className; item.kind = this.classKinds[classId] || "part"; item.fish_id = item.kind === "whole_fish" ? item.id : this.el.fish.value.trim() || null;
      this.selected = item.id; this.drawing = null; this.render(); this.message("Mask updated locally. Save verified edits when the complete image is correct.");
    }
    removePoint() {
      const item = this.selectedAnnotation(); if (this.busy || !this.editing || !editableMask(item) || item.mask.length <= 3 || this.vertex === null) return;
      const points = copy(item.mask); points.splice(this.vertex, 1); replaceMask(item, points); this.vertex = null; this.render();
    }
    localPoint(event) { return this.item ? pointInImage(this.el.canvas, event, this.item.width, this.item.height) : null; }
    pointerDown(event) {
      if (this.busy || !this.ready || event.button !== 0) return;
      if (this.drawing) { const point = this.localPoint(event); if (point) { this.drawing.points.push(point); this.renderCanvas(); this.controls(); } return; }
      const id = event.target.dataset.annotation;
      if (!this.editing) { if (id && id !== this.selected) this.select(id); return; }
      if (event.target.dataset.vertex !== undefined) {
        this.vertex = Number(event.target.dataset.vertex); this.drag = {pointerId: event.pointerId, vertex: this.vertex, annotation: this.selected};
        this.el.canvas.setPointerCapture(event.pointerId); this.controls(); event.preventDefault();
      } else if (id && id !== this.selected) this.select(id);
    }
    pointerMove(event) {
      if (!this.drag || this.busy || event.pointerId !== this.drag.pointerId) return;
      const item = this.annotations.find(annotation => annotation.id === this.drag.annotation), point = this.localPoint(event);
      if (!item || !point) return;
      const points = copy(item.mask); points[this.drag.vertex] = point; replaceMask(item, points); this.renderCanvas();
    }
    pointerUp(event) {
      if (!this.drag || event.pointerId !== this.drag.pointerId) return;
      if (this.el.canvas.hasPointerCapture(event.pointerId)) this.el.canvas.releasePointerCapture(event.pointerId);
      this.drag = null; this.renderCanvas(); this.controls();
    }
    insertPoint(event) {
      const item = this.selectedAnnotation();
      if (this.busy || !this.editing || this.drawing || !editableMask(item) || event.target.dataset.annotation !== item.id) return;
      const point = this.localPoint(event); if (!point) return;
      const points = copy(item.mask); points.splice(nearestEdge(points, point), 0, point); replaceMask(item, points); this.render(); event.preventDefault();
    }
    svgNode(tag, attributes, text) {
      const node = this.document.createElementNS(SVG, tag);
      for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
      if (text !== undefined) node.textContent = text;
      return node;
    }
    color(item) { return `hsl(${((Number(item.class_id) || 0) * 67 + 165) % 360} 85% 60%)`; }
    renderCanvas() {
      if (!this.item) return;
      const svg = this.el.canvas, {width, height} = this.item;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      svg.classList.toggle("is-editing", this.editing);
      const nodes = [this.svgNode("image", {href: this.imageUrl, x: 0, y: 0, width, height})], font = Math.max(10, width / 95);
      for (const item of this.annotations) {
        const selected = this.selected === item.id, color = this.color(item), contours = rings(item), bounds = hasMask(item) ? bbox(contours.flat()) : item.bbox;
        if (hasMask(item)) nodes.push(this.svgNode("path", {d: contours.map(mask => `M ${mask.map(point => point.join(" ")).join(" L ")} Z`).join(" "), fill: color, "fill-rule": "evenodd", "fill-opacity": selected ? .34 : .2, stroke: color, "stroke-width": selected ? 3 : 1.5, "stroke-linecap": "round", "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke", "data-annotation": item.id}));
        else if (Array.isArray(bounds) && bounds.length === 4) nodes.push(this.svgNode("rect", {x: bounds[0], y: bounds[1], width: bounds[2] - bounds[0], height: bounds[3] - bounds[1], fill: "none", stroke: color, "stroke-dasharray": "5 4", "stroke-width": 2, "vector-effect": "non-scaling-stroke", "data-annotation": item.id}));
        if (bounds) nodes.push(this.svgNode("text", {x: clamp(bounds[0] + 3, width - font * 5), y: Math.max(font * 1.2, bounds[1] - font / 2), fill: "white", stroke: "#102124", "stroke-width": font / 5, "paint-order": "stroke", "font-size": font, "font-family": "sans-serif", "pointer-events": "none"}, `${item.fish_id ? `Fish ${item.fish_id}` : "Unassigned fish"} · ${item.class_name}${hasMask(item) ? "" : " · MASK NEEDED"}`));
        if (selected && this.editing && !this.drawing && editableMask(item)) item.mask.forEach((point, index) => nodes.push(this.svgNode("circle", {cx: point[0], cy: point[1], r: Math.max(width / 180, 3), fill: this.vertex === index ? "#102124" : "white", stroke: color, "stroke-width": 2, "vector-effect": "non-scaling-stroke", "data-vertex": index})));
      }
      if (this.drawing) {
        const points = this.drawing.points;
        nodes.push(this.svgNode("polyline", {points: points.map(point => point.join(",")).join(" "), fill: "none", stroke: "#ffffff", "stroke-width": 2, "vector-effect": "non-scaling-stroke", "pointer-events": "none"}));
        for (const point of points) nodes.push(this.svgNode("circle", {cx: point[0], cy: point[1], r: Math.max(width / 220, 3), fill: "#fff", "pointer-events": "none"}));
      }
      svg.replaceChildren(...nodes);
    }
    renderObjects() {
      this.el.object.replaceChildren(...this.annotations.map(item => {
        const option = this.document.createElement("option"); option.value = item.id; option.textContent = `${item.fish_id ? `Fish ${item.fish_id}` : "Unassigned fish"} · ${item.class_name}${hasMask(item) ? "" : " · mask needed"}`; return option;
      }));
      this.el.object.value = this.selected || "";
    }
    renderLabels() {
      this.el.labels.replaceChildren(...this.annotations.map(item => {
        const li = this.document.createElement("li"), button = this.document.createElement("button"), swatch = this.document.createElement("span");
        button.type = "button"; button.setAttribute("aria-pressed", String(this.selected === item.id)); button.disabled = this.busy || Boolean(this.drawing);
        swatch.className = "annotation-label-swatch"; swatch.style.backgroundColor = this.color(item);
        button.append(swatch, this.document.createTextNode(`${item.fish_id ? `Fish ${item.fish_id}` : "Unassigned fish"} · ${item.class_name}${hasMask(item) ? "" : " · mask needed"}`));
        button.addEventListener("click", () => { if (!this.busy && !this.drawing) this.select(item.id); }); li.append(button); return li;
      }));
    }
    render() {
      if (!this.item) return;
      this.el.filename.textContent = this.item.filename;
      const next = this.pending.find(item => item.image_id !== this.item.image_id);
      this.el.next.textContent = `${this.total} pending · ${next ? `Next: ${next.filename}` : "Last pending image"}`;
      this.el.editor.classList.toggle("hidden", !this.editing); this.el.layout.classList.toggle("is-editing", this.editing);
      this.el["drawing-actions"].classList.toggle("hidden", !this.drawing);
      this.renderObjects(); this.renderCanvas(); this.renderLabels();
      const selected = this.selectedAnnotation();
      if (selected && !this.drawing) { this.el.class.value = String(selected.class_id); this.el.fish.value = selected.fish_id || ""; }
      const warnings = (this.item.warnings || []).map(warning => typeof warning === "string" ? warning : warning.message || JSON.stringify(warning));
      const missing = this.annotations.filter(item => !hasMask(item)).length;
      if (missing) warnings.push(`${missing} annotation${missing === 1 ? " needs a" : "s need"} segmentation mask before approval.`);
      if (!this.classes.length) warnings.push("Dataset class mapping is unavailable. Approval is withheld until it loads.");
      if (this.editing && selected?.mask_complete === false) warnings.push("Selected mask contains holes or disconnected pieces. Class and fish-ID edits preserve them. Redraw replaces the entire mask.");
      this.el.warnings.textContent = warnings.join(" "); this.el.warnings.classList.toggle("hidden", !warnings.length);
      this.el.references.replaceChildren(...(this.item.references || []).map(reference => {
        const li = this.document.createElement("li");
        li.textContent = typeof reference === "string" ? reference : `${reference.filename || reference.image_id || "Verified example"}${typeof reference.similarity === "number" ? ` · similarity ${reference.similarity.toFixed(3)}` : ""}${reference.reason ? ` · ${reference.reason}` : ""}`; return li;
      }));
      if (!this.item.references?.length) { const li = this.document.createElement("li"); li.textContent = "No relevant verified reference was retrieved for this prediction."; this.el.references.append(li); }
      this.controls();
    }
    renderLearning(status) {
      this.classes = classEntries(status.class_names);
      this.classKinds = status.class_kinds || {};
      this.el.class.replaceChildren(...this.classes.map(([id, name]) => { const option = this.document.createElement("option"); option.value = String(id); option.textContent = name; return option; }));
      const deployed = status.current_model_version || "Unavailable", evaluation = status.latest_evaluation;
      const evaluationText = !evaluation ? "No evaluation yet" : typeof evaluation === "string" ? evaluation : evaluation.summary || evaluation.status || "Recorded; see local evaluation report";
      this.el["learning-status"].textContent = `${status.verified_examples ?? 0} verified · ${status.corrected_annotations ?? 0} corrections recorded · Model ${deployed} · ${status.pending_training ?? 0} awaiting training · ${evaluationText}`;
      const baseline = status.baseline_indexing;
      if (baseline?.state === "indexing") this.el["learning-status"].textContent += " · Indexing original manual examples…";
      else if (baseline && ["errors", "unavailable", "source_changed"].includes(baseline.state)) this.el["learning-status"].textContent += " · Baseline needs attention";
      if (status.training_blocked_reason) this.el["learning-status"].textContent += " · Training awaits validation coverage";
      if (status.reference_index?.status === "indexing") this.el["learning-status"].textContent += " · Preparing reference evidence…";
      const rows = [["Approved without editing", percent(status.approved_without_edit_rate)], ["Verified examples", String(status.verified_examples ?? 0)], ["Corrected annotations", String(status.corrected_annotations ?? 0)], ["Corrected masks", String(status.corrected_masks ?? 0)], ["Declined images", percent(status.declined_rate)], ["Average review time", typeof status.avg_review_time_ms === "number" ? `${(status.avg_review_time_ms / 1000).toFixed(1)} s` : "Not measured"], ["Deployed model", deployed], ["New learning data", String(status.pending_training ?? 0)], ["Latest evaluation", evaluationText], ["Frequent class corrections", Object.entries(status.corrected_classes || {}).map(([name, count]) => `${name}: ${count}`).join(", ") || "None recorded"]];
      if (status.primary_baseline) rows.push(["Learning baseline", status.primary_baseline.name || status.primary_baseline.dataset_id], ["Secondary examples retained", String(status.retained_secondary_examples ?? 0)]);
      this.el["progress-values"].replaceChildren(...rows.map(([name, value]) => { const row = this.document.createElement("div"), term = this.document.createElement("dt"), description = this.document.createElement("dd"); term.textContent = name; description.textContent = value; row.append(term, description); return row; }));
      if (status.training_blocked_reason) { const row = this.document.createElement("div"), term = this.document.createElement("dt"), description = this.document.createElement("dd"); term.textContent = "Training status"; description.textContent = status.training_blocked_reason; row.append(term, description); this.el["progress-values"].append(row); }
    }
  }
  const api = {Review, bbox, maskValid, hasMask, editableMask, rings, replaceMask, nearestEdge, pointInImage, classEntries, reviewProblem};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AnnotationReview = api;
  if (typeof document !== "undefined") {
    const view = document.getElementById("view-review"), container = document.getElementById("annotation-review");
    if (view && container) {
      const review = new Review(document);
      new MutationObserver(() => { if (review.visible() && !review.editing && !review.busy) review.refresh(); }).observe(view, {attributes: true, attributeFilter: ["class"]});
      if (review.visible()) review.refresh();
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
