# Prompt 12 - Fix Temporal Evidence Counting And Recovery

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Require genuinely informative temporal observations and permit evidence recovery.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/inference/grading_engine.py` near 993-1019 and `src/inference/grading_policy.py`. `len(track.usable_frames)` may increase for accepted frames with zero detected parts, letting a grade clear a multi-frame requirement without two part-evidence frames. `parent_uncertain`, `association_ambiguous`, and `out_of_frame` are sticky OR flags that can block grading after valid later evidence. Separate 'frame processed', 'usable image', and 'frame with sufficient body-part evidence'; require the correct evidence quantity for temporal gating. Define a conservative recent-window recovery rule for transient ambiguity while preserving review flags for unresolved conflicts. Regression-test good+empty, ambiguous+good, out-of-frame+recovery, contradictory part grades, and absence of Model 2. Do not simply lower confidence thresholds to boost grade coverage.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Temporal-ready means the required count of evidence-bearing observations; transient poor frames do not automatically poison a whole track forever.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
