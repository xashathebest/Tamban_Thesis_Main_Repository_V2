# 06 - Confirm CPU/GPU Runtime and Safe Precision

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Find whether the actual 5-FPS setup is using CPU when CUDA/GPU inference could be supported, and optimize compute safely if benchmarks justify it.

## Evidence
`YoloFishDetector._resolve_device` and `YoloQualityModel._resolve_device` select CUDA when PyTorch reports it, otherwise CPU. The saved `results/diagnostic/yolo26m_test/report.json` records one Model 2 CPU still-image inference of ~0.363 s. This does not prove the live machine runs on CPU.

## Implementation
- Add a concise startup diagnostics report for OS, CPU, GPU, CUDA-capable torch build, actual model device, backend, selected checkpoints and available VRAM if accessible. Never confuse an NVIDIA GPU's presence with CUDA support in the installed PyTorch wheel.
- Compare warm model predictions on CPU vs CUDA if available; avoid importing/loading model checkpoints more than necessary.
- Experiment behind explicit flags with FP16 only where GPU and framework support it. Validate class outputs, bounding boxes, and confidence tolerances against FP32. Do not set FP16 on CPU by default or claim GPU speedups without testing.
- Consider supported framework optimizations (warm-up, inference mode, fusion/export, appropriate CPU threading) only if compatible with chosen architecture, model weights and Windows hardware.
- Include fallback if GPU driver or device is unavailable, with a visible honest device status.

## Acceptance
Provide the measured performance matrix and recommendation; preserve baseline correctness and current model IDs/hashes in exported metadata.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
