# PROMPT 16 - Final Regression QA, Documentation and Release Checklist

After the relevant Tamban implementation prompts are completed, run a **fresh code audit** of the actual repository state; do not reuse prior pass/fail claims. The project has Model 1 fish counting, Model 2 part-based confidence predictions, weighted grading, diagnostic image features, and possibly experimental belly-defect evidence/fusion.

## Tasks

1. Inspect every modified runtime path, config, tests, exports, and frontend copy for consistency with the active feature flags and versioned grading policy.
2. Re-run model-free unit/integration suites; isolate checkpoint-backed/GPU tests as opt-in and record absent model assets clearly. Where real checkpoints are locally available, document and run scoped end-to-end smoke tests; do not treat skipped model tests as passing.
3. Check key regressions: temporal evidence counting; recovery after ambiguity; multi-fish overlap ownership; body-only vs Body+(Head OR Tail); physically missing vs undetected Head/Tail; stable original 50/30/20 scoring; diagnostic features not changing grades by default; and safe disabled fusion.
4. Check feature provenance, mask vs ROI sources, fish IDs, configuration/checkpoint hashes, rejected/ungraded reason codes, model switching during active inspection, and private video access if the evidence library was added.
5. Update README, research method notes, architecture diagram in Markdown, API examples, model/feature status inventory, independent-validation status, and user-facing grading explanations. Correct stale `crop`/`full_frame` defaults if present.
6. Produce `docs/release_readiness.md` with PASS/FAIL/BLOCKED, changed-file summary, commands/tests/results, outstanding expert-signoff decisions, and exact next steps. Do not label the release fully validated if expert fish-level testing is incomplete.

## Acceptance criteria

- All documented runtime behavior is verified against code and tests.
- No feature is described as active or accurate without evidence.
- Final report explicitly identifies anything still blocked by expert labels, consent, or model checkpoints.

## Report back

Give a short release verdict, verifiable test results, links to generated documentation, and the remaining TODOs prioritized for thesis defense.
