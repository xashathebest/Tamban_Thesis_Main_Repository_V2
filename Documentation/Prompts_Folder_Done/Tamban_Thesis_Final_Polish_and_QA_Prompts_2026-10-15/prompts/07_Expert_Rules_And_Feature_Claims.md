# Prompt 07: Protect research methodology from unintended changes

**Priority / phase:** P1 - scientific clarity

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Protect research methodology from unintended changes.

### Inspection and implementation tasks

Inspect `configs/grading_engine.yaml`, `src/inference/grading_engine.py`, feature modules in `src/features/` and any UI descriptions of grade logic. Prepare a matrix for EACH measured feature: coded, executed in live camera, saved, displayed, influences final grade, validated by expert.
Explicitly note that color/HSV diagnostics and offline reflectance/texture are NOT validated quality-rule overrides unless code and evaluation prove otherwise. Belly holes are structural defects, not equivalent to general edge density; do not claim automatic belly-hole recognition without labels, a detector/rule and validation.
Stage (do not silently enable) professor's proposal: body plus at least head OR tail. Stage expert rule that a physically missing head may mean Rejected whereas tail absence may still allow grading, pending confirmation. NONDETECTION or occlusion is not physical absence. Recommend expert rubric, consented evidence references and approval gate before scientifically material code changes.

### Required verification

Add truth-in-labeling UI/docs assertions. Where a policy change is approved, add a separate versioned feature flag, tests against expert fish-level labels, and rollback. Otherwise deliver policy proposal only.

### Deliverables for this step

Feature truth table, proposed policy decisions needing approval, corrected wording, and tests of disclosures.

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
