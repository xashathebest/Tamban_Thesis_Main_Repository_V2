# Prompt 14 - Check Model Checksum And Registry Identity

**Priority/status:** P1 / REPRODUCED RISK

**Goal:** Make the selected checkpoint match the model ID and recorded SHA-256.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/inference/model_registry.py` `resolve_checkpoint_path`, `src/inference/model_traceability.py`, `src/inference/yolo_quality_model.py` loading/switching, and `models/MODEL_REGISTRY.json`. Registry resolution verifies path containment/existence, but NOT the expected SHA-256: a deliberately mismatched dummy file was accepted by resolution, while the existing hash assertion rejected it. Validate integrity once per checkpoint load/selection in strict research mode, NOT per frame. Detect configured model ID/path mismatch (including explicit `FISH_QUALITY_MODEL_PATH` overrides) and prevent using the wrong class labels/adapter metadata. Decide policy for custom models with unknown hashes, warn or reject as appropriate. Snapshot actual checkpoint path + SHA in each session, with mismatch tests using tiny temporary fake files.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Locked model identity is checked once; mismatches stop scientific runs or are reported without silently mislabeling model provenance.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
