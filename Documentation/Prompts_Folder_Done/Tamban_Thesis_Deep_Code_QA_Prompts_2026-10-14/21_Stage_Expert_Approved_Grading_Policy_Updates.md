# Prompt 21 - Stage Expert Approved Grading Policy Updates

**Priority/status:** P2 / REQUIRES EXPERT SIGNOFF

**Goal:** Implement proposed body+secondary-part eligibility only after expert review.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `configs/grading_engine.yaml` (`minimum_regions_observed: 1`) and `src/inference/grading_policy.py`. Current standard rules can grade with body only; the adviser proposed allowing Body+Head OR Body+Tail to reduce Ungraded counts. The annotator provisionally said a physically absent head should be Rejected but a physically absent tail may still be eligible. FIRST document and obtain annotator confirmation; do not infer physical absence from missing detections. Add an opt-in versioned configuration for minimum two observed parts and a separate structural-integrity evidence gate that can only reject on affirmative confirmed defect evidence. Compare old/new policies on held-out labeled samples including overlapping/occluded fish. Preserve original 50/30/20 weights unless changed with validation; do not silently renormalize missing parts.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Clear before/after policy versions, expert signoff, correct separation of 'Ungraded' (insufficient evidence) from 'Rejected' (confirmed defect).

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
