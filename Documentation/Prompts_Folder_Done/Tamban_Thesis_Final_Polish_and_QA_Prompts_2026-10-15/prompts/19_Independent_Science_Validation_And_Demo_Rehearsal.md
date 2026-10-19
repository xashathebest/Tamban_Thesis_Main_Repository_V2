# Prompt 19: Verify research claims and practice the real demonstration

**Priority / phase:** P0 - thesis gate

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Verify research claims and practice the real demonstration.

### Inspection and implementation tasks

Inspect training/validation/test manifests and `results/stabilization/validation_readiness.json`, current per-class metrics and expert-labeled image availability. Confirm whether specimen-level split independence is proven; do not claim full Class A validation if the test split contains no Class A annotations. Do not tune on the final test set.
Prepare comparisons for class A/B/C/Rejected, low-confidence, B-versus-C, overlap and belly-defect cases using independent labeled fish where available. Separate (a) fish detection/counting, (b) part detection, (c) fish-level grading, (d) human-vs-model agreement, (e) preview and AI FPS.
Create a pre-defense walkthrough: clean startup, connect camera, detect/count fish, explain weighted grade, review uncertain result, inspect history, export, demonstrate expert evidence only with appropriate consent. Prepare a fallback image demonstration if camera/hardware fails, clearly labeled as fallback.

### Required verification

Rehearse end-to-end on defense machine; record actual timing, accepted known limitations, panel Q&A and blocked experimental validation honestly. Do not claim expert approval of exact 50/30/20 values until documented.

### Deliverables for this step

`qa/final/scientific_readiness.md`, demo script, hardware checklist and explicitly scoped evidence claims.

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
