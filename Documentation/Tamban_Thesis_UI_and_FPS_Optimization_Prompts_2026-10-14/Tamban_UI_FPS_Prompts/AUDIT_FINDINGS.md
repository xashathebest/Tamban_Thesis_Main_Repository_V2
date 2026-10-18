# Source-Based UI & Performance Audit (October 14, 2026)

Scope: static inspection of `Thesis-main (2).zip`, plus review of bundled stored diagnostic reports. This is **not** a new real-camera benchmark. Actual reasons for the reported ~5 processed FPS must be confirmed on the user's Windows machine with the installed checkpoints.

## Performance findings and confidence

| Priority | Finding | Source | Confidence |
| --- | --- | --- | --- |
| High | Model 1 YOLO inference and tracking run on every *processed* live frame | `src/api/camera.py` `process_frame` ~979-983; `src/inference/yolo_fish_detector.py` `detect` ~284-310 | Confirmed design; time share unmeasured |
| High | Model 2 default is `full_frame` and interval 3, selected YOLO26m with 768 input | `src/api/app.py` ~40-50, ~85-102; `configs/active_model.json`; `models/MODEL_REGISTRY.json` | Confirmed |
| High | Inference is coupled to published annotated MJPEG frames: processing then JPEG then publish | `src/api/camera.py` `_run` ~1230-1263; `src/api/app.py` `_mjpeg_frames` ~1280-1296 | Confirmed design |
| High | Device selection falls back to CPU when CUDA is unavailable | `src/inference/yolo_fish_detector.py` `_resolve_device`; `src/inference/yolo_quality_model.py` `_resolve_device` | Confirmed; user's actual device unverified |
| Medium | Saved one-off still-image diagnostic used CPU for Model 2 and took 0.363 sec on that image | `results/diagnostic/yolo26m_test/report.json` | Confirmed file; **not** sustained live FPS |
| Medium | Every status poll assembles durable events and recalculates analytics; JS updates hidden charts/tables | `src/api/app.py` `_status_payload` and `_analytics`; `frontend/app.js` `render`, `getStatus`, `setInterval(getStatus, 900)` | Confirmed design; runtime cost unmeasured |
| Medium | MJPEG quality 82 encodes full annotated processing frame | `src/api/camera.py` ~1253 | Confirmed; actual cost needs JPEG timing |
| Medium | Calibration condition monitoring can process full-frame grayscale/HSV | `src/api/camera.py` `_update_image_statistics` ~794-849 | Confirmed conditional path |
| Critical measurement caveat | Enabling debug capture can enable Model 2 raw output at a 0.001 floor and save file artifacts | `src/api/camera.py` `set_runtime_diagnostics` ~319-334; `src/inference/yolo_quality_model.py` `_infer_parts` ~410-438 | Confirmed; avoid in baseline |
| Positive | Camera acquisition uses one reader with a capacity-one latest-frame queue, avoiding an ever-growing backlog | `src/api/camera.py` `_capture_frames`; `src/api/runtime_diagnostics.py` `LatestFrameQueue` | Already implemented; don't rewrite without cause |
| Positive | Runtime already records camera FPS, processed FPS, Model 1/2 latency, JPEG, overlays, queue drop counts | `src/api/runtime_diagnostics.py`; `frontend/app.js` `renderRuntimeDiagnostics` | Already present |

## Specific UI redundancies

- Two Settings entry points: sidebar `#sidebar-settings`, header `#settings-button` (`frontend/index.html`).
- Two Export entry points: sidebar `#sidebar-export`, header `#export-button`.
- Feed display checkboxes and Settings display checkboxes share the same `overlayControls` mapping (`frontend/app.js`).
- Sidebar `Analytics` is an anchor button that calls `showView('live')` and opens `#analytics-disclosure`; it is not an independent route/view (`frontend/app.js` ~1032).
- Model info is repeated in header pills, a dedicated Model view, and Settings drawer.
- Session stats, 'Latest completed fish', History and Review Queue have overlapping information. Merge **presentation**, not distinct persisted workflows.
- `renderAnalytics` and other expensive UI updates run on every 900 ms status render, not only when visible. `render()` also triggers history/review fetches when corresponding views are active.
- 'Observed regions' or 'detected features' must not be presented as automatic crack/brightness-based grading. Current automatic quality grading remains based on Model 2 parts.

## Most valuable next measurement

On the actual inspection machine, with debug capture **OFF**, record 60-120 seconds of:

- CPU, GPU, CUDA availability and actual device per model
- Capture FPS, processed FPS, MJPEG/browser-visible FPS and stale-frame replacement count
- Model 1 p50/p95, Model 2 p50/p95, tracker, association, HSV, overlays, JPEG, total processing, capture-to-process age
- Number of active fish and Model 2 calls per frame / per fish, selected model, image size, mode, interval
- Same-run counting accuracy, grade coverage, part-association ambiguity and class accuracy (if ground truth is present)

Only then set a realistic target and pick the largest measured bottleneck. A faster *unannotated* preview should not be misreported as higher model inference FPS.
