/* Approved training exports and centralized classes share the canonical store. */
(() => {
  "use strict";
  function selection(scope, selected, current) {
    if (scope === "all") return null;
    if (scope === "current") {
      const id = current?.image_id || current?.id;
      if (!id) throw new Error("Open an image before choosing Current image.");
      return [String(id)];
    }
    if (!selected?.length) throw new Error("Select images in the gallery first.");
    return [...new Set(selected.map(String))];
  }
  function reportText(report) {
    const errors = report.errors || [], warnings = report.warnings || [];
    const rows = [`${report.valid ? "Validation passed" : "Validation failed"} · ${errors.length} errors · ${warnings.length} warnings`];
    for (const [title, items] of [["Error", errors], ["Review", warnings]]) {
      for (const item of items.slice(0, 40)) rows.push(`${title}: ${item.image_id ? item.image_id + " · " : ""}${item.annotation_id ? item.annotation_id + " · " : ""}${item.message || String(item)}`);
      if (items.length > 40) rows.push(`${items.length - 40} further ${title.toLowerCase()} messages are included in the downloaded report.`);
    }
    return rows.join("\n");
  }
  if (typeof module !== "undefined" && module.exports) module.exports = {selection, reportText};
  if (typeof document === "undefined") return;
  const $ = id => document.getElementById(id), panel = $("annotation-training-panel");
  if (!panel) return;
  let classes = [], busy = false, lastReport = null;
  const bridge = () => window.annotationLibrary;
  const write = (id, message, error = false) => { $(id).textContent = message; $(id).classList.toggle("training-error", error); };
  async function request(path, options = {}) {
    if (bridge()?.request) return bridge().request(path, options);
    const response = await fetch(path, {...options, credentials: "same-origin", cache: "no-store"});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`); }
    return response;
  }
  async function json(path, payload, method = "POST") {
    return (await request(path, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)})).json();
  }
  async function flush() {
    if (bridge()?.flush && !await bridge().flush()) throw new Error("The current changes could not be saved. Resolve the save message before continuing.");
    if (bridge()?.canExport && !bridge().canExport()) throw new Error("Finish the current mask edit and wait for saving to complete.");
  }
  function download(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  function chosenIDs() { return selection($("training-scope").value, bridge()?.getSelection?.() || [], bridge()?.getCurrent?.()); }
  async function eligibleIDs() {
    const chosen = chosenIDs();
    const registry = await (await request("/api/annotations/datasets")).json();
    const selectedDataset = bridge()?.getDataset?.();
    if (registry.primary_dataset_id && selectedDataset === "") throw new Error("Choose a single dataset in the library before exporting training labels. Primary and secondary manual baselines stay separate.");
    const dataset = selectedDataset || registry.primary_dataset_id || null;
    const listing = await (await request("/api/annotations/images")).json();
    const datasetOf = row => row.dataset_id || row.baseline?.dataset_id || row.metadata?.dataset_id || (row.baseline ? "v2-coco-v7" : null);
    const rows = listing.images.filter(row => (!dataset || datasetOf(row) === dataset) && (chosen === null || chosen.includes(row.id)));
    const eligible = rows.filter(row => ["approved", "manual_verified"].includes(row.status));
    const excluded = rows.length - eligible.length;
    if (!eligible.length) throw new Error("No approved images or original manual baseline images match this selection. Review and approve new predictions first.");
    return {ids: eligible.map(row => row.id), excluded};
  }
  async function training(exporting) {
    if (busy) return;
    busy = true; $("training-validate").disabled = true; $("training-download").disabled = true;
    write("training-result", exporting ? "Validating approved labels and preparing the dataset…" : "Checking images, pixel masks, classes and object associations…");
    try {
      await flush();
      const {ids, excluded} = await eligibleIDs();
      lastReport = await json("/api/annotations/validate", {image_ids: ids});
      $("training-report-download").disabled = false;
      write("training-result", reportText(lastReport) + (excluded ? `\n${excluded} unreviewed, corrected or rejected images excluded.` : ""), !lastReport.valid);
      if (!lastReport.valid || !exporting) return;
      const format = $("training-format").value;
      const response = await request("/api/annotations/export", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({format, image_ids: ids, split: $("training-split").checked})});
      const filename = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] || `fish-${format}.zip`;
      download(await response.blob(), filename);
      write("training-result", reportText(lastReport) + `\nDownloaded ${ids.length} images with approved or original manual annotations and exact PNG masks.` + (excluded ? ` ${excluded} unreviewed/corrected/rejected images excluded.` : "") + (!$("training-split").checked ? "\nNo validation/test split was created. Request a split before training an evaluation model." : ""));
    } catch (error) { write("training-result", error.message || String(error), true); }
    finally { busy = false; $("training-validate").disabled = false; $("training-download").disabled = false; }
  }
  function fillClass() {
    const item = classes.find(c => String(c.id) === $("training-class-select").value);
    if (!item) return;
    $("training-class-name").value = item.name; $("training-class-color").value = item.color;
  }
  async function loadClasses() {
    const data = await (await request("/api/annotations/classes")).json();
    classes = data.classes || [];
    const selected = $("training-class-select").value;
    $("training-class-select").replaceChildren(...classes.filter(c => c.active).map(c => {
      const option = document.createElement("option"); option.value = c.id; option.textContent = `${c.name} · ID ${c.id}`; return option;
    }));
    if (classes.some(c => c.active && String(c.id) === selected)) $("training-class-select").value = selected;
    fillClass();
  }
  async function changeClass(action) {
    if (busy) return;
    busy = true;
    try {
      await flush();
      if (action === "add") {
        await json("/api/annotations/classes", {name: $("training-new-class-name").value.trim(), kind: $("training-new-class-kind").value});
        $("training-new-class-name").value = "";
      } else {
        const id = $("training-class-select").value;
        if (!id) throw new Error("Choose a class first.");
        if (action === "remove") await request(`/api/annotations/classes/${encodeURIComponent(id)}`, {method: "DELETE"});
        else await json(`/api/annotations/classes/${encodeURIComponent(id)}`, {name: $("training-class-name").value.trim(), color: $("training-class-color").value}, "PATCH");
      }
      await loadClasses();
      if (bridge()?.refresh) await bridge().refresh();
      write("training-class-result", action === "remove" ? "Unused class removed. Used and historical class IDs are protected." : "Class configuration saved. Existing model mappings and annotation IDs are preserved.");
    } catch (error) { write("training-class-result", error.message || String(error), true); }
    finally { busy = false; }
  }
  $("training-validate").addEventListener("click", () => void training(false));
  $("training-download").addEventListener("click", () => void training(true));
  $("training-report-download").addEventListener("click", () => { if (lastReport) download(new Blob([JSON.stringify(lastReport, null, 2)], {type: "application/json"}), "dataset-validation.json"); });
  $("training-class-select").addEventListener("change", fillClass);
  $("training-class-add").addEventListener("click", () => void changeClass("add"));
  $("training-class-save").addEventListener("click", () => void changeClass("save"));
  $("training-class-remove").addEventListener("click", () => void changeClass("remove"));
  panel.addEventListener("toggle", () => { if (panel.open) void loadClasses().catch(error => write("training-class-result", error.message, true)); });
})();
