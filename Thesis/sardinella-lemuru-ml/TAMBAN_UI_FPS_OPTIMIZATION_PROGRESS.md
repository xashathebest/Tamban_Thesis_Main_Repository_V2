# Tamban UI and FPS optimization progress

The requested parent folder currently exists but is empty at `Documentation/Prompts_Folder_Done/Tamban_Thesis_UI_and_FPS_Optimization_Prompts_2026-10-14`. Its prompt subfolder is now a sibling: `Documentation/Prompts_Folder_Done/Tamban_UI_FPS_Prompts`. The 18 numbered Markdown files there are byte-equivalent, ignoring line endings, to the original tracked files at HEAD. Prefixes 01–18 are consecutive with no duplicates or gaps; `README.md` and `AUDIT_FINDINGS.md` are not numbered prompts. The existing working tree and prior fixes are preserved.

Reviewed the earlier UI/FPS, deep-code QA and final-polish trackers. Verified the recorded final isolated model-free log (588 passed, 6 skipped, 92 subtests), checkpoint compatibility log (2 CPU tests passed), and headless browser log. These do not establish camera FPS or independent fish-level accuracy. The user previously stated the independent videos and expert labels are not yet available.

| # | Actual filename | Status | Objective, existing implementation, changes and validation |
|---|---|---|---|
| 01 | 01_Measure_Real_FPS_And_Hardware.md | PENDING HARDWARE VALIDATION | Existing non-mutating collector and procedure verified; 61 tests and 40 subtests passed. Local API timed out; no live scene measurement. |
| 02 | 02_Make_Runtime_Telemetry_Accurate.md | PROVISIONALLY VALIDATED | Existing bounded timing and provenance checked; 48 tests, 48 subtests passed. Real overhead and synchronized CUDA comparison pending. |
| 03 | 03_Lightweight_Status_API_And_Analytics.md | ALREADY IMPLEMENTED AND VERIFIED | Existing live-status endpoint and session revision cache; 37 tests, 4 subtests passed; prior synthetic fixture results retained. |
| 04 | 04_Skip_Hidden_Frontend_Renders.md | ALREADY IMPLEMENTED AND VERIFIED | Hidden-view gating, stale request cancellation and hidden-tab handling verified in local browser; physical live performance pending. |
| 05 | 05_Compare_Model2_FullFrame_Vs_Crop.md | BLOCKED | Comparison tooling and 47 tests, 48 subtests verified; independent labeled clips and paired target measurements unavailable. |
| 06 | 06_Check_CPU_GPU_And_Safe_Precision.md | PENDING HARDWARE VALIDATION | CPU-only PyTorch detected; device and model selection tests passed. CUDA and precision comparisons are unavailable. |
| 07 | 07_Test_Model_Input_Sizes.md | BLOCKED | Input sizes and model switching are exposed; labeled size-sweep accuracy and target timings are unavailable. |
| 08 | 08_Camera_Acquisition_And_JPEG.md | PENDING HARDWARE VALIDATION | Capture ownership and calibration tests checked; camera/backend and JPEG comparisons require the physical setup. |
| 09 | 09_Decouple_Preview_From_Inference.md | PROVISIONALLY VALIDATED | Existing optional bounded raw preview passed 35 tests and 36 subtests; live stream rates remain unmeasured. |
| 10 | 10_Optional_Model1_Frame_Gating.md | BLOCKED | Explicit prerequisite that Model 1 dominates has not been measured; no experimental gating was introduced. |
| 11 | 11_Simplify_Sidebar_And_Navigation.md | PROVISIONALLY VALIDATED | Existing navigation checked with keyboard and six responsive widths; new screenshots captured. |
| 12 | 12_Operator_First_Live_Inspection_UI.md | PROVISIONALLY VALIDATED | Existing operator states and grading distinctions tested; physical camera and first-time operator use remain pending. |
| 13 | 13_Consolidate_Display_Settings_And_Models.md | PROVISIONALLY VALIDATED | Existing display controls, settings locks, model selection and calibration checked; hardware readbacks remain pending. |
| 14 | 14_History_Review_Analytics_UX.md | PROVISIONALLY VALIDATED | History, review, exports and lazy analytics checked using synthetic fixtures and browser workflows. |
| 15 | 15_Responsive_Accessible_UI_States.md | PROVISIONALLY VALIDATED | Fixed duplicate Start actions; keyboard/state checks and screenshots at six widths passed; accessibility field audit pending. |
| 16 | 16_Run_Full_Speed_And_Accuracy_Regression.md | BLOCKED | Full software suite and two CPU checkpoint tests pass; paired real performance and independent accuracy remain unavailable. |
| 17 | 17_Cleanup_Documentation_And_HandOff.md | PROVISIONALLY VALIDATED | Added operator/developer handoff; runtime default and static selector audit checked; field validation remains open. |
| 18 | 18_Optional_Validated_Performance_Presets.md | BLOCKED | Required scientifically acceptable performance tradeoffs have not been measured; no presets created. |

## 01 — Baseline measurement

Objective: measure capture and inference on the intended camera before choosing a bottleneck. Existing `src/evaluation/runtime_benchmark.py` performs non-mutating, warmed-up local collection with bounded queue counters, model/device/camera metadata and rolling timing windows; `docs/runtime_baseline.md` documents the three operator-declared scenes and warns that browser paint, synchronized GPU timing and accuracy are not established. `configs/active_model.json` selects `yolo26m_partdet`; the runtime configuration can differ via settings or environment, so current running configuration cannot be inferred from that file alone. No runtime source was modified.

Command: `python -B -m pytest -q -p no:cacheprovider tests/test_runtime_benchmark.py tests/test_runtime_diagnostics.py tests/test_operator_dashboard.py --tb=short` — **61 passed, 40 subtests**. A local status request timed out; no running inspection was established. Empty, one-fish and overlapping real-camera baselines, browser display rate, overhead and causal bottleneck remain **PENDING HARDWARE VALIDATION**. The prior 5 FPS is an unverified report, not a measured result. Follow `docs/runtime_baseline.md` and `qa/final/performance_baseline.md` on the inspection machine.

## 02 — Runtime telemetry

Objective: accurate, bounded stage timing without changing predictions. Inspected `src/api/runtime_diagnostics.py`, `src/api/camera.py`, `src/inference/yolo_quality_model.py` and the frontend diagnostics renderer. Existing monotonic samples are bounded, snapshots copy under lock before sorting, full-frame call timing is recorded once, and provenance distinguishes host-observed asynchronous GPU calls and MJPEG consumer pacing. The recorder can be disabled at startup; no code was changed. `python -B -m pytest -q -p no:cacheprovider tests/test_runtime_diagnostics.py tests/test_runtime_benchmark.py tests/test_status_polling.py tests/test_tail_optional_policy.py --tb=short` — **48 passed, 48 subtests, one warning**. Comparable enabled/disabled live overhead and CUDA-synchronized timing remain pending a representative device and session; `docs/runtime_baseline.md` provides the procedure.

## 03 — Lightweight status and analytics

Objective: avoid rebuilding durable history for every fast UI poll while preserving historical APIs and counters. Existing `src/api/app.py` provides `/api/status/live` beside the backward-compatible `/api/status`, `src/api/database.py` records per-session event revisions, and `frontend/app.js` refreshes analytics on revision changes. No source changes were necessary. `python -B -m pytest -q -p no:cacheprovider tests/test_status_polling.py tests/test_history_performance_qa.py tests/test_operator_dashboard.py --tb=short` — **37 passed, 4 subtests, one warning**. Prior `results/performance/status_polling_fixtures.md` measured synthetic 10,000-row legacy/live p95 of 226.910/5.299 ms and response size 568,003/12,334 bytes; each made one SELECT. This in-process fixture is not a camera or production-network FPS measurement. Real concurrency and long-running behavior remain subject to field testing.

## 04 — Hidden frontend updates

Objective: limit hidden rendering and stale requests without degrading freshness. Existing `frontend/app.js` gates analytics, model and diagnostics by visibility; it aborts old requests, guards revisions, and pauses polling while hidden. No source changes were necessary. `python -B tests/dashboard_status_smoke.py` passed: two-page history, review, stale-request cancellation and hidden/resumed polling. `node --check frontend/app.js` passed. Previously recorded `results/performance/browser_render_profile.md` used six stopped-camera samples: live render p50/p95 0.80/0.98 ms before and 0.20/0.28 ms after, 252/132 mutation records and 6/0 closed-analytics redraws. These browser wall-clock observations are not CPU utilization or camera FPS; live-camera effects remain pending.

## 05 — Model 2 mode and scheduling comparison

Objective: compare full-frame and crop across 0/1/3/6-plus fish and intervals 1–4, measuring ownership, coverage, counting and grade safety before recommending a configuration. Existing `src/evaluation/model2_schedule_benchmark.py` and `docs/model2_schedule_benchmark.md` prepare the experiment and disclose its replay limitations. No runtime configuration or code was changed. `python -B -m pytest -q -p no:cacheprovider tests/test_model2_schedule_benchmark.py tests/test_runtime_diagnostics.py tests/test_association.py tests/test_tail_optional_policy.py --tb=short` — **47 passed, 48 subtests**. The user has already confirmed that the independent unannotated recordings and expert labels do not exist yet; paired accuracy/ownership and real timing cannot be measured. This phase is **BLOCKED**, not passed. Full-frame interval 3 remains the existing default and rollback baseline.

## 06 — CPU, GPU and precision

Objective: report actual model devices and compare supported precision modes before changing them. Existing device resolution falls back to CPU for auto selection and rejects unavailable explicitly requested CUDA; `src/api/app.py` reports requested and resolved devices and PyTorch CUDA availability. This environment reports PyTorch 2.14.0+cpu, no CUDA build and zero available CUDA devices. Previously recorded real-checkpoint CPU compatibility tests passed, but are not a throughput comparison. `python -B -m pytest -q -p no:cacheprovider tests/test_multi_model_selection.py tests/test_model_integrity_qa.py tests/test_runtime_diagnostics.py --tb=short` — **56 passed, 36 subtests, one warning**. No precision or device settings were changed. A warmed-up CPU/CUDA matrix, VRAM and FP16 accuracy/throughput remain **PENDING HARDWARE VALIDATION** on a properly configured target with independent labels.

## 07 — Model input sizes

Objective: compare recall, grading and speed at multiple input sizes before recommending one. The detector defaults to 640 unless overridden; Model 2's default comes from its active registry entry, can be overridden at startup, and is exposed in session/runtime metadata. Model switching tests are included in the phase 06 run (**56 passed, 36 subtests**). Independent labeled small/overlapping fish and comparable target timing do not exist yet, so the 512/640/768 sweep and accuracy tradeoffs are **BLOCKED**. No model input size or grading policy was changed.

## 08 — Camera capture and JPEG

Objective: measure capture and delivery before adjusting them, preserving calibration and image coordinates. Inspected `src/api/camera.py` and `src/api/camera_controls.py`: one capture owner feeds a latest-frame queue, and annotated JPEG quality remains 82. Existing camera settings and calibration checks passed: `python -B -m pytest -q -p no:cacheprovider tests/test_camera_calibration.py tests/test_camera_calibration_ui.py tests/test_camera_settings_atomic_qa.py --tb=short` — **13 passed**. No capture settings, JPEG settings or code changed. Physical backend/fourcc/readback and JPEG/network/browser comparisons, as well as hardware stop/restart, are **PENDING HARDWARE VALIDATION**; no before/after savings are claimed.

## 09 — Optional raw preview

Objective: separate camera preview responsiveness from AI processing without misleading overlays. The existing opt-in `FISH_RAW_PREVIEW_ENABLED` path in `src/api/raw_preview.py` shares the camera owner, uses bounded subscriber-aware encoding, and offers a distinct unannotated stream; annotated MJPEG remains available. It is disabled by default. `python -B -m pytest -q -p no:cacheprovider tests/test_raw_preview_qa.py tests/test_runtime_diagnostics.py --tb=short` — **35 passed, 36 subtests**. No code or settings changed. Physical multi-client stream FPS, display age, camera lifecycle and target-device resource usage still require live validation; no improvement in AI FPS is claimed.

## 10 — Experimental Model 1 scheduling

The prompt explicitly requires a measured dominant Model 1 bottleneck before prototyping gating. The baseline is unavailable, and independent counting/occlusion labels are also unavailable. Consequently this optional experiment is **BLOCKED**; no tracker, counting or scheduling changes were made. Phase 01 telemetry and phase 05 comparison tooling passed their model-free tests, but do not satisfy the experiment's prerequisite.

## 11 — Navigation

Previously duplicated desktop header actions now appear once in the sidebar, with the header retained at narrower widths. Live, History and Review remain views; Model and optional Expert remain accessible; Analytics is explicitly labeled as a Live subsection. Feed display controls and calibration remain accessible. Extended `tests/navigation_qa_smoke.py` to include 375 and 768 px and allow a separate screenshot destination, preserving earlier artifacts. `TAMBAN_NAV_SMOKE_OUTPUT=qa/ui_fps_optimization python -B tests/navigation_qa_smoke.py` passed keyboard navigation, analytics and single visible Settings/Export access at 375, 390, 768, 1280, 1366 and 1920 px; current stopped-view screenshots are in `qa/ui_fps_optimization/`. No before screenshots exist, and operator testing and physical-device access remain unverified. See `qa/final/13_navigation.md` for the earlier map.

## 12 — Operator-first live view

Existing Live view shows the camera, controls, session totals, result evidence and recent fish, with diagnostic detail available separately; `qa/final/14_live_states.md` records the stopped/starting/running/stopping/error behavior and known limits. The phase 11 browser run exercised those simulated states. `python -B -m pytest -q -p no:cacheprovider tests/test_operator_dashboard.py tests/test_session_lifecycle_qa.py tests/test_tail_optional_policy.py --tb=short` — **47 passed, 16 subtests**. No grading or UI source changed. Live camera behavior, first-time operator usability and before screenshots remain unverified; these checks do not constitute user acceptance.

## 13 — Settings and model details

Existing visible feed controls are consolidated beside the feed; hidden compatibility controls remain synchronized, model selection remains in the Model view, and physical calibration has its own drawer. The settings and calibration API locking behavior is preserved. `python -B -m pytest -q -p no:cacheprovider tests/test_settings_lock.py tests/test_settings_atomic_qa.py tests/test_multi_model_selection.py tests/test_camera_calibration_ui.py --tb=short` — **33 passed**; phase 11 browser checks exercised Settings and Escape at six widths. No source changes. Physical calibration/readback, assistive technology and a complete keyboard-only settings workflow are still pending.

## 14 — History, review and analytics

Existing history pagination, session-specific manual review and export preserve the AI verdict and audit history; analytics refreshes lazily by session revision. `python -B -m pytest -q -p no:cacheprovider tests/test_history_performance_qa.py tests/test_historical_review_qa.py tests/test_historical_export_qa.py tests/test_export_selection_qa.py --tb=short` — **35 passed, one warning**. `tests/historical_review_smoke.py` passed the past-session review and original-AI-grade checks; `tests/export_form_smoke.py` passed selection, validation and failure feedback; the phase 04 browser smoke covered pagination and stale responses. No source changed. These are synthetic workflows; live-to-record workflow and independent operator usability remain pending.

## 15 — Responsiveness, accessibility and feedback

Reviewing the 768-pixel screenshot exposed two simultaneous primary Start actions. Updated `frontend/app.js` to show the empty-feed Start while stopped or errored and the main-control Start during active lifecycle states, retaining the same handlers and disabled rules. Extended the navigation smoke to assert exactly one visible Start for five simulated lifecycle states. The six-width keyboard/browser smoke passed after the change, `node --check frontend/app.js` passed, and `python -B -m pytest -q -p no:cacheprovider tests/test_operator_dashboard.py tests/test_session_lifecycle_qa.py --tb=short` passed **37 tests, 4 subtests**. Screenshots and the concise checklist are in `qa/ui_fps_optimization/`; equivalent before captures are unavailable at 375 and 768 px. Contrast tooling, screen readers, complete focus-trap/zoom checks, live image overlay alignment and physical-device testing remain pending.

## 16 — Full performance and accuracy regression

`python -B tests/run_model_free_isolated.py` — **588 passed, 6 skipped, 92 subtests, 7 warnings** (`qa/ui_fps_optimization/16_model_free.log`). With explicit checkpoint opt-ins, `tests/test_checkpoint_smoke.py` and `tests/test_real_model2_reference.py` passed **2 CPU compatibility tests** (`16_checkpoint_cpu.log`); neither is independent accuracy. The actual paired same-camera FPS, latency, counting, ownership and grade comparison is **BLOCKED** by absent target scenes and expert labels. Added `results/performance/performance_report.md` and `comparison.csv`, explicitly marking all real metrics unmeasured; no fabricated baseline or candidate is presented. Reproduction guidance exists in `docs/runtime_baseline.md` and `docs/model2_schedule_benchmark.md`.

## 17 — Documentation and handoff

Added `docs/ui_fps_handoff.md` and linked it from `README.md`: operator flow, evidence terminology, current defaults, flags, reproduction, rollback and open validation gates. README's existing `full_frame` and interval-3 defaults agree with current code; no unsupported optimal configuration was selected. A static HTML ID scan found no duplicates; three literal JavaScript ID references absent from static HTML are deliberately constructed dynamically (`history-analysis-dialog`, `grading-settings-section`, `history-verdict-status`). No selector or CSS was removed without evidence that it was dead. JavaScript syntax and the browser workflow were checked in phase 15, with the full isolated regression in phase 16. Static scans do not prove all dynamic selectors or accessibility work correctly; actual camera and operator checks remain pending.

## 18 — Optional validated presets

The prompt permits presets only when phases 05–08 and 16 establish acceptable measured tradeoffs. Those experiments remain blocked or pending, so no performance profiles, silent threshold changes or scheduling presets were introduced. The existing clearly labeled opt-in raw preview is not marketed as an AI speed or validated accuracy preset. Revisit only after the target-camera and independent-label gates have passed.

## Final regression and status

After phase 18, `python -B tests/run_model_free_isolated.py` passed **588 tests, 6 skipped, 92 subtests and 7 warnings** (`qa/ui_fps_optimization/final_model_free.log`). The six-width keyboard and lifecycle browser smoke passed (`final_browser.log`); JavaScript syntax and a scoped `git diff --check` passed. The comparison CSV has six consistently shaped scenario rows with blank, explicitly unmeasured metrics. The preceding checkpoint-backed CPU compatibility tests passed 2 tests. Results comprise 2 already implemented and verified phases, 8 provisional phases, 3 pending hardware validation phases and 5 blocked phases; none remains unreviewed. These software results do not establish a camera FPS improvement, independent grade accuracy, accessibility conformance or release readiness. Existing working-tree changes remain uncommitted.
