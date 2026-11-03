# End-to-end runtime measurements

This validation follows the `additional.md` implementation. It runs the actual unchanged Model 1 V2, Model 2 and MobileSAM on CPU, then replays their exact saved native outputs through the final software. It is an engineering validation and contains no independently reviewed fish-level grading accuracy estimate.

## Controlled inputs and baseline

`results/qa/runtime_e2e/baseline_source.zip` is an actual snapshot of the working source, frontend and configurations before this task's production edits. It includes the previous uncommitted `additional.md` fixes, not the older tracked HEAD. Its SHA256 is `934a1a4ad9e415e2157561aee0a9447eb936705bf6562412c2d780309ec0d1b5`; its manifest records 148 files. The before pass imports this frozen package. Model registry entries and checkpoint paths point to the original read-only model files.

Twenty-four actual detector/SAM passes were made: seven representative real-image cases plus all 17 original project test images. Every pass used one Model 1 adapter call, one Model 2 adapter call, one actual MobileSAM image-encoder pass, and zero GrabCut calls. The selected/raw part outputs, complete result, native source pixels, native binary candidate masks, prompt/frame identities, checkpoints and timings are frozen per scene.

The after pass reuses these exact neural outputs while rerunning current association, ownership validation, crop translation, geometry/color diagnostics, grading, serialization, annotation, and preview preparation. It strictly rejects changed source pixels, parent prompts, or frame identity. It performs zero new neural inference. This is a controlled before/after software comparison; its shorter replay time is **not** a measured end-to-end speed improvement.

The representative inputs comprise the exact historical CSV photo at its original 3840 by 2160 resolution, a naturally crowded original test photo, recorded crops of touching fish and clipped fish, a naturally damaged-fish photo, a source-bound isolated real-fish crop, and an additional 25-degree rotation of that isolated crop on an enclosing canvas. The derived pixels and operations are explicitly recorded in `scenes.json`. Scene tags are engineering descriptions, not anatomical or grading ground truth. The 17-image cohort overlaps the representative sources and has known historical training exposure; the cohorts cannot be combined into an independent accuracy score.

## Before and after

All 24 scenes preserve exactly the same accepted native parts, parent boxes, weighted scores, effective weights, final grades and supports after the new safety/diagnostic repairs. There are zero runtime invariant violations before or after. The new required-pair safeguard has synthetic regressions; it does not change the actual accepted part pairs in these scenes. Eight mask reports gain clearer unvalidated-status explanations; mask ownership approval and grading remain unchanged.

| Representative scene | Parents | Raw H/B/T | Accepted H/B/T before and after | Ungraded before and after |
|---|---:|---|---|---:|
| Historical CSV original photo with current Model 1 V2 | 10 | 7/9/6 | 1/5/1 | 9 |
| Naturally severe overlap | 6 | 5/6/6 | 2/3/2 | 5 |
| Touching-fish crop | 3 | 2/6/1 | 0/3/0 | 3 |
| Naturally damaged-fish photo | 4 | 6/5/1 | 2/3/0 | 3 |
| Clipped-fish crop | 4 | 5/9/0 | 1/3/0 | 3 |
| Isolated real-fish crop | 1 | 1/0/1 | 0/0/0 | 1 |
| Same isolated crop rotated 25 degrees | 1 | 1/2/1 | 0/1/0 | 1 |

| Separate cohort | Parents | Raw H/B/T | Accepted H/B/T before and after | Ungraded before and after | Graded coverage |
|---|---:|---|---|---:|---:|
| Seven representative scenes | 29 | 27/37/16 | 6/18/3 | 25 | 4/29 (13.8%) |
| All 17 project test photos | 117 | 90/107/46 | 24/71/10 | 105 | 12/117 (10.3%) |
| Exact historical CSV replay, original recorded parents | 7 | 7/9/6 | 2/4/0 | 5 | 2/7 (28.6%) |

The historical seven-parent replay must stay separate from the current Model 1 V2 run on its photograph. Current Model 1 detects ten parents on that photo, whereas the CSV records seven older parent boxes. Substituting those generations would invalidate the reproduction. `legacy_csv_comparison.json` retains the exact original seven parents, all 22 native candidates, original export grades and identical policy replays on both sides.

The 16 graded verdicts across the two actual-image cohorts were independently recomputed from their own accepted raw part confidences. All preserve 50/30/20 with Tail or 62.5/37.5 Body/Head without Tail, and every final support equals its weighted support. There are zero arithmetic violations. This establishes **policy compliance**, not correctness against expert fish grades. Width and structural contributions remain inactive; no automatically generated mask becomes independently validated.

## Why Ungraded remains

For the 17-image cohort, 86 of 105 Ungraded records have missing-required-evidence as their primary reason and 19 have required ownership ambiguity. Among Ungraded fish, 93 lack an accepted Head and 46 lack an accepted Body; these counts overlap. Three have accepted Head and Body but additional ambiguous required-region candidates still require abstention. None was forced into a grade.

The best recorded candidate for each missing Head fails as follows: 45 fail only the unchanged ownership score, 19 do not intersect that parent, 10 remain competing-parent ambiguous, 12 fail score/center/containment, and seven fail score/containment. Missing Body candidates comprise 12 score-only failures, 13 without intersection, eight competing-parent ambiguities, ten score/center/containment failures, and three score/containment failures. These categories describe recorded software gates, not expert conclusions about which fish actually owns a candidate.

For the representative cohort, primary reasons are missing required evidence for 19 fish and required ownership ambiguity for six. Twenty-three lack an accepted Head and 11 lack an accepted Body. The isolated crop has no Body candidate at the unchanged production output threshold/NMS; its Head ownership score is 0.643479 versus 0.70 despite 0.859731 containment. Rotation produces Body candidates, but the Head still scores 0.649375 with 0.835574 containment and is withheld. Expanding the grading crop would not resolve this decision: Model 2 and association already inspect full native image coordinates before cropping.

The score formula reserves support for reliable mask geometry. An unvalidated generated mask cannot silently supply that evidence. Most remaining Ungraded cases therefore involve ownership policy gates, uncertain parent extent, unavailable independent mask support, competing fish, or absent detector candidates. They are not all attributable solely to Model 2. No threshold was lowered and no neighboring part was borrowed to improve coverage.

## Mask ownership and latency bottlenecks

In the 17-image cohort, 78 of 117 candidate masks pass native geometry checks, but only seven pass all engineering ownership/required-evidence checks; all remain independently unvalidated. Reasons include missing accepted Head support (93), missing accepted Body support (46), required ownership ambiguity (19), actual foreground contact with the native image boundary (15), mask-overlap conflict (12), uncertain/implausible silhouette orientation (nine), omission of an accepted Head region (four), and neighbor anatomical evidence contamination (four). Reasons overlap and are not a partition. The representative cohort has 11 geometry passes and one complete engineering pass among 29 masks. A plausible shape alone is insufficient to settle parent ownership.

The fresh CPU pipeline median is 1,755.6 ms across the 17 original 640 by 640 test images, with p95 1,978.4 ms. These are single passes per input, not a repeated deployment performance study. The native historical photo takes 11,263.0 ms; the first SAM load, native mask handling, and larger color/diagnostic arrays contribute. Its reported shared segmentation is 1,833.3 ms, Model 2 is 374.6 ms, and color processing is 3,586.3 ms. Stage scopes overlap and must not be summed into a claimed total. The actual interval excludes file decode/network and initial Model 1/2 loading; it includes first-use MobileSAM loading and annotation/preview encoding.

Paired after timings (about 228.9 ms median for the 17-image software replay) exclude all neural inference and are retained with an explicit separate scope. The actual current-source HTTP/browser run by the parallel API validation records a fresh full pass separately in `results/qa/runtime_e2e/ui/actual_e2e.json`; it is not conflated with cached replay latency. No CUDA initialization, live-server restart, or training interaction was performed by this harness.

## Artifacts and reproducibility

- `before.json`, `after.json`, `comparison.json`: exact scene-level provenance, call counts, invariant checks, protected predictor AST comparisons, unchanged full checkpoint hashes, and CPU/CUDA status.
- `before.summary.json`, `after.summary.json`: cohort counts, every missing-required-part best candidate and failed gate, mask reasons, and scoped timings.
- `before/<scene>/frozen.json`, `masks.npz`, and both phases' `payload.json`: full native detections, candidate masks and structured pipeline results.
- `sources/` and `visuals/`: exact frozen input pixels and the pipeline's own before/after annotated JPEGs, without fabricated labels.
- `legacy_csv_comparison.json`: historical seven-record reproduction kept separate from current detector generation.

The new orchestrator is `src/evaluation/validate_runtime_e2e.py`. `--snapshot-only` refuses to overwrite a baseline. `--phase before --all-test-images` performs the actual CPU inference; `--phase after` reuses those frozen outputs; `--summarize before`, `--summarize after`, `--compare`, and `--legacy-csv` require no new neural inference. Ordinary regression is `python -B -m pytest -q -p no:cacheprovider tests/test_runtime_e2e_validation.py`: **nine tests passed**. The harness tests native coordinate loss, trace completeness, false mask/calibration approval, exact replay source/frame/parent binding, nonmerged raw identities and grading arithmetic without claiming expert accuracy.

Independent expert parent-to-part ownership and whole-fish grade labels, deployment-camera holdout data, calibrated physical measurement references, and real GPU/end-to-end latency studies remain necessary before claiming anatomical correctness or grading accuracy. Existing COCO part labels can measure part detection compatibility, but they do not identify a parent fish or supply its adjudicated final grade.
