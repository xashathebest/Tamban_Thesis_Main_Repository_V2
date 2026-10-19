# Prompt 22 - Repair Independent Test Readiness Gates

**Priority/status:** P2 / RESEARCH BLOCKER

**Goal:** Make model performance claims depend on clean fish-level validation.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect dataset manifests, labels/split metadata, `src/evaluation/`, and `results/stabilization/validation_readiness.json`. The saved readiness report marks independent validation/test as blocked despite strong software coverage. Audit duplicate imagery, original fish identity, repeated specimen leakage, annotations across A/B/C/Rejected, and over/underrepresentation. Do not evaluate Class A test performance using a split without Class A examples. Design specimen-disjoint validation/test manifests, annotation agreement checks, and report per-class fish-level precision/recall/F1, confusion matrix, Ungraded coverage, reject errors and counting/association errors. Preserve a locked untouched test split; do not invent missing labels or manufacture improved accuracy.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Reproducible scientific validation plan and traceable blockers; no unsupported overall-accuracy claims.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
