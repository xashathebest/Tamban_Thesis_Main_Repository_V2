# Prompt 13 - Safe Model2 Error Handling And Abstention

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Prevent model crashes from leaving unexplained or stale fish grades.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/camera.py` broad exception handling near 1091-1093, `YoloQualityModel.unavailable_observation`, grading-policy reasons, and results persistence. Currently a Model 2 exception updates the global segmenter error but may not create per-fish unavailable observations for that cycle. Decide and implement explicit per-track failure semantics: counted fish still count; incomplete grading abstains with a documented reason; previously finalized grades remain immutable; no stale overlay is presented as fresh. Add bounded retry/backoff, error logging, and tests for inference failure, adapter failure, recovery, and partial batch failure. Never fabricate Class A/B/C from absent evidence.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Every affected fish has a traceable verdict/reason, and Model 2 failures do not crash Model 1 counting.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
