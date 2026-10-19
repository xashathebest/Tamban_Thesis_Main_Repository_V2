# Prompt 23 - Final End To End Regression And Release

**Priority/status:** P1 / FINISHING GATE

**Goal:** Verify all applied fixes together without breaking counting or grades.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

After implementing approved prompts, run model-free CI, static checks, API regression, concurrency tests, database migration/backward-compatibility tests, and deterministic simulated multi-fish overlapping-video tests. On user's hardware with real checkpoints (if available), measure Model 1/2 device, inference time, actual processed FPS vs preview FPS, counting agreement, grade confusion and abstention rate; do not mistake preview smoothing for faster inference. Verify Stop/Start, model changes, uploads, manual review, CSV/XLSX, active and historic sessions, and registry provenance. Archive baseline versus final results, release notes, config hashes and known limitations. Do not mark the project ready if independent expert and specimen-level testing remains blocked.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Final regression report with pass/fail evidence, versioned changelog, unfinished actions and validated capabilities.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
