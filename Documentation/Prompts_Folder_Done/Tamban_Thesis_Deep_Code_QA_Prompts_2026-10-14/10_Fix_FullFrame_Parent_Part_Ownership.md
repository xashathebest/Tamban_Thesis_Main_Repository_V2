# Prompt 10 - Fix FullFrame Parent Part Ownership

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Protect body-part ownership when fish overlap.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/camera.py` `_process_frame` around 1010-1060, `src/inference/association.py`, and `YoloQualityModel.predict_full_frame`. Existing full-frame association only receives `eligible` parents, excluding fish not due for grading/already counted. Verify whether their parts can wrongly attach to eligible neighboring fish. Perform global parent-part association against ALL currently visible, credible fish; then keep only quality results due for grading. Preserve ambiguous/unassigned handling rather than forcing nearest-match. Write adversarial synthetic tests with 2 overlapping fish, one eligible and one ineligible, near-equal candidates, counted fish, and no valid parent. Compare outputs to baseline on fixed samples where available.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
A part owned by an ineligible fish never becomes evidence for the eligible fish, with no duplicate counting.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
