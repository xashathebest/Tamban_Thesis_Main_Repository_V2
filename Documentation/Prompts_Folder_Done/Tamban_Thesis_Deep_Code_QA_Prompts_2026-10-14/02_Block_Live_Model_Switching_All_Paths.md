# Prompt 02 - Block Live Model Switching All Paths

**Priority/status:** P0 / VERIFIED

**Goal:** Prevent mixing Model 2 predictions inside an ongoing inspection.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `/api/models/select` in `src/api/app.py` (around 609-662), the model-selection branch of `/api/settings`, and `YoloQualityModel.switch_model` in `src/inference/yolo_quality_model.py`. Reproduce that `/api/models/select` does not enforce the existing inspection-status lock, whereas `/api/settings` does. Enforce ONE server-side guard for all model-change entry points whenever inspection is starting/running/stopping. Return HTTP 409 without changing loaded weights, selected model ID, persisted JSON, temporal grading state, or session metadata. Serialize loading against inference to avoid concurrent state changes. When stopped, switch models atomically and reset or version temporal evidence. Test all entry paths, simultaneous requests, identical-model requests, failed loads, and rollback. Do not rely on the frontend disabling a button.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Live switching rejected with no state mutation; stopped switch succeeds with coherent model IDs/checkpoint metadata; reliable regression tests.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
