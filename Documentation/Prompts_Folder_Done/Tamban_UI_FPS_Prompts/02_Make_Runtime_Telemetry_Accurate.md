# 02 - Accurate, Low-Overhead Stage Timing

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Make runtime diagnostics trustworthy and lightweight enough to decide what to optimize. The tool must not slow the application significantly or change predictions.

## Inspect
`src/api/runtime_diagnostics.py`, `src/api/camera.py`, `src/inference/yolo_fish_detector.py`, `src/inference/yolo_quality_model.py`, `src/inference/model_adapters.py`, `frontend/app.js` `renderRuntimeDiagnostics`.

## Implementation
- Verify and, only if necessary, correct timings for camera capture, Model 1, tracker, Model 2, association, part assignment, HSV, grading, overlays, JPEG, total processing, MJPEG dispatch, frame age and frontend DOM work. Use monotonic clocks.
- GPU operations may be asynchronous. Compare existing timings against appropriately synchronized benchmarks or CUDA events for **profiling only**; avoid global device synchronization in the production hot loop.
- Include Model 2 invocation count, active fish count, selected mode, p50/p95 sample sizes, capture FPS, processed FPS, and queue replacements. Label time units and provenance clearly.
- Keep bounded memory (the existing rolling-window model); no file writes on each frame. Guard sampling rate and avoid lengthy serialization inside the inference lock.
- Expose a lightweight machine-readable read-only diagnostics endpoint or extend the existing one without breaking clients; avoid enabling raw candidate capture.
- Add unit tests for low sample counts, missing GPU, no camera, monotonic values, zero activity, empty samples and multiple model calls per frame.

## Acceptance
Capture a performance trace where stage measurements are reproducible, do not double-count known stages, and clean-mode FPS is comparable with telemetry disabled. Do not label asynchronous GPU dispatch time as completed inference latency.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
