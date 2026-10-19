# 07 - Image-Size Sweep With Accuracy Safeguards

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Determine whether input resolution is consuming avoidable time without making small heads/tails or B-versus-C quality grading worse.

## Evidence
`src/api/app.py`: Model 1 default input size 640; chosen persisted YOLO26m Model 2 registry input size 768. `FISH_QUALITY_IMAGE_SIZE` supports explicit overrides. Actual Model 2 adapter may adopt model-specific registry sizing after a switch.

## Implementation
1. Audit where effective image size comes from, including `model_registry` switching and command-line/environment overrides. The runtime UI must show **effective**, not requested, sizes.
2. Benchmark proposed sizes (e.g. 512/640/768) for Model 1 and Model 2 **separately** on the same test set and target machine. Keep original source images, cropping/letterbox and calibration documented.
3. Report warm inference p50/p95, FPS, fish recall, counting mistakes, part recall, A/B/C/Rejected F1, B/C confusion, score shifts, and Ungraded rate. Include small/overlapping fish.
4. If a smaller size is demonstrably acceptable, introduce a clearly documented feature flag/config with safe defaults and provenance captured in sessions.
5. Do not blindly replace 768 with 320/416 or resize only preview and pretend the model saw full resolution.

## Acceptance
Publish a transparent speed/accuracy trade-off table and keep quality-safe default based on validation, not FPS alone.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
