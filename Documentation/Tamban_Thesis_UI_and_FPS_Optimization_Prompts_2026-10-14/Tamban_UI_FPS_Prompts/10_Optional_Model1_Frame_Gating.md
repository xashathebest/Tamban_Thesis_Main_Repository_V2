# 10 - Experimental Model 1 Scheduling (Only If Dominant)

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Only if Prompt 01 proves Model 1 consumes the majority of the frame budget: prototype reduced Model 1 inference frequency while retaining reliable fish tracking/counting.

## Important risk
`src/api/camera.py` currently calls Model 1 on every processed frame. Simply skipping its calls could break ByteTrack/IoU tracking, fish IDs, counting-line crossings and per-fish body-part associations. Do not ship naive `if frame % N` logic.

## Implementation
- First benchmark Model 1-only with Model 2 off (research mode) versus full pipeline, without changing persisted production grading.
- Design a feature-flagged experimental detection/tracker schedule using motion propagation on skipped inference frames, if possible. Explicitly label those positions as predicted/not re-detected and avoid counting from untrusted stale positions.
- Use the same camera/tracker state owner; add regression videos with fast movement, occlusion, overlapping fish, entrance/exit, and fish crossing the counting line during skipped frames.
- Track false counts, missed counts, ID switches, duplicate events, association ambiguity and ROI crop errors. Any reduction in reliability must be reported.
- Default the feature OFF unless an independently evaluated result demonstrates an acceptable speed/accuracy balance.

## Acceptance
A before/after performance and counting table, a feature-flagged implementation only if supported, and a zero-risk rollback to per-frame Model 1 prediction.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
