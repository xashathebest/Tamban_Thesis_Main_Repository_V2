# Prompt 11: Reduce measured latency without damaging grading

**Priority / phase:** P1 - performance

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Reduce measured latency without damaging grading.

### Inspection and implementation tasks

Using output from prompt 10, optimize only demonstrated bottlenecks in Model 1, Model 2, preprocessing or scheduling. Check CPU/GPU device selection, precision (FP16 only if supported/tested), warmup, avoid repeated model loading, full-frame vs per-fish crop, input size (e.g. 768/640 if compatible), batching when sensible, reuse buffers and duplicate conversions.
Treat current Model 2 cadence (previously 3 eligible frames) as an intentional sampling policy, not a guarantee of no accuracy effect. Never silently disable Model 2, discard small fish, or reduce grading evidence to inflate speed. Preserve per-fish associations and count invariants.
Make optimizations optional/configurable and add a rollback. Report hardware constraints; if CPU only, state realistic limits.

### Required verification

A/B benchmark unchanged fish clips with baseline vs optimized settings: FPS and p50/p95, count errors, assignment errors, proportion Ungraded, grade disagreement by class. Revert variants that cause unacceptable scientific regression.

### Deliverables for this step

`qa/final/performance_changes.md`, concrete measured gains and tradeoff table, tests and rollback instructions.

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
