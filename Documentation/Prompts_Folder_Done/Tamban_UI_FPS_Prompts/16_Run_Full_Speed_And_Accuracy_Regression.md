# 16 - Prove Performance Improvement Without Sacrificing Grading

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
After earlier changes, perform an apples-to-apples comparison on the **same real camera machine**. This is a validation task, not a claim that any FPS target is guaranteed.

## Protocol
- Record baseline and optimized runs with same hardware, checkpoint hashes, camera settings, environmental lighting, fish-count scenarios, resolution, warm-up period and session duration.
- Show capture FPS, preview FPS, processed AI FPS, per-stage p50/p95, frame age, one-slot queue replacements, server/status p95, browser render p95, number of Model 2 passes and throughput fish/minute.
- Measure fish detection recall, counting accuracy/duplicates, ID switches, parent-part ownership, temporal evidence, A/B/C/Rejected accuracy and macro F1, B/C confusion and Ungraded rate on labelled test video/images.
- Note any changes in real classification accuracy or annotation visibility caused by reduced image sizes, frame scheduling, crop/full-frame choices or new camera settings.
- Publish `results/performance/comparison.csv`, `performance_report.md`, reproducibility configs and a plain summary. Mark any unknowns explicitly.
- Choose optimizations only if they meaningfully improve speed without unacceptable accuracy/traceability regression. Retain easy rollback flags for risky changes.

## Acceptance
One defensible final table: baseline ~5 FPS (if reproduced) -> measured optimized FPS on same equipment, together with quality/counting results and limitations. No fake metrics or benchmarks from other hardware.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
