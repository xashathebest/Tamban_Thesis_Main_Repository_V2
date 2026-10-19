# Prompt 04: Validate entire configuration and checkpoint identities safely

**Priority / phase:** P0 - prevent silent inconsistency

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Validate entire configuration and checkpoint identities safely.

### Inspection and implementation tasks

Inspect `src/api/app.py` `/api/settings`, config schemas and `src/inference/model_registry.py`, `src/inference/model_traceability.py`, `src/inference/yolo_quality_model.py`.
Validate the COMPLETE settings payload before committing any field. A malformed field must cause no partial mutations (for example detector threshold changes before an HTTP 422). Clearly define which settings are disallowed mid-session. Persist effective configuration version/snapshot.
Registry entries with SHA-256 must be checked against selected checkpoint bytes at LOAD/SELECTION time, not for every frame. Check explicit path overrides against registry metadata rather than falsely attributing identity. Do not block a local demo solely because large checkpoints were deliberately excluded from the shared ZIP; report UNAVAILABLE appropriately.

### Required verification

Test valid changes, partially invalid payload, concurrent settings requests, active-session locks, bad hash, explicit checkpoint override, restart persistence, and honest error messages.

### Deliverables for this step

Atomic settings tests, verified checkpoint selection audit, and concise configuration contract.

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
