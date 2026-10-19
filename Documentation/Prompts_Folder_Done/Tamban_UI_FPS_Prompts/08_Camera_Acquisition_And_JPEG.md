# 08 - Optimize Camera Capture and MJPEG Delivery

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Measure and reduce camera/JPEG overhead if it matters on the research PC; preserve stable calibration and model input coordinates.

## Relevant code
`src/api/camera.py` `_open_capture`, `_capture_frames`, `_run`; `src/api/camera_controls.py`; MJPEG generator in `src/api/app.py`. Current processed frames are JPEG-encoded with quality 82. The current queue already drops stale frames instead of accumulating them.

## Implementation
- Record actual camera backend, fourcc, capture dimensions, hardware FPS, readback FPS and capture latency on Windows. Evaluate DirectShow vs MSMF and MJPG vs raw video only if the connected webcam supports them.
- Check whether saved camera processing resolution is actually applied to frames or only stored as calibration metadata; fix misleading display if necessary.
- Benchmark JPEG encoding at different supported preview resolutions/quality settings, including network transfer/browser image decode; don't degrade evidence that grading requires.
- Keep camera read only in the existing capture thread and respect camera-control locking, recorded calibration profile, provenance and restart behavior.
- Make preview encoding tunable independently of the images fed to models. Verify bounding-box transforms if output preview resolution changes.
- Do not chase minor JPEG savings if measurements show Model 1/2 dominate.

## Acceptance
A measured capture/JPEG before-after table, reliable camera stop/restart, accurate preview and processing resolution labels, and no impact on grading or saved crops.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
