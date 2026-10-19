# Prompt 01 - Baseline Reproducible Test Audit

**Priority/status:** P0 / START HERE

**Goal:** Lock down a truthful, reproducible starting point before any fixes.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Review `tests/`, `tests/README.md`, `.github/workflows/model-free-tests.yml`, `requirements.txt`, and the active API/inference files. Run `python -m unittest discover -s tests -v`, Python compilation, and JavaScript syntax checks. Group failures into (a) genuine logic regressions, (b) absent local checkpoints/hardware, (c) dependency/configuration failures. In the reviewed ZIP, there were 341 tests: 330 passed, 6 failed in `test_multi_model_selection.py`, and 5 skipped; verify this independently on the current checkout. Never fabricate model weights or mark checkpoint-dependent tests as software bugs. Create a short baseline report with environment details, reproducible commands, current grading-policy summary, and a risk register. Preserve existing files.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
A clean test-results inventory, an issue/priority table with source line evidence, and a known-good command to run after each future change. Do not alter runtime behavior yet.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
