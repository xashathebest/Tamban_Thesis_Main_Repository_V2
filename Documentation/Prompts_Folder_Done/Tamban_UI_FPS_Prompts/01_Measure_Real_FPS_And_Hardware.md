# 01 - Capture the Real 5-FPS Bottleneck

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
**Measure first, optimize later.** Determine what limits the live annotated feed to approximately 5 processed FPS on the actual Windows inspection machine. Do not modify grading, thresholds, or model scheduling in this task.

## Inspect
- `src/api/app.py` device setup (`FISH_DETECTOR_DEVICE`, `FISH_QUALITY_DEVICE`), default sizes/mode/interval, `_device_report`, `/api/status`, `/api/debug/runtime`.
- `src/api/runtime_diagnostics.py` telemetry counters and `LatestFrameQueue`.
- `src/api/camera.py` `_capture_frames`, `process_frame`, `_run`; `frontend/app.js` diagnostics renderer.
- `configs/active_model.json` and `models/MODEL_REGISTRY.json`.

## Implementation
1. Add a repeatable, **non-mutating** benchmark collection procedure (script or documented steps) that logs a 60-120 second warmed-up live session in normal mode. Preserve existing counters and grading behavior.
2. Record device, PyTorch/CUDA availability, CPU/GPU model assignments, chosen Model 2 ID, model input sizes, actual camera resolution/FPS/backend, `quality_inference_mode`, and `quality_interval`.
3. Export bounded telemetry (JSON + readable Markdown/CSV) for capture FPS, processed FPS, queue replacements, Model 1/2 p50/p95, tracker, association, ROI, color/HSV, overlays, JPEG, total processing and capture-to-process age.
4. Compare empty conveyor, one fish and multiple overlapping fish. Include warm-up; mark missing checkpoints or camera as **not measured**.
5. Explain whether 5 FPS is a measured **processed** rate vs camera capture rate. Classify bottlenecks based on data, not assumption.

**Important:** `GET /api/debug/runtime` already exposes timing counters while diagnostic capture is off. Do **not** turn on the `Enable bounded debug capture` checkbox for a clean baseline: it changes raw part collection and may write debug artifacts.

## Acceptance
Produce `results/performance/baseline_YYYYMMDD.json`, a short `baseline.md`, and a summary showing the largest measured stage, measurement conditions and any unknowns. If running in an environment without the webcam/checkpoints, build the benchmark tooling but explicitly defer live claims to the research machine.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
