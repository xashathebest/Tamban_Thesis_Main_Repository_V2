# Prompt 18 - Make Model Free CI Truly Model Free

**Priority/status:** P1 / REPRODUCED

**Goal:** Remove false CI failures caused only by deliberately omitted heavy checkpoints.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `tests/test_multi_model_selection.py`, `tests/README.md`, `.github/workflows/model-free-tests.yml`, and `requirements.txt`. The documented 'model-free' command runs 341 tests in this ZIP, but 6 tests in `test_multi_model_selection.py` require nonexistent checkpoints or adapters, leading to 2 failures and 4 errors. Refactor those tests to use temporary fake checkpoint fixtures and mocked model factories, or mark REAL weight dependent integration tests opt-in and skip them with clear prerequisites. Preserve tests for path traversal, model switch identity, no per-frame reload, and session metadata; don't simply delete the failing assertions. Add a separate, explicitly invoked checkpoint smoke test. Verify clean checkout with no checkpoints gets all model-free tests green.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Default CI is portable and green without huge weights, while opt-in hardware tests remain meaningful and documented.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
