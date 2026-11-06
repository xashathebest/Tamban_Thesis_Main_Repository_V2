/* Saved-session history and analytics. Reads durable records; never runs inference. */
(() => {
  "use strict";
  const GRADES = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
  const COLORS = {"Class A": "#087664", "Class B": "#175cba", "Class C": "#b54d0a", Rejected: "#b52e40", Ungraded: "#546c7a"};
  const state = {mounted: false, view: "", selected: "", sessions: [], sessionPage: 1, sessionPages: 1, sessionTotal: 0, page: 1, pages: 1, rows: [], total: 0, requests: new Map(), versions: new Map(), analyticsSessions: [], analytics: null, appliedAnalyticsScope: null, pendingDrilldown: null};
  const $ = id => document.getElementById(id);
  const number = value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
  const count = value => Math.max(0, number(value) ?? 0);
  const format = value => number(value) === null ? "Not recorded" : Number(value).toLocaleString(undefined, {maximumFractionDigits: 1});
  const percent = value => number(value) === null ? "Not recorded" : `${format(value)}%`;
  function gradeOf(row) {
    const analysis = row?.analysis || row?.quality_analysis || {};
    const fusion = analysis.feature_fusion;
    const grade = fusion?.schema_version === "feature_fusion_v1" ? fusion.final_grade
      : [row?.ai_final_grade, analysis.ai_final_grade, row?.final_grade, analysis.final_grade, row?.quality, analysis.quality, row?.final_class, row?.grade].find(value => value !== null && value !== undefined && value !== "");
    return GRADES.includes(grade) ? grade : "Ungraded";
  }
  function timestamp(value, dateOnly = false) {
    if (!value) return "Not recorded";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : dateOnly ? parsed.toLocaleDateString() : parsed.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
  }
  function duration(seconds) {
    const value = number(seconds);
    if (value === null) return "Not recorded";
    const minutes = Math.floor(Math.max(0, value) / 60);
    return minutes < 60 ? `${minutes}m ${Math.floor(Math.max(0, value) % 60)}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }
  function el(tag, className = "", text = null) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== null) element.textContent = String(text);
    return element;
  }
  function button(text, action, className = "button quiet") {
    const control = el("button", className, text);
    control.type = "button";
    control.addEventListener("click", action);
    return control;
  }
  function note(target, text, error = false) {
    if (!target) return;
    target.textContent = text;
    target.classList.toggle("error", error);
  }
  function escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  }
  function setBusy(id, busy) { $(id)?.setAttribute("aria-busy", String(busy)); }
  function abort(kind) {
    state.requests.get(kind)?.abort();
    state.versions.set(kind, (state.versions.get(kind) || 0) + 1);
  }
  async function json(path, kind) {
    abort(kind);
    const controller = new AbortController();
    const version = state.versions.get(kind);
    state.requests.set(kind, controller);
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
    try {
      const response = await fetch(path, {signal: controller.signal, cache: "no-store"});
      const data = await response.json();
      if (state.versions.get(kind) !== version) return null;
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status}).`);
      return data;
    } catch (error) {
      if (timedOut && state.versions.get(kind) === version) throw new Error("The saved-record request timed out. Refresh to try again.");
      throw error;
    } finally {
      clearTimeout(timeout);
      if (state.requests.get(kind) === controller) state.requests.delete(kind);
    }
  }
  function historyQuery(filters = {}) {
    const query = new URLSearchParams({range_name: filters.start_date || filters.end_date ? "custom" : "all", page: String(filters.page || 1), page_size: String(filters.page_size || 25)});
    for (const key of ["session_id", "start_date", "end_date", "search", "grade", "verdict", "reason_code", "evidence_region", "track_id"]) {
      if (filters[key] !== undefined && filters[key] !== null && filters[key] !== "") query.set(key, String(filters[key]));
    }
    return query;
  }
  function historyFilters() {
    return {session_id: state.selected, start_date: $("sh-start")?.value || "", end_date: $("sh-end")?.value || "", search: $("sh-fish")?.value.trim() || "", grade: ["graded", "accepted"].includes(state.pendingDrilldown?.grade) ? state.pendingDrilldown.grade : $("sh-grade")?.value || "", verdict: $("sh-verdict")?.value || "", page: state.page, reason_code: state.pendingDrilldown?.reason_code || "", evidence_region: state.pendingDrilldown?.evidence_region || ""};
  }
  function validDates(start, end, status) {
    if (start && end && start > end) { note(status, "Choose an end date on or after the start date.", true); return false; }
    return true;
  }
  function mount() {
    if (state.mounted || !$("session-history-workspace") || !$("view-analytics")) return;
    state.mounted = true;
    $("session-history-workspace").innerHTML = `
      <div class="session-workspace">
        <div class="sw-heading"><div><p class="eyebrow">SAVED INSPECTIONS</p><h2>Every run, in one place</h2><p>Review recorded AI results and evidence, with the camera online or offline.</p></div><button class="button quiet" id="sh-refresh" type="button">Refresh sessions</button></div>
        <div class="sw-layout">
          <aside class="sw-session-panel surface" aria-label="Saved sessions">
            <div class="sw-panel-head"><h3>Inspection sessions</h3><span id="sh-session-count"></span></div>
            <form id="sh-session-filters" class="sw-session-filters"><label>Find a session<input id="sh-session-search" type="search" placeholder="Session ID"></label><div class="sw-date-fields"><label>From<input id="sh-start" type="date"></label><label>Through<input id="sh-end" type="date"></label></div><button class="button quiet" type="submit">Apply dates / search</button></form>
            <button class="sw-all-sessions" id="sh-all" type="button">View all saved fish</button>
            <p class="sw-status" id="sh-session-status" role="status" aria-live="polite"></p><div id="sh-sessions" class="sw-session-list"></div>
            <nav class="sw-pagination" aria-label="Session pages"><button class="button quiet" id="sh-session-prev" type="button">Previous</button><span id="sh-session-page">Page 1</span><button class="button quiet" id="sh-session-next" type="button">Next</button></nav>
          </aside>
          <section class="sw-record-panel surface" aria-labelledby="sh-record-title">
            <div class="sw-panel-head"><div><p class="eyebrow">ORIGINAL AI RESULTS</p><h3 id="sh-record-title">All saved fish</h3><p class="sw-session-id" id="sh-selected-id"></p></div><div class="sw-export-actions"><button class="button quiet" id="sh-csv" type="button" disabled>Session CSV</button><button class="button quiet" id="sh-pdf" type="button" disabled>Session PDF</button></div></div>
            <form class="sw-record-filters" id="sh-record-filters"><label>Fish ID<input id="sh-fish" type="search" placeholder="e.g. Fish #4"></label><label>Final grade<select id="sh-grade"><option value="">All grades</option>${GRADES.map(grade => `<option>${grade}</option>`).join("")}</select></label><label>Verdict<select id="sh-verdict"><option value="">All verdicts</option><option value="AUTO_GRADED">Automatically graded</option><option value="NEEDS_REVIEW">Needs review</option></select></label><button class="button quiet" type="submit">Filter fish</button><button class="sw-clear" id="sh-clear" type="button">Clear filters</button></form>
            <p class="sw-status" id="sh-record-status" role="status" aria-live="polite"></p><p class="sw-drilldown hidden" id="sh-drilldown"></p><div id="sh-records" class="sw-record-groups"></div>
            <nav class="sw-pagination" aria-label="Fish record pages"><button class="button quiet" id="sh-prev" type="button">Previous</button><span id="sh-page">Page 1</span><button class="button quiet" id="sh-next" type="button">Next</button></nav>
          </section>
        </div>
      </div>`;
    window.TambanAnalytics?.mount({target: $("view-analytics"), onRecords: (filters, scope) => {
      state.appliedAnalyticsScope = {...scope}; drilldown(filters);
    }, onSessions: sessions => { state.analyticsSessions = sessions; }});
    const back = button("Back to Analytics", () => window.TambanInspection?.showView("analytics"));
    back.id = "sh-back-analytics"; back.classList.add("hidden");
    $("session-history-workspace").querySelector(".sw-heading").append(back);
    $("sh-refresh").addEventListener("click", () => { void loadSessions(); void loadRecords(); });
    $("sh-session-filters").addEventListener("submit", event => { event.preventDefault(); state.sessionPage = 1; state.page = 1; void loadSessions(); void loadRecords(); });
    $("sh-record-filters").addEventListener("submit", event => { event.preventDefault(); state.page = 1; void loadRecords(); });
    $("sh-clear").addEventListener("click", () => { ["sh-fish", "sh-grade", "sh-verdict"].forEach(id => $(id).value = ""); state.pendingDrilldown = null; state.page = 1; void loadRecords(); });
    $("sh-all").addEventListener("click", () => openSession(""));
    $("sh-session-prev").addEventListener("click", () => { if (state.sessionPage > 1) { state.sessionPage--; void loadSessions(); } });
    $("sh-session-next").addEventListener("click", () => { if (state.sessionPage < state.sessionPages) { state.sessionPage++; void loadSessions(); } });
    $("sh-prev").addEventListener("click", () => { if (state.page > 1) { state.page--; void loadRecords(); } });
    $("sh-next").addEventListener("click", () => { if (state.page < state.pages) { state.page++; void loadRecords(); } });
    $("sh-csv").addEventListener("click", () => void exportCsv(state.selected));
    $("sh-pdf").addEventListener("click", () => void printSession(state.selected));
  }
  function sessionStatus(session) {
    return ({active: "Inspecting", completed: "Completed", interrupted: "Interrupted", starting: "Starting"})[session.status] || (session.ended_at ? "Completed" : "Open");
  }
  function sessionCount(session) { return number(session.fish_count ?? session.event_count); }
  function renderSessions(data) {
    state.sessions = Array.isArray(data.items) ? data.items : [];
    state.sessionPages = Math.max(1, Number(data.total_pages) || 1);
    state.sessionTotal = count(data.total ?? state.sessions.length);
    $("sh-sessions").replaceChildren();
    $("sh-session-count").textContent = `${format(state.sessionTotal)} saved`;
    $("sh-session-page").textContent = `Page ${state.sessionPage} of ${state.sessionPages}`;
    $("sh-session-prev").disabled = state.sessionPage <= 1;
    $("sh-session-next").disabled = state.sessionPage >= state.sessionPages;
    $("sh-all").setAttribute("aria-pressed", String(!state.selected));
    for (const session of state.sessions) {
      const card = button("", () => openSession(session.session_id), "sw-session-card");
      card.setAttribute("aria-pressed", String(state.selected === session.session_id));
      const heading = el("span", "sw-session-card-head");
      heading.append(el("strong", "", timestamp(session.started_at, true)), el("span", "sw-status-badge", sessionStatus(session)));
      const detail = el("span", "sw-session-card-detail", `${timestamp(session.started_at)} → ${session.ended_at ? timestamp(session.ended_at) : "In progress / not closed"}`);
      const metrics = el("span", "sw-session-card-metrics", `${sessionCount(session) === null ? "Fish count not recorded" : `${format(sessionCount(session))} fish`} · ${duration(session.duration_seconds)}`);
      const identity = el("small", "sw-session-id", session.session_id);
      const distribution = el("span", "sw-mini-distribution");
      const grades = session.grade_distribution;
      if (grades && typeof grades === "object") for (const grade of GRADES) {
        const item = el("span", "", `${grade.replace("Class ", "")} ${format(grades[grade] ?? 0)}`);
        item.style.setProperty("--sw-grade", COLORS[grade]);
        distribution.append(item);
      }
      card.append(heading, detail, metrics, distribution, identity);
      const activeSeconds = session.accumulated_active_seconds ?? session.active_seconds;
      if (number(activeSeconds) !== null) card.append(el("small", "sw-save-note", `${duration(activeSeconds)} active${session.autosaved_at ? " · autosaved" : session.auto_save_eligible ? " · save threshold reached" : ""}`));
      $("sh-sessions").append(card);
    }
    note($("sh-session-status"), state.sessions.length ? "" : "No saved sessions match these dates or session ID.");
  }
  async function loadSessions() {
    if (!validDates($("sh-start").value, $("sh-end").value, $("sh-session-status"))) return;
    setBusy("sh-sessions", true);
    note($("sh-session-status"), "Loading saved sessions…");
    const query = new URLSearchParams({limit: "1000", page: String(state.sessionPage), page_size: "8"});
    for (const [key, id] of [["search", "sh-session-search"], ["start_date", "sh-start"], ["end_date", "sh-end"]]) if ($(id).value) query.set(key, $(id).value);
    try {
      const data = await json(`/api/sessions?${query}`, "sessions");
      if (data) renderSessions(data);
    } catch (error) { if (error.name !== "AbortError") note($("sh-session-status"), error.message || "Saved sessions could not be loaded.", true); }
    finally { setBusy("sh-sessions", false); }
  }
  function openSession(sessionId) {
    state.selected = String(sessionId || "");
    state.page = 1;
    state.pendingDrilldown = null;
    ["sh-fish", "sh-grade", "sh-verdict"].forEach(id => $(id).value = "");
    renderSessions({items: state.sessions, total_pages: state.sessionPages, total: state.sessionTotal});
    void loadRecords();
  }
  function verdict(row) { return row.analysis?.verdict_status || row.verdict_status || "Not recorded"; }
  function reason(row) {
    const analysis = row.analysis || {};
    return analysis.verdict_reason_text || analysis.verdict_reason || analysis.reason || analysis.verdict_reason_code || (Array.isArray(analysis.reason_codes) ? analysis.reason_codes.join(", ") : "") || (gradeOf(row) === "Ungraded" ? "Reason not recorded" : "");
  }
  function partSummary(row) {
    const parts = row.analysis?.part_results || {};
    return ["Body", "Head", "Tail"].map(region => {
      const part = parts[region];
      return `${region}: ${part && typeof part === "object" ? part.present === true ? "present" : part.present === false ? "unavailable" : "not recorded" : "not recorded"}`;
    }).join(" · ");
  }
  function openEvidence(row) {
    if (typeof window.TambanInspection?.openHistoricalAnalysis === "function") {
      window.TambanInspection.openHistoricalAnalysis(row);
      $("history-analysis-dialog")?.addEventListener("close", () => { if (state.view === "history") void loadRecords(); }, {once: true});
    }
    else note($("sh-record-status"), "The evidence viewer is loading. Try again after the dashboard is ready.", true);
  }
  function fishCard(row) {
    const grade = gradeOf(row);
    const card = el("article", "sw-fish-card");
    card.style.setProperty("--sw-grade", COLORS[grade]);
    const head = el("div", "sw-fish-head");
    const title = button(`${row.fish_label || `Fish #${row.track_id}`} · ${grade}`, () => openEvidence(row), "sw-fish-title");
    const time = el("span", "sw-fish-time", timestamp(row.timestamp));
    head.append(title, time);
    const evidence = el("p", "sw-fish-anatomy", partSummary(row));
    const status = el("p", "sw-fish-reason", [verdict(row).replaceAll("_", " "), reason(row)].filter(Boolean).join(" · "));
    const actions = el("div", "sw-fish-actions");
    actions.append(button("View evidence", () => openEvidence(row)), button("CSV", () => void exportCsv(row.session_id, row.track_id)), button("PDF", () => printRows([row], `Fish #${row.track_id}`, row.session_id)));
    card.append(head, evidence, status, el("p", "sw-session-id", `Session ${row.session_id || "Not recorded"}`));
    if (row.manual_override || row.manual_final_grade) card.append(el("p", "sw-manual-note", `Operator review: ${row.manual_final_grade || row.manual_grade || "Recorded"}. Original AI grade retained above.`));
    card.append(actions);
    return card;
  }
  function renderRecords(data) {
    state.rows = Array.isArray(data.items) ? data.items : [];
    state.total = count(data.total);
    state.pages = Math.max(1, Number(data.total_pages) || 1);
    const selectedSession = state.sessions.find(session => session.session_id === state.selected) || state.analyticsSessions.find(session => session.session_id === state.selected);
    $("sh-record-title").textContent = state.selected ? selectedSession?.started_at ? `Session · ${timestamp(selectedSession.started_at, true)}` : "Saved session" : "All saved fish";
    $("sh-selected-id").textContent = state.selected || "Fish IDs are unique within their saved session.";
    $("sh-csv").disabled = !state.selected;
    $("sh-pdf").disabled = !state.selected;
    $("sh-csv").title = $("sh-pdf").title = state.selected ? "Export the complete saved session, including fish hidden by the current filters." : "Select a session to export the complete run.";
    $("sh-records").replaceChildren();
    for (const grade of GRADES) {
      const rows = state.rows.filter(row => gradeOf(row) === grade);
      if (!rows.length) continue;
      const group = el("section", "sw-grade-group");
      group.style.setProperty("--sw-grade", COLORS[grade]);
      const header = el("h4", "", `${grade} · ${rows.length} on this page`);
      group.append(header);
      for (const row of rows) group.append(fishCard(row));
      $("sh-records").append(group);
    }
    $("sh-page").textContent = `Page ${state.page} of ${state.pages}`;
    $("sh-prev").disabled = state.page <= 1;
    $("sh-next").disabled = state.page >= state.pages;
    note($("sh-record-status"), state.rows.length ? `${format(state.total)} matching fish · showing ${format((state.page - 1) * 25 + 1)}–${format((state.page - 1) * 25 + state.rows.length)}. Session exports include the complete run.` : "No saved fish match these filters. A zero-fish session still retains its session metadata.");
    $("sh-back-analytics")?.classList.toggle("hidden", !state.pendingDrilldown);
    const detail = state.pendingDrilldown?.reason_code ? `Filtered by recorded reason: ${state.pendingDrilldown.reason_code.replaceAll("_", " ")}` : state.pendingDrilldown?.evidence_region ? `Filtered by present ${state.pendingDrilldown.evidence_region} evidence` : state.pendingDrilldown?.grade === "graded" ? "Filtered to graded original AI final decisions." : state.pendingDrilldown?.grade === "accepted" ? "Filtered to Class A, Class B and Class C original AI final decisions." : "";
    $("sh-drilldown").textContent = detail;
    $("sh-drilldown").classList.toggle("hidden", !detail);
  }
  async function loadRecords() {
    const filters = historyFilters();
    if (!validDates(filters.start_date, filters.end_date, $("sh-record-status"))) return;
    setBusy("sh-records", true);
    note($("sh-record-status"), "Loading recorded fish…");
    try {
      const data = await json(`/api/history?${historyQuery(filters)}`, "records");
      if (data) renderRecords(data);
    } catch (error) { if (error.name !== "AbortError") note($("sh-record-status"), error.message || "Fish records could not be loaded.", true); }
    finally { setBusy("sh-records", false); }
  }
  function drilldown(filters) {
    const scope = state.appliedAnalyticsScope || window.TambanAnalytics?.getScope() || {session_id: "", start_date: "", end_date: ""};
    state.selected = filters.session_id ?? scope.session_id ?? "";
    state.page = 1;
    $("sh-start").value = filters.complete_session ? "" : scope.start_date;
    $("sh-end").value = filters.complete_session ? "" : scope.end_date;
    $("sh-grade").value = ["graded", "accepted"].includes(filters.grade) ? "" : filters.grade || "";
    $("sh-verdict").value = filters.verdict || "";
    $("sh-fish").value = "";
    state.pendingDrilldown = filters;
    $("sh-back-analytics")?.classList.remove("hidden");
    if (typeof window.TambanInspection?.showView === "function") window.TambanInspection.showView("history");
    else onView("history");
  }
  async function exportCsv(sessionId, trackId = null) {
    if (!sessionId) { note($("sh-record-status"), "Select a saved session before exporting its records.", true); return; }
    note($("sh-record-status"), "Preparing CSV from saved evidence…");
    try {
      const payload = {format: "csv", range: "all", session_id: sessionId, complete_analysis: true};
      if (trackId !== null) payload.track_ids = [Number(trackId)];
      const response = await fetch("/api/export", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `CSV export failed (${response.status}).`); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = el("a");
      link.href = url;
      link.download = `tamban_${String(sessionId).replace(/[^a-zA-Z0-9_-]/g, "_")}${trackId === null ? "_session" : `_fish_${trackId}`}.csv`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
      note($("sh-record-status"), "CSV downloaded with the recorded original AI verdict and available evidence.");
    } catch (error) { note($("sh-record-status"), error.message || "CSV export failed.", true); }
  }
  function reportHtml(rows, title, sessionId) {
    const columns = ["Fish ID", "Saved session", "Timestamp", "Original AI final grade", "Operator review", "Verdict status", "Anatomical evidence", "Reason", "Processing (ms)"];
    const records = rows.map(row => `<tr>${[row.fish_label || `Fish #${row.track_id}`, row.session_id || sessionId, timestamp(row.timestamp), gradeOf(row), row.manual_final_grade || row.manual_grade || "None recorded", verdict(row), partSummary(row), reason(row), format(row.processing_time_ms)].map(value => `<td>${escape(value)}</td>`).join("")}</tr>`).join("");
    const detailed = rows.map(row => `<article><h2>${escape(row.fish_label || `Fish #${row.track_id}`)} · ${escape(gradeOf(row))}</h2><p>Saved session: ${escape(row.session_id || sessionId)} · ${escape(timestamp(row.timestamp))}</p><p>${escape(partSummary(row))}</p><p>${escape(reason(row))}</p><h3>Recorded analysis and evidence</h3><pre>${escape(JSON.stringify(row.analysis || {status: "Analysis not recorded"}, null, 2))}</pre></article>`).join("");
    const session = state.sessions.find(item => item.session_id === sessionId) || state.analyticsSessions.find(item => item.session_id === sessionId);
    const metadata = session ? `<p>Started: ${escape(timestamp(session.started_at))} · Ended: ${escape(timestamp(session.ended_at))} · Duration: ${escape(duration(session.duration_seconds))} · Active inspection: ${escape(duration(session.accumulated_active_seconds ?? session.active_seconds))} · Status: ${escape(sessionStatus(session))}</p>` : "";
    return `<!doctype html><html><head><meta charset="utf-8"><title>${escape(title)} · Tamban</title><style>@page{size:A4 landscape;margin:14mm}body{font:11px/1.5 Arial,sans-serif;color:#173047}h1{font-size:24px}h2{font-size:16px}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid #ccd7df;padding:6px;text-align:left;overflow-wrap:anywhere}th{background:#edf4f8}thead{display:table-header-group}tr{break-inside:avoid}article{break-before:page}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:9px;border:1px solid #dbe4eb;padding:10px}p{overflow-wrap:anywhere}</style></head><body><h1>${escape(title)}</h1><p>Saved session: ${escape(sessionId || "Multiple saved sessions")} · ${rows.length} fish · Generated ${escape(new Date().toLocaleString())}</p>${metadata}<p>Grades are original AI verdicts. Mask reliability, operator reviews, and uncertain or unavailable evidence remain separate. Use your browser's Print dialog to save this report as PDF.</p><table><thead><tr>${columns.map(column => `<th>${column}</th>`).join("")}</tr></thead><tbody>${records}</tbody></table>${detailed}</body></html>`;
  }
  function printRows(rows, title, sessionId, popup = null) {
    const report = popup || window.open("", "_blank");
    if (!report) { note($("sh-record-status"), "Allow this site's print window to save the PDF report.", true); return; }
    report.document.open(); report.document.write(reportHtml(rows, title, sessionId)); report.document.close();
    report.focus(); report.print();
  }
  async function printSession(sessionId) {
    if (!sessionId) return;
    const popup = window.open("", "_blank");
    if (!popup) { note($("sh-record-status"), "Allow this site's print window to save the PDF report.", true); return; }
    popup.document.write("<!doctype html><title>Preparing inspection report</title><p>Loading the complete saved session…</p>");
    note($("sh-record-status"), "Preparing the complete session PDF report…");
    try {
      const rows = new Map();
      let expectedTotal = null;
      let page = 1, pages = 1;
      do {
        if (popup.closed) throw new Error("Report preparation cancelled.");
        const data = await json(`/api/history?${historyQuery({session_id: sessionId, page, page_size: 100})}`, "report");
        if (!data) return;
        if (expectedTotal === null) expectedTotal = count(data.total);
        if (count(data.total) !== expectedTotal) throw new Error("This session changed while the report was loading. Refresh and export again after inspection stops.");
        for (const row of Array.isArray(data.items) ? data.items : []) rows.set(`${row.session_id}:${row.track_id}`, row);
        pages = Math.max(1, Number(data.total_pages) || 1);
        page++;
      } while (page <= pages);
      if (rows.size !== expectedTotal) throw new Error("The saved session changed during pagination. Refresh before exporting the complete report.");
      printRows([...rows.values()], "Tamban inspection session", sessionId, popup);
      note($("sh-record-status"), `${format(rows.size)} fish loaded. Choose Save as PDF in the print dialog.`);
    } catch (error) { popup.close(); note($("sh-record-status"), error.message || "The complete session report could not be loaded.", true); }
  }
  function onView(name) {
    mount();
    if (!state.mounted) return;
    if (state.view !== name) for (const kind of ["sessions", "records", "analytics", "analytics-sessions"]) abort(kind);
    state.view = name;
    if (name === "history") { void loadSessions(); void loadRecords(); }
    void window.TambanAnalytics?.onView(name);
  }
  window.TambanSessions = {mount, onView, openSession, refresh: () => onView(state.view), gradeOf, historyQuery, reportHtml};
})();
