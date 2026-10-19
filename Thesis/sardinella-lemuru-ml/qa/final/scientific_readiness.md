# Phase 19 — scientific readiness

**BLOCKED — independent study and defense rehearsal have not been performed.** The user confirmed that independent videos and expert labels do not yet exist. `results/stabilization/validation_readiness.json` marks dataset independence FAIL and final certification BLOCKED. The 2026-09-22 historical dataset audit recorded 39 train/validation and 38 train/test lineage-overlap groups and an incomplete near-duplicate scan; it must be repeated on the actual study and training data. The existing preflight inspected 17 test images and no Class A part annotations. It cannot establish independent four-grade fish-level performance. `results/stabilization/model2_validation/val_metrics.json` contains historical development part-detection metrics, not an independent fish-level grade or expert-agreement study.

| Claim | Evidence and current status |
|---|---|
| Fish detection/counting | Software functions exist; real independent detection/counting accuracy and overlapping identity are NOT RUN. |
| Part detection | Historical development metrics exist for trained labels; independent four-grade fish-level validity is BLOCKED. |
| Fish-level grading | `tail_optional_v1` uses Body 0.50, Head 0.30, Tail 0.20 when available; an unavailable Tail redistributes to 0.625/0.375 and Body/Head are required. This is proposed logic, not expert-approved accuracy. |
| Human vs model | No independent expert labels or documented agreement; NOT RUN. |
| Belly defects | No independently validated belly-defect detector or structural override; BLOCKED. |
| Preview and AI FPS | Separate quantities; actual browser display FPS, end-to-end latency and representative AI processing rates have not been measured. |

Follow `docs/independent_validation_protocol.md` and `docs/adaptive_tail_policy.md`: obtain specimen/session-linked, blinded expert truth and permission; include A/B/C/Rejected, low-confidence B/C, zero/one/three/six-plus fish, overlaps, occlusion and relevant defect controls. Audit independence and lock checkpoints, settings and splits before final testing. Report detection, counting, part and fish grades separately, including abstention coverage, per-class denominators, uncertainty and expert disagreement. Do not tune on the final test set.
