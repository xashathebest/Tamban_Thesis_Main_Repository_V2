# Model 2 false-positive investigation

The November 2, 2026 investigation found a concrete display problem: the normal
fish zoom viewer drew unassigned or ambiguous Model 2 diagnostic boxes inside
each overlapping fish crop. These boxes were not that fish's owned anatomical
evidence. The same physical candidate could therefore appear in several fish
viewers. The main uploaded-image annotation already drew only assigned parts.
Camera raw/rejected overlays were already behind explicit debug/display flags.

The frontend repair removes unowned diagnostic boxes from the ordinary fish
viewer. Raw predictions and association failures remain recorded for inspection.
This corrects misleading display; it does not assert that the trained detector
has no genuine false positives.

## Detector behavior and configuration

The running backend was queried read-only at `/api/status`. It reported the
expected `yolo26m_partdet` checkpoint, confidence 0.25, input size 768, full-frame
inference, FP32, and `debug_raw_output=false`. None of its raw/rejected overlay
switches was enabled. The checkpoint SHA-256 was
`f74cd336b6ba9274f3bbbad845f64d03d0d4cc78e79cf1c0392d0b07d1d53222`.
See [the captured settings](../results/qa/sam/model2_live_settings_readonly.json).
The detector investigation itself used read-only live settings and actual CPU
comparison inference with CUDA hidden. After implementation and regression
checks, the stopped dashboard was reloaded to expose the new preview API; see
[the dashboard verification](sam_preview.md#running-dashboard-verification).

Compared with the frozen pre-MobileSAM source snapshot, the `_infer_parts`
method has an identical Python syntax tree. The detector adapter, association
code, model registry code, and captured active-model configuration also retain
identical file hashes. No detector threshold, NMS setting, class mapping,
checkpoint, training data, or annotations were changed to hide predictions.

A real CPU test executed the old `_infer_parts` method extracted from the
snapshot and the current method against the same loaded checkpoint and original
reference-image pixels. Selected detections and raw output matched **exactly**,
including coordinates, classes, and confidence. This directly checks detector
output rather than relying only on unit-test doubles. The reference input and
its hash are recorded in [the audit JSON](../results/qa/sam/model2_falsepositive_audit.json).

## Existing unmatched detections reproduced

The unchanged production adapter was rerun on all 17 images and 225 part boxes
in the current COCO test export. The operating confidence remained 0.25. Ranked
AP used the existing evaluation floor of 0.001; that floor is evaluation-only
and did not change the application's confidence threshold.

Every metric and per-class matching-error count is **identical** to the saved
[October 30 compatibility report](../results/evaluation/active_model2_coco_part_compatibility.json),
which predates the MobileSAM integration.

| Test-export measure | Historical | Current |
| --- | ---: | ---: |
| Class-aware matched boxes at IoU 0.50 | 190 | 190 |
| Unmatched predictions at confidence 0.25 | 53 | 53 |
| Missed annotated boxes | 35 | 35 |
| Macro precision | 0.501555 | 0.501555 |
| Macro recall | 0.555360 | 0.555360 |
| mAP50 | 0.548903 | 0.548903 |
| mAP50–95 | 0.317795 | 0.317795 |

These are part-box **compatibility** results, not independent fish-level
accuracy. Historical training/export overlap is known. A class-aware unmatched
box can be a wrong grade, a localization error, duplicate output, an incomplete
annotation, or a nonexistent part; this comparison alone cannot distinguish
those causes. It nevertheless demonstrates that the unmatched outputs on this
reproduction were already present before MobileSAM. It does not prove that an
unsupplied recent failing image behaves identically.

Current measurements are saved in
[`model2_compatibility_test.json`](../results/qa/sam/model2_compatibility_test.json).
The historical exposure audit found exact-byte training overlap for 15 of the
17 test-export images, further limiting any generalization claim.

## Why fish-viewer overlays looked worse

The following counts replay actual saved detector outputs and the unchanged
association code. Extra draws are summed across individually opened fish
viewers; they are not additional neural predictions or unique physical parts.

| Scene | Raw selected Model 2 boxes | Owned boxes | Unassigned/ambiguous boxes | Extra unowned draws across old fish viewers |
| --- | ---: | ---: | ---: | ---: |
| Natural multi-fish image | 17 | 9 | 8 | 17 |
| Recorded reproduction photo | 19 | 6 | 13 | 43 |

After removing the diagnostic-drawing branch, the ordinary viewer draws only
its selected fish's assigned parts, so those extra unowned draws are absent.
The raw detection counts and grading evidence remain unchanged. Current-frame
parent identity and source coordinates must still match before painting parts.

## Reproduce and investigate further

From the project root, in a suitable CPU environment:

```powershell
$env:CUDA_VISIBLE_DEVICES = ""
$env:OMP_NUM_THREADS = "1"
python -B -m src.evaluation.evaluate_active_model2_parts --splits test --device cpu --operating-confidence 0.25 --output results/qa/sam/model2_compatibility_test.json
python -B -m results.qa.sam.model2_audit_reproduction
```

The second command consumes the historical report and preserved pre-MobileSAM
source snapshot. It checks exact source/output equality and checkpoint integrity;
it does not train, change settings, or create annotation labels. The 17-image
export is a development convenience sample. A recent original failing image
and reviewed part/ownership labels are needed to establish whether the user's
remaining concern is detector precision, incorrect grading class, ownership,
or another display path. Operating-point changes require validation; none was
fabricated or silently enabled here.
