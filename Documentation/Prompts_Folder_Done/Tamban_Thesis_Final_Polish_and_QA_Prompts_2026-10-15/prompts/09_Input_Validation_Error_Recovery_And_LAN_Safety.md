# Prompt 09: Harden external operations without overengineering

**Priority / phase:** P1 - stability

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Harden external operations without overengineering.

### Inspection and implementation tasks

Review image upload validation and memory use in `src/api/app.py`, `src/api/image_analysis.py`, error handling in camera/inference, and host binding in `src/api/__main__.py`. Enforce sensible upload caps before decoding, pixel limits, types and safe responses for corrupted/unreadable inputs; avoid unbounded `await request.body()` on untrusted traffic.
Check handling of missing/invalid camera IDs, model checkpoints, unavailable GPU, empty predictions, inference exceptions and status failures. Errors must leave app and session coherent and allow retry. If bound beyond loopback, review authorization, CORS, debug routes, data exports and mutating operations. Do not promise network security without testing.

### Required verification

Test truncated JPEG, invalid magic bytes, huge declared/undeclared body, decompression-bomb dimensions, no camera, missing model, failed DB write, concurrent API call and LAN-exposed mutation risks. Measure recovery not just status code.

### Deliverables for this step

Safety fixes, practical local-vs-LAN deployment recommendations, error-handling tests.

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
