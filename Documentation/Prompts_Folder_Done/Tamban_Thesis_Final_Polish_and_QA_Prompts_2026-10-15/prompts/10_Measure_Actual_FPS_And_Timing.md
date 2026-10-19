# Prompt 10: Establish reproducible performance baseline

**Priority / phase:** P1 - measure before optimizing

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Establish reproducible performance baseline.

### Inspection and implementation tasks

Inspect existing `src/api/runtime_diagnostics.py`, camera timing, preview stream and frontend telemetry BEFORE adding duplicate instrumentation. Instrument or expose camera capture FPS, processed inference FPS, displayed preview FPS, capture-to-display age, dropped frames, Model 1/Model 2 latency p50/p95, tracker, association, feature calculation, overlays, JPEG and DB/API cost.
On real hardware, record OS, CPU, GPU, torch CUDA availability, actual device per model, camera resolution, YOLO checkpoint IDs, Model 2 input (known configuration previously used 768), mode, grading interval, number of fish and warmup. Turn OFF debug capture for baseline.
Benchmark representative single and crowded scenes under the same conditions for 60-120 seconds. Do not equate smooth frontend preview with faster AI inference or invent results if hardware/weights unavailable.

### Required verification

Validate stage durations sum reasonably to total, metrics are labeled correctly, no instrumentation-induced major slowdown; compare empty scene vs several fish. Where no camera is available, mark measurement BLOCKED and provide exact command/steps for Windows host.

### Deliverables for this step

`qa/final/performance_baseline.md` with raw numbers or BLOCKED, reproduction commands and ranked measured bottlenecks.

## Execution rules (apply to this prompt)

- Operate on the **latest repository state**; earlier audit findings are leads to verify, not proof that a bug is still present. If already fixed, document evidence and make no unnecessary changes.
- Inspect relevant code and reproduce the issue **before** editing. Make incremental, reviewable changes; preserve working features and the two-model architecture.
- Missing large YOLO checkpoints in a shared ZIP are expected. Clearly distinguish simulated/model-free tests from actual model inference; label unavailable evaluations **BLOCKED**.
- Do not change scientific grade weights, required parts, rejection criteria, confidence interpretation, or feature-to-grade rules without explicit research approval and validation. No detected head is NOT proof the fish physically lacks a head; **Ungraded** is not **Rejected**.
- Include regression tests, full test commands/results, files changed, any API/config behavior change, and a rollback or feature flag when the behavior is significant. No fabricated measurements or claims of 100% accuracy.
- Stop and request approval before destructive dataset migrations, incompatible database/schema changes, irreversible historical result changes, or scientifically material policy decisions.

### Completion response format

1. **Finding/status:** confirmed bug, already fixed, improvement, or blocked, with source paths and short evidence.
2. **Changes made:** precise files/functions, concise before vs after.
3. **Tests:** commands, pass/fail/skip/blocked counts and relevant output.
4. **Risks and open questions:** anything requiring expert approval, camera, GPU or checkpoint.
5. **Next action:** handoff to the next numbered prompt without starting it.
