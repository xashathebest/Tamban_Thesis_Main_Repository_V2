# 09 - Make Camera Preview Smooth Without Faking AI FPS

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Explore an **optional** smoother live camera preview even when inference remains near 5 processed FPS. Clearly distinguish raw camera preview from annotated processed frames.

## Current design
There is one camera capture thread and a capacity-one latest-frame queue, but `src/api/camera.py` `_run` publishes only after Model 1 -> optional Model 2 -> tracking/evidence -> overlays -> JPEG; `src/api/app.py` serves that processed MJPEG. Thus the preview itself waits for model work.

## Implementation
1. Design a minimal-risk read-only path from the **same existing camera owner** to a bounded, optionally downscaled **raw preview** stream, without creating a second `VideoCapture`.
2. Keep the original annotated processed MJPEG available. In the UI, offer a clearly labeled choice: `Smooth camera preview (unannotated)` vs `AI-annotated inspection feed`.
3. Show **Capture FPS**, **AI processing FPS**, and time/age of the last AI result separately. Do not draw stale fish boxes on a newer raw frame unless synchronizing metadata/frame IDs and coordinate scaling exactly.
4. Prevent a slow browser from causing unlimited queue growth, disk writes or blocking camera acquisition. Ensure stopping/starting/pausing the camera is race-safe and doesn't spawn orphan threads.
5. Test single and multiple clients, disconnect/reconnect, app shutdown, and count-line accuracy with skipped inference frames.

## Acceptance
Measure both stream rates; preview may improve while AI FPS stays unchanged. There must be no fabricated grading speedup or mismatch between displayed fish and grades.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
