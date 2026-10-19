# 05 - Benchmark Model 2 Scheduling and Modes

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Find the fastest **correct** Model 2 evaluation strategy for one fish vs crowded overlapping fish. Do not assume crop or full-frame is always faster.

## Relevant code
`src/api/app.py` defaults to `FISH_QUALITY_INFERENCE_MODE=full_frame`, `FISH_QUALITY_INTERVAL=3`. `src/api/camera.py` `process_frame` calls `predict_full_frame` once for due tracks, otherwise loops crop per eligible fish. `src/inference/yolo_quality_model.py` `predict_full_frame` infers once then associates parts with parents.

## Implementation
1. Build a reproducible A/B test for 0, 1, 3, 6+ fish per frame with fixed camera resolution, same Model 1 and Model 2 checkpoint, and existing expert-labelled difficult overlap cases.
2. Compare `full_frame` vs `crop`, number of actual Model 2 invocations, total model time, association time, parent/part mismatch, ambiguous/unassigned parts, quality coverage and count accuracy.
3. Measure interval 1/2/3/4 or other justifiable values under equal image/video conditions. Ensure `minimum_valid_frames` and temporal aggregation are not accidentally weakened.
4. If adaptive per-track invocation is justified, propose and implement a feature-flagged scheduler with due-time/eligible-track bookkeeping and deterministic tests. Keep all fish needed for association in consideration even if only some need grading.
5. Never finalize early solely to gain FPS or invent a grade from undetected parts.

## Acceptance
A clearly supported recommendation with A/B output. Preserve fish-to-part ownership, per-fish histories, count-line finalization, rejection and Ungraded behavior. Include rollback to existing `full_frame` interval 3.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
