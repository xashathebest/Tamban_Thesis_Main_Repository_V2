# Prompt 06: Make evidence aggregation robust but scientifically honest

**Priority / phase:** P0 - grading validity

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make evidence aggregation robust but scientifically honest.

### Inspection and implementation tasks

Inspect `src/inference/grading_engine.py`, relevant grading policy, `src/api/camera.py` track pruning and temporal evidence buffers. Verify that `minimum_usable_frames` counts FRAMES WITH USABLE BODY-PART EVIDENCE, not frames with empty predictions. Avoid sticky uncertainty flags persisting forever after a later clean observation unless policy explicitly requires it.
Check whether short detection gaps clear useful evidence prematurely, and synchronize policy with tracker timeouts. Clearly distinguish TRACK LOST, UNGRADED, REJECTED and CLASS A/B/C. Preserve provenance for decisions and evidence windows.
Maintain current Body 50%, Head 30%, Tail 20% semantics until a scientifically approved policy change; missing-part weights currently contribute zero, not automatically renormalized. Handle absent, ambiguous, conflicting, and zero-confidence predictions safely.

### Required verification

Test body-only, body+head, body+tail, head+tail, all missing, tied scores, no part in second frame, ambiguous-then-clean, clean-then-ambiguous, short dropout and long timeout. Assert reasons and thresholds not just labels.

### Deliverables for this step

Regression table of synthetic cases, documented temporal policy, implementation and results.

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
