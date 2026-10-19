# Continuation dependency review — 2026-10-18

The current instruction `continuee.md` directs a review of prompt 11 and complete, ordered reading of prompts 12–21. Both reviews were performed. Prompt 11 remains **BLOCKED — EMPIRICAL VALIDATION**: the target-camera baseline and independently labeled fish clips needed for the required paired latency, count, ownership and grade comparison are unavailable. No configuration, model or grading policy was changed.

Prompt 11's model-free checks were rerun: `python -B -m pytest -q -p no:cacheprovider tests/test_model2_schedule_benchmark.py tests/test_runtime_diagnostics.py tests/test_multi_model_selection.py tests/test_tail_optional_policy.py --tb=short` — **56 passed, 48 subtests** (`11_continuation_review.log`). These checks establish software behavior, not real FPS, grade accuracy or optimization benefit. The latest complete checkpoint-free run remains 579 passed, 6 skipped and 92 subtests (`regression_through_11.log`).

## Sequence constraint

The user-invoked `Documentation/QA.md` instructs: “Complete each phase, validate the implementation, and update `TAMBAN_FINAL_POLISH_QA_PROGRESS.md` before moving to the next.” It also requires numbered prompts in strict order until a genuine blocker prevents further progress. `continuee.md` says: “If the repository's strict QA policy prohibits continuation, do not silently override it. Document that constraint and seek the necessary authorization before proceeding.” Therefore simply reading prompts 12–21 does not authorize executing them while 11 remains empirically blocked. The constraint comes from the user-invoked QA workflow, not an independently discovered `AGENTS.md` policy. Permission to continue software-only work with phase 11 still blocked would explicitly resolve the sequencing conflict; no incomplete empirical phase would be relabeled as passed.

The user subsequently said “yes skip it for now,” authorizing continuation past the empirical blocker while retaining phase 11 as BLOCKED.

## Actual dependencies

| Prompt | Technical dependency on a validated prompt 11 | Independently possible work and remaining acceptance limits |
|---|---|---|
| 12 — preview | No hard dependency for inspecting the existing queue or testing a separately flagged path. Avoid claiming a speedup or carrying stale overlays forward. | Software investigation and synthetic multi-client tests are possible; real display FPS, latency and camera behavior remain hardware-dependent. |
| 13 — navigation | No | Frontend review and browser interaction tests can run independently; visual coverage remains scoped to tested devices. |
| 14 — live interactions | No for state/UI simulation | UI and mocked backend states can be checked; live-camera, multiple-fish and long-running cases require hardware. |
| 15 — history/settings/exports | No | Existing APIs, history/export and browser workflows can be tested with temporary data; no production data migration is implied. |
| 16 — responsive/accessibility | No | Static and headless browser checks can run; manual assistive-technology and real device coverage must be reported separately. |
| 17 — maintenance/soak | No for code review and synthetic checks | A real 30–60 minute operational soak and device resources require an available test setup; do not claim it from short tests. |
| 18 — comprehensive QA matrix | No for a provisional matrix | It must record prompt 11 and all unrun hardware/scientific checks as blocked; it cannot turn those results into passes. |
| 19 — independent science and demo | Empirical acceptance depends on the missing study data and defense hardware, not on a particular optimization being adopted. | Claims audit, protocols and demo preparation can be drafted; independent accuracy and actual rehearsal remain blocked. |
| 20 — final release review | Full readiness depends on the evidence from prior phases, including 10/11 and 19. | A clearly provisional review can record blockers; READY cannot be claimed without required evidence. |
| 21 — optional expert library | No | Existing scaffold can be reviewed; real media, access and presentation require appropriate consent and authorization. The prompt is optional and says to implement only if requested by the research team. |

`src/api/camera.py` already uses `LatestFrameQueue` and a separate capture thread; `src/api/app.py` serves MJPEG, and `frontend/app.js` provides current navigation, history and exports. These observations are a dependency assessment, not completion or validation of prompts 12–21. Continue those phases in order only after authorization to proceed past the blocked empirical acceptance, preserving all hardware and science restrictions above.
