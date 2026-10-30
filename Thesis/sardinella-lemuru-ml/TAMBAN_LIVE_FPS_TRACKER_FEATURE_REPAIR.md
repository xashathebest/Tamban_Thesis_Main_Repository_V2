# Tamban live FPS, tracker, feature, and application repair

Date: 2026-10-26; updated 2026-10-29. This record distinguishes verified behavior from work that
still needs physical-camera and independent research validation.

## Scope and specification status

The requested `Tamban_Thesis_Requirements_Dataset_Checklist_and_Validation_2026-10-20.docx`
was not present in the repository. The requirements reproduced in
`Documentation/bugfixes1.md`, the checked-in configuration, and the existing
application contracts were used instead. No claim below is based on an unread
14-page document.

| Status | Requirement handling |
|---|---|
| AGREED | Preserve Model 2 Head/Body/Tail evidence, temporal grading, and the configured tail-optional weights. |
| AGREED | Keep HSV/color measurements diagnostic only; they do not change grades. |
| PROPOSED | ByteTrack, full-frame ownership, replay performance, and feature-cost improvements were implemented and tested as described below. |
| PENDING | Missing-head rule, defect/crack thresholds, feature fusion, vendor agreement, accuracy acceptance, overlap tracking acceptance, and conveyor-deadline acceptance remain unapproved. |

## Actual execution path

`CameraInspectionService` owns capture, places the latest frame in a one-item
queue, calls `YoloFishDetector.predict`, scopes persistent IDs, runs the
scheduled `YoloQualityModel`, performs full-frame parent/part association,
passes evidence to `WeightedGradingEngine`, finalizes line-crossing events in
`InspectionState`, captures their durable session identity, and hands immutable
snapshots to an ordered background writer for `InspectionDatabase`. The writer
is bounded, FIFO, and visible in runtime diagnostics; it does not change
counting or grading decisions. FastAPI supplies the status/history/export/MJPEG
endpoints used by `frontend/app.js`.

The live color proxies flow from a Model 1 crop or Model 2 part box into the
grading result and UI. They remain rectangular-ROI diagnostics: no live fish
mask, texture, morphology, crack, or belly-defect measurement changes a grade.

## Repairs made

| Component | Initial finding | Implemented repair | Validation | Status |
|---|---|---|---|---|
| Tracker | The running backend used IoU fallback because `lap` was absent, and a loaded tracker could still display `checking` while idle. | Installed pinned `lap==0.5.13` in project-local `.venv`; validate its binary before ByteTrack construction; strict mode rejects fallback; report `ready` after successful tracker initialization. | Fresh strict backend and replay reported `ByteTrack`; restarted port 8000 reports `tracker_status: ready`. | Verified in `.venv` and after restarting port 8000. |
| Track identity | IDs could collide after stop/restart/reset; unconfirmed detections were dropped. | Scope IDs by tracker epoch; retain unmatched/conflicting raw boxes as untracked ownership competitors only. | Tracker, full-frame, lifecycle, and reset regressions. | Implemented; overlap acceptance remains pending. |
| Part ownership | An ambiguous part could affect a distant fish. | Mark only score-margin contenders ambiguous; preserve a distant fish's evidence. | Three-fish full-frame regression. | Verified by regression. |
| Model 2 live mode | A stale `crop` setting could bypass full-frame parent/part ownership in a multi-fish live session. | Whole-fish dashboard normalizes `FISH_QUALITY_INFERENCE_MODE=crop` to `full_frame`; crop mode remains isolated-tool/part-preview only. | Runtime-policy regression and live status report the effective full-frame mode. | Verified safeguard; overlapping-fish acceptance remains pending. |
| Camera/feed | State could become running before a frame, capture failures could strand processing, old JPEGs could reappear, and unavailable hardware had little actionable backend context. | First-frame transition, capture-error cleanup, frame-generation guards, a bounded DirectShow/Media Foundation/default attempt log, and safe preference of a saved recognized backend. | Lifecycle/backend-selection tests, replay MJPEG, clean stop. | Verified without physical camera. |
| Streaming | An idle MJPEG generator could delay server shutdown. | Converted processed/raw streams to cancellable async generators. | Stream cancellation tests and replay shutdown. | Verified. |
| Decision timing | No per-fish evidence distinguished tracker detection-to-decision time from a physical conveyor or actuator SLA. | Record first persistent Model 1 detection to the virtual count-line decision. An optional, unset-by-default deadline yields `not_configured`, `met`, or `missed` telemetry only; it never changes count, class, or grade. | Domain, cached-analytics, export, and frontend syntax regressions. | Software telemetry verified; physical acceptance limit pending. |
| Durable event persistence | Post-count SQLite writes ran inline in the camera listener, so storage latency could stall the frame path; any asynchronous replacement needed an explicit overflow and session-identity rule. | Added a single-worker bounded FIFO hand-off. It deep-copies the event plus its captured session ID; saturation applies ordered producer backpressure rather than a newer direct write. A retained writer failure is visible, keeps its failed head rather than silently discarding/reordering it, and causes the next enqueue or durability boundary to request a safe stop rather than continue with unrecorded fish. Close/reset/policy rotation/manual and structural review/export use a FIFO drain barrier before changing durable state. | Dispatcher, session-target, lifecycle, review, export, and runtime-diagnostics integration tests. | Software behavior verified; physical throughput and storage-outage soak validation remain pending. |
| Diagnostics | Unavailable measures were unclear. | UI now shows devices, tracker, stage timing, frame and durable-event queue health, server capture-to-publish/event-persistence/MJPEG timing, and this browser's bounded image-load event rate. Browser paint/network latency remains `Not measured`. | Focused runtime regressions, browser diagnostic smoke, and static frontend syntax check. | Verified as software/browser-event telemetry only. |
| Feature cost | Live UI needed 11 HSV/coverage values but calculated unrelated offline statistics. | Added `summary_only` color extraction in the live path. | Exact-value checks on existing fish crops. | Verified component optimization. |
| Analytics/export | Review queue, unknown Model 2 status, provisional support, some evidence fields, and historical-run export access were misleading or incomplete. | Corrected queue accounting, Ungraded reasons, exports, review worksheet selection, and added a dashboard selector that submits the exact durable `session_id` for a historical run. | Focused analytics/history/export tests and a browser payload smoke test. | Verified in software. |

## Runtime and dependency findings

The accessible Python is `C:\Users\User\AppData\Local\Python\bin\python.exe`
(Python 3.14.6). It initially had PyTorch 2.14.0 CPU-only, Ultralytics 8.4.138
(below the declared `>=8.4.142,<9` requirement), and no `lap`. A disposable
project-local environment installed `ultralytics==8.4.142` and `lap==0.5.13`;
real checkpoint/reference, tracker, pipeline, and association tests passed
before the exact Ultralytics version was promoted to the project `.venv`.
`torch.cuda.is_available()` was `False`, although `nvidia-smi` reported an
NVIDIA GeForce RTX 2050 (driver 610.74, 4096 MiB). Both models run on CPU.
CUDA acceleration is **not** claimed.

The project-local `.venv` now contains `ultralytics 8.4.142` and `lap 0.5.13`;
importing `lap` and creating the real Ultralytics `BYTETracker` succeeded. The
stopped port-8000 backend was replaced with the project-local strict ByteTrack
environment. Its status endpoint reports `ByteTrack`, `tracker_status: ready`,
no tracker warning, both models ready on CPU, and `bytetrack_required: true`.

Dependencies changed: only project-local `.venv` packages were installed or
upgraded (`lap==0.5.13`, `ultralytics==8.4.142`). No global Python package was
changed. The temporary compatibility environment was removed after validation.

## Measured results

### Component measurement

On three existing `feature_mask_examples` crops, the old diagnostic extraction
had median times of 19.1-47.4 ms per crop. The live summary path measured
4.4-6.0 ms per crop after warm-up. All 11 UI values matched the full extractor
exactly. This is a CPU component measurement, not end-to-end camera FPS. No
pre-repair live-camera FPS baseline exists because no physical camera was
available; the replay is not a before/after physical-camera comparison.

### QA-only prerecorded replay

Physical camera indices 0-3 could not open through DirectShow, Media Foundation,
or the default OpenCV backend. A QA-only server replacement therefore fed
`results/tamban_inference/20260916_070726/camera_annotated.mp4` from frame 350
at 30 FPS into the real application pipeline, using a temporary database.

| Metric | Result |
|---|---:|
| Active tracker | ByteTrack |
| Camera-capture rate | 30 FPS |
| Published AI-processing rate | 13.9 FPS |
| Model 1 p50 host time | 62.474 ms |
| Model 2 p50 host time | 234.154 ms (7 calls) |
| Grading / HSV p50 | 27.359 / 26.978 ms |
| Queue stale-frame drops | 225 of 320 captured frames |
| MJPEG endpoint | HTTP 200 with JPEG bytes |
| Stop/shutdown | Clean stopped state; graceful server shutdown succeeded |

The recording is already annotated and lacks independent fish truth. It cannot
establish accuracy, ownership correctness, conveyor deadline compliance, or a
before/after physical-camera FPS claim.

## Validation performed

- Model-free isolated suite, excluding `tests/test_bc_texture_experiment.py`:
  **636 passed, 6 skipped, 92 subtests passed** in 24.23 s.
- The excluded texture experiment cannot import SciPy because Windows Application
  Control blocked `scipy.optimize._pava_pybind`; no workaround was attempted.
- Final real-checkpoint smoke plus real reference-image integration in the
  promoted project runtime: **2 passed**.
- Disposable Ultralytics 8.4.142 validation: **30 passed** across real
  checkpoint/reference, tracker, pipeline, and association tests.
- Post-hardening focused suite: **70 passed, 36 subtests passed**.
- Restarted production backend: ByteTrack strict mode and both models reported
  ready; it reports `tracker_status: ready`; its `Analyze image` endpoint
  processed the reference image (7 fish, Model 2 available, 2 Class C and 5
  Ungraded) without starting a camera session.
- Tracker/association/lifecycle focused suite: **127 passed, 1 skipped,
  59 subtests passed**.
- Analytics/history/export focused suite: **77 passed, 17 subtests passed**.
- Camera/lifecycle focused suite: **62 passed, 4 subtests passed**.
- Final timing/camera diagnostics focused suite: **88 passed, 36 subtests
  passed** in 6.33 s (one existing FastAPI/Starlette deprecation warning).
- Durable timing/analytics/export regression follow-up: **46 passed** across
  database, conveyor timing, export selection, and history-performance tests
  (one existing FastAPI/Starlette deprecation warning).
- Durable FIFO persistence follow-up: **92 passed, 36 subtests passed** across
  dispatcher, target-session, lifecycle, manual/structural review, export,
  status, diagnostics, and tracker regression coverage (one existing
  FastAPI/Starlette deprecation warning). This is software-only validation,
  not a physical-conveyor throughput or storage-outage soak result.
- Full regression after the durable FIFO integration, excluding the existing
  blocked SciPy texture experiment: **652 passed, 6 skipped, 92 subtests
  passed** in 19.50 s (the existing seven warnings remain).
- Final restarted local API validation after the FIFO integration: strict
  ByteTrack was `ready`, both models were `ready` on CPU, camera was
  disconnected/stopped, and the durable queue reported `0 / 256`, drained,
  with no retained failure. The dashboard returned HTTP 200 and the checked-in
  reference image completed through `/api/analyze-image` (7 fish; Model 2
  available; 2 Class C and 5 Ungraded). No physical camera session was started.
- Rebuilt browser QA after the FIFO/UI changes: dashboard status/history/review
  smoke, export-form smoke, and responsive navigation at 375, 390, 768, 1280,
  1366, and 1920 px passed using the explicit test-only
  `TAMBAN_CHROME_NO_SANDBOX=1` opt-in. The dashboard smoke explicitly rendered
  `Event write queue (pending / capacity)` as `0 / 256`.
- `node --check frontend/app.js` passed after the timing and camera-status UI
  changes. This is a syntax check, not a physical-camera or browser-latency
  measurement.
- Final local API validation after the timing/diagnostics changes: the strict
  ByteTrack service reported both models `ready` on CPU with inspection stopped
  and camera disconnected; `POST /api/analyze-image` returned HTTP 200, 7 fish,
  and Model 2 available for a checked-in demo image. No physical camera session
  was started.
- Browser status/history/review and responsive navigation smoke passed at 375,
  390, 768, 1280, 1366, and 1920 px. Chrome used a QA-only `--no-sandbox`
  setting required by the execution environment.
- Re-ran the camera-free temporary-server browser checks after making that
  QA-only Chrome setting an explicit `TAMBAN_CHROME_NO_SANDBOX` opt-in:
  dashboard status/history/review, export form, historical-review isolation,
  and responsive navigation all passed. The flag is not an application setting
  and no physical camera or normal inspection database was used.
- Historical-run export follow-up: the dashboard now loads the 1,000 most
  recent durable sessions when Export opens. **Current session** keeps the
  existing no-ID request; **Specific inspection run** maps the chosen session
  to the existing `range: current_session` plus `session_id` API contract.
  The focused export/history/persistence suite passed **41 tests** (one
  existing FastAPI/Starlette deprecation warning), and the temporary-server
  Chrome smoke verified both payload forms using a seeded historical run.
- Current broad collection with only the texture experiment ignored reached
  **652 passed, 6 skipped** but `test_bc_color_experiment` then failed before
  application code ran because Windows Application Control blocked SciPy's
  native `scipy.sparse.csgraph._traversal` extension. With both independent
  SciPy experiments excluded, the applicable suite passed **650 tests, 6
  skipped, 92 subtests** in 25.33 s (the existing seven warnings remain).
- Browser-observed preview telemetry and device-badge follow-up: a bounded
  five-second client-side window now reports `This browser's MJPEG image-load
  FPS`; it deliberately does not claim paint/network or capture-to-display
  latency. The dashboard smoke deterministically verified 10.0 FPS, reset on
  stream detach, and correct healthy/neutral badges for device values `0`,
  `cuda:0`, `cpu`, and `unresolved`. The focused runtime/camera/persistence/
  export suite passed **88 tests, 36 subtests** (one existing FastAPI/Starlette
  deprecation warning).
- After the final frontend changes, all camera-free browser checks passed again:
  dashboard status/history/review, selected-run export, historical-review
  isolation, and responsive navigation at 375, 390, 768, 1280, 1366, and
  1920 px. They used the explicit QA-only `TAMBAN_CHROME_NO_SANDBOX=1` opt-in;
  they do not constitute a physical-camera or browser-paint-latency result.
- The documented local API was restarted after those changes with strict
  ByteTrack required. It reported ByteTrack and both models `ready` on CPU,
  inspection stopped, camera disconnected, and a healthy drained `0 / 256`
  durable queue. The checked-in reference image again completed through
  `/api/analyze-image` with 7 fish, Model 2 available, 2 Class C, and 5
  Ungraded; no physical camera session was started.

## Required component status

| Component | Initial problem | Implemented handling | Validation | Status |
|---|---|---|---|---|
| Camera | No usable physical device was available; lifecycle could expose stale frames. | First-frame state transition, backend attempts, error cleanup, generation guards. | Lifecycle regressions and replay; indices 0-3 had no usable hardware. | Software path verified; hardware pending. |
| Tracker | Missing `lap` caused IoU fallback; idle API state was ambiguous. | Project-local `lap`, strict launch, ByteTrack loading, explicit ready state. | Strict live status, replay, tracker regressions. | ByteTrack verified; overlap continuity pending. |
| Model 1 | Raw detections could be discarded before ownership competition. | Preserve unconfirmed raw detections as ungraded ownership competitors. | Detector/tracker/association regressions and reference upload. | Verified in tested pipeline. |
| Model 2 | Crop-local live mode could evade parent association. | Full-frame live ownership is enforced; Head/Body/Tail evidence stays per fish. | Ownership regressions, real reference upload, replay. | Verified for tested cases; overlap acceptance pending. |
| FPS | Old 5 FPS observation was not a measured comparable baseline. | Bounded latest-frame queues, Model 2 scheduling, live feature-cost reduction, per-stage telemetry. | QA replay measured 13.9 published AI FPS. | Replay-only measurement; no physical baseline. |
| Grading | Ambiguous/partial evidence could be misleading. | Temporal evidence, tail-optional weights, Ungraded reasons, and conservative ownership behavior preserved. | Grading, structural evidence, and export tests. | Approved policy preserved; missing-head/defect rules pending. |
| Features | Expensive non-UI color calculations ran in the live path. | `summary_only` extraction keeps the 11 diagnostic UI values; features remain non-grading diagnostics. | Exact output match on three crops. | Verified component optimization. |
| Frontend | Feed/reconnect and diagnostic states could be unclear. | Accurate stopped/error states, recognized CPU/CUDA device badges, runtime stages, browser-observed MJPEG image-load FPS, and `Not measured` where latency is unavailable. | Browser/responsive smoke and API checks. | Verified in QA environment. |
| Analytics | Review queue and evidence representations could misstate AI output. | Corrected counters, review selection, evidence fields, and durable-run disclosure. | Focused analytics/history/export regressions. | Verified. |
| Conveyor timing | Count-line events had no explicit elapsed decision evidence and no safe way to evaluate an approved timing limit. | Store immutable first-persistent-detection-to-virtual-decision timing, optional deadline status, export fields, analytics, and UI disclosure. | 11 domain timing tests; cached analytics/export and 88-test focused integration suite. | Telemetry verified; no physical deadline claim. |
| Durable persistence | SQLite event writes could block the camera listener, and a naive async fallback could misattribute or reorder a fish during session rotation. | FIFO background worker with immutable captured targets, ordered backpressure, failure retention, queue diagnostics, and drain barriers before direct durable mutation, export, session close, reset, or policy rotation. | Dispatcher, database concurrency, lifecycle, review, export, and diagnostics regressions. | Software path verified; real-load/storage-failure acceptance pending. |
| History / exports | Provisional support and unknown Model 2 data could be labeled incorrectly. | Preserve original AI fields separately from review fields; correct CSV/XLSX selection. | Focused export/history tests. | Verified. |

## Actual files modified

- `Documentation/run.md`; `README.md`; `.gitignore`; this repair report.
- `frontend/app.js`, `frontend/index.html`.
- `src/api/app.py`, `src/api/camera.py`, `src/api/database.py`,
  `src/api/event_persistence.py`, `src/api/domain.py`, `src/api/export.py`, and
  `src/api/runtime.py`.
- `src/features/color.py`; `src/inference/association.py`,
  `src/inference/grading_engine.py`, and `src/inference/yolo_fish_detector.py`.
- Regression coverage in `tests/test_association.py`,
  `tests/test_camera_backend_selection.py`, `tests/test_camera_lifecycle_repair.py`,
  `tests/test_conveyor_timing_qa.py`, `tests/test_export_selection_qa.py`,
  `tests/test_database.py`, `tests/test_event_persistence.py`,
  `tests/test_event_persistence_integration.py`, `tests/test_handcrafted_features.py`,
  `tests/test_history_performance_qa.py`,
  `tests/test_part_preview.py`, `tests/test_raw_preview_qa.py`,
  `tests/test_runtime_diagnostics.py`, `tests/test_tracker_backend_qa.py`, and
  `tests/test_yolo_two_model_pipeline.py`.
- Camera-free temporary-server UI smoke coverage in
  `tests/dashboard_status_smoke.py`, `tests/export_form_smoke.py`,
  `tests/historical_review_smoke.py`, and `tests/navigation_qa_smoke.py`; their
  QA-only Chrome sandbox opt-in is documented in `tests/README.md`.

## Remaining blockers and acceptance work

1. Connect/select the actual overhead camera and record empty, one-fish,
   separated, touching, overlapping, occlusion, entry/exit, lighting, and
   conveyor-speed passages using the runtime benchmark procedure.
2. Compare independently collected vendor labels with locked representative
   clips before selecting any FPS setting or grade claim.
3. Synthetic ByteTrack crossing checks showed an ID swap. Do not claim overlap
   stability or no cross-fish grading until reviewed real video proves it.
4. The IoU fallback remains functional but uses greedy matching and is not
   equivalent to ByteTrack under overlap. Launch with `FISH_REQUIRE_BYTETRACK=1`.
5. Dashboard totals persist across stop/restart until Reset, while default
   history/analytics cover the newest durable run after a restart/policy
   rotation. Older runs remain
   selectable. A logical-session redesign needs separate persistence, export,
   cache, and review validation.
6. The missing research DOCX, vendor/professor approvals, CUDA-enabled PyTorch,
   physical camera availability, and blocked SciPy experiment remain external
   constraints.
7. Durable event writes now use the bounded FIFO hand-off, but this has only
   software/regression coverage. A physical-load and intentional SQLite/storage
   failure soak is still required. The designed behavior is conservative: a
   full queue applies ordered backpressure; a retained writer failure is shown
   in Runtime Diagnostics, prevents a clean close/rotation/export, and keeps
   the durable session open rather than silently losing or misattributing a
   record. Operators need an approved recovery procedure before production
   acceptance.

## Final release readiness

**Not ready for physical-conveyor release.** The software is ready for the
documented strict-ByteTrack, CPU/replay QA workflow, but a physical-camera
benchmark, independently labeled overlap/occlusion validation, conveyor
deadline evidence, CUDA migration validation, and the pending research
approvals are required before production acceptance.

## Rollback

All code changes are local and version controlled. Revert the changed source
and test files together to restore prior behavior. The local `.venv` is ignored
by Git; removing it only removes the optional local dependency environment.
