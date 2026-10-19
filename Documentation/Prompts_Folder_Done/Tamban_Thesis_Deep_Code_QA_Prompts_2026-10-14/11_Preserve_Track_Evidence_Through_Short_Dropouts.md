# Prompt 11 - Preserve Track Evidence Through Short Dropouts

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Stop one missed detector frame from erasing valid Model 2 evidence.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/camera.py` around 1094-1099, `src/api/domain.py` TrackingManager timeout behavior, and `YoloQualityModel.prune_tracks`. The camera prunes grade caches based only on detections in the current processed frame; this can erase evidence while the tracker still considers a fish alive. Retain track evidence until its lifecycle is truly expired or finalized. Use bounded TTL/grace rules and monotonic timestamps, and guard against reusing track IDs after reset or camera restart. Test one-frame dropout, multiple dropouts under/over threshold, overlap, detection reappearance, and stale-ID contamination. Do not smooth over genuinely lost tracks or retroactively invent evidence.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Brief gaps no longer reset a valid track; genuinely expired fish are cleaned up within bounded memory.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
