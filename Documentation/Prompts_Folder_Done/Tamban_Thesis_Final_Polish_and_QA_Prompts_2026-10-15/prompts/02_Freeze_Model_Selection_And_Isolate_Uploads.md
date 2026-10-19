# Prompt 02: Prevent changes to model identity during active inspections

**Priority / phase:** P0 - data integrity

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Prevent changes to model identity during active inspections.

### Inspection and implementation tasks

Inspect `src/api/app.py` model selection (`/api/models/select`), settings model controls, and `/api/analyze-image`; inspect `src/inference/yolo_quality_model.py`, model registry and camera service.
Ensure all endpoints enforce one coherent policy: a running inspection must use an immutable selected checkpoint/configuration for its lifetime, or a documented explicitly safe transition. Analyze image uploads must not silently switch the live camera's shared Model 2. Validate inputs BEFORE touching shared model state.
Handle concurrent requests with an appropriate lock, per-request model isolation or safe serialization. Persist effective model ID/path hash to durable session/event metadata. Never infer a model ID merely from UI selection.
If existing implementation already handles these cases, prove it and avoid rewrite.

### Required verification

Test active inspection + model-change attempt through EVERY API path; invalid upload with a model parameter; simultaneous uploads and camera; normal idle switch; checkpoint unavailable; model ID in events matches model used. All tests must be deterministic without actual weights where possible.

### Deliverables for this step

Minimal fix with regression tests, before/after reproduction, and model-selection contract for API/frontend.

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
