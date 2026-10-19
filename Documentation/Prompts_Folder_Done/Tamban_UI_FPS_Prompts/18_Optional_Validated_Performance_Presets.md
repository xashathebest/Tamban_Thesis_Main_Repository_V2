# 18 - Optional Presets Only After Benchmarks

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
If and only if Prompts 05-08 and 16 demonstrate meaningful and scientifically acceptable trade-offs, offer beginner-friendly runtime profiles. Do not create inaccurate 'fast means equally accurate' marketing labels.

## Implementation
- Design two or three **validated** named profiles, e.g. `Standard/Validated`, `Faster preview` (if raw preview is available), `Research benchmark`, each with explicit settings and observed trade-offs.
- Keep final grading policy and checkpoint hashes separate from user display preferences. Never silently lower confidence thresholds or disable evidence/Reject gates for speed.
- Restrict any model-size/mode/inference scheduling changes to stopped sessions or explicit authorized changes; record exact settings and hashes in durable session metadata.
- UI should show what each profile actually changes and distinguish smoother camera rendering from AI processing FPS. Include an easy Restore Validated Settings action.
- Require automated tests for session locking, provenance, selection persistence, missing CUDA, absent checkpoints and safe fallback.
- If experiments are inconclusive or accuracy degrades, do NOT implement performance presets. Report why instead.

## Acceptance
An operator can choose a **verified** setting without accidentally corrupting research comparability, and each recorded inspection can be traced to its exact configuration.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
