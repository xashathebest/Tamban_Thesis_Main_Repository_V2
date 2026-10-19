# Prompt 03 - Isolate Upload Model Choice From Live Model

**Priority/status:** P0 / VERIFIED

**Goal:** Prevent uploaded-image analysis from mutating the active camera model.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/app.py` `/api/analyze-image` (around 1233-1277) and `src/api/image_analysis.py`. Currently an `x-model-id` override calls shared `quality_model.switch_model` BEFORE the uploaded image is decoded, and without an inspection lock; even invalid bytes can trigger the switch. Reproduce with an invalid-image request and a stub. Make uploaded-image analysis side-effect free with respect to the live camera: use the already active model, or use an isolated short-lived / explicitly cached adapter only if resource budgets allow; alternatively reject different-model overrides during active inspection (409). Validate request and filename prior to any optional switch. Ensure no change to shared session/model selection on a failed upload. Cover concurrent upload + live processing, unsupported model IDs, failure paths, and cleanup. Clearly document your chosen policy.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Invalid uploads cannot change model or session; upload operations cannot silently perturb the running fish-grading process.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
