# Fixed-detection reproduction and postprocessing audit

`python -m src.evaluation.evaluate_association_repairs --collect-test-images --audit-models --verify-csv-model2 --repeats 11` performs one CPU-only, FP32 detector pass over the 17 original project test images, freezes those detections, and compares the saved pre-repair association implementation with the current implementation. Subsequent runs omit `--collect-test-images` and reuse the exact outputs. The optional `--verify-csv-model2` separately checks one fresh Model2 pass on the exact original CSV image. No segmentation, training, checkpoint writes, physical calibration or width grading are involved.

The additional input cohorts are the seven-record original CSV and ten previously recorded real-image stress scenes. They are reported separately because they contain overlapping source images and different detector generations. Do not aggregate them into an independent test accuracy score.

## Correct original CSV reproduction

The CSV's actual source metadata names `WIN_20260823_20_49_53_Pro.jpg`. The original exists at `C:/Users/User/Downloads/Class B/WIN_20260823_20_49_53_Pro.jpg` and has SHA256 `b41cb97575eebc5e8b42ade0cf53197aa028ac671e99f851966d1a0bfb0c3dae`. The separately available `20_47_00` image used by an earlier MobileSAM benchmark is a different scene.

Each CSV fish retains a native-image association trace. Individual summaries omit ambiguities unrelated to that fish, so their exact-identity union recovers all 22 original Model2 candidates: Head 7, Body 9, Tail 6. The harness checks that count against the original metadata. It uses these native boxes rather than the crop-clamped `model2_debug.raw_detections`, and retains the seven legacy recorded Model1 boxes. It never substitutes current Model1 detections for those parents.

The original historical export grades and weighted scores remain separately recorded. Before/after association replays both use the same current canonical grading policy. This distinction matters: a historical export and the later conservative association baseline need not retain identical selected Tail evidence.

A fresh CPU Model2 pass on that original native 3840×2160 image also produces 22 candidates. It agrees with the original exported native boxes within 0.000489 pixels and confidence within 0.00000155. The raw floating-point identities are not bit-identical; this small numerical difference is retained honestly in `csv_fresh_model2_verification.json`. The controlled before/after comparison uses the exact exported detections on both sides.

## What was checked

- Both actual local checkpoints' class maps match the registry and runtime validators exactly: Model1 class 0 `Fish`; Model2 IDs 0–11 are the trained grade/Body/Head/Tail classes in their original order.
- Both checkpoint SHA256 values match the protected registry values. Neither checkpoint initializes an end-to-end detection head; normal class-aware predictor NMS applies.
- Model1 uses confidence 0.50, input size 768, IoU 0.70 and maximum 132 detections. Model2 uses confidence 0.25 and input size 768; its adapter leaves IoU, class filtering and maximum detections at installed predictor defaults: IoU 0.70, no class filter, class-aware NMS, maximum 300. These settings were inspected and preserved.
- The ASTs of every adapter `predict`, Model1 `_detect`, and Model2 `_infer_parts` are identical to `results/qa/additional/baseline_source.zip`, reconstructed from tracked HEAD `728380ed518ff54f7c6ccad4e89d574a8e0bf39a`. Tracked files were clean when this task began. The archive was constructed after edits began; its embedded `baseline_manifest.json` explicitly records that provenance and does not claim a pre-edit snapshot time. The new preprocessing/association changes do not silently change those detector calls.
- The installed Ultralytics predictor letterboxes internally and calls `scale_boxes` before constructing its result. The adapters consume native-image `boxes.xyxy` and clamp once to the actual source dimensions. The 3840-pixel CSV and earlier 1280-pixel reproduction contain coordinates beyond the 768-pixel network input, consistent with that contract. The benchmark overlays draw on the matching source pixels.
- A fresh native CSV-image pass records the actual predictor settings, including `rect=True` from `YOLO.predict`'s method defaults. Its prepared input is 448×768, while the resulting boxes extend to native x=3838.821 and y=2160. The generic global configuration's `rect=False` is not the effective method override. No external resize or second coordinate scaling is added.
- Production `raw` candidates are already after the predictor's confidence filtering and NMS, not pre-NMS logits or every network proposal. Debug mode can expose the 0.001 operating floor separately; this benchmark retains the unchanged production floor. Small detections lost inside the network, confidence filtering or NMS cannot be recovered by association.
- Model2's prior 17-image part-box compatibility audit already found unchanged pre-/post-SAM detector behavior. The new fixed outputs contain 243 selected/raw candidates at the production threshold. This does not eliminate the existing detection errors: the earlier development COCO report had 190 matched, 53 unmatched predictions and 35 missed annotations among 225 part annotations. That part-level check is neither fish-parent ownership validation nor an independent accuracy evaluation; 15/17 source images overlap a historical training manifest.

## Artifacts and interpretation

`results/qa/additional/association_comparison.md` contains the current before/after table and association-only latency. `association_comparison.json` includes every candidate, score, acceptance threshold, rejection reason, changed decision and fish verdict. `current_17_native_detections.json` freezes the actual CPU outputs. `postprocessing_audit.json` records real checkpoint mappings/hashes and installed predictor defaults. Twenty-eight paired real-image overlays are under `visuals/`.

There are no independent expert fish-parent ownership labels. Correct assignments, false associations and correct grading coverage are deliberately null. Increased assigned or graded counts are diagnostic changes, not proof that ownership is correct. Existing COCO part labels do not identify their parent fish. Engineering regression fixtures establish that the software obeys its evidence rules, while visually plausible examples still require expert review.

Association timings exclude detector loading, inference, segmentation, image measurements, API and frontend rendering. Frozen detector latencies are single-pass provenance only, not a repeated end-to-end performance claim. CUDA remains uninitialized throughout collection and checkpoint audit.

The automated reproduction tests retain the exact seven CSV parents and global candidates and three actual fixed detector scenes. They check complete raw traces, unique parent/region assignments, unchanged source records, original CSV final classes, required Body/Head evidence and the 62.5/37.5 redistribution when Tail is unavailable. They never assert expert ownership accuracy.

## Confirmed crop truncation in the original CSV

The optional `--audit-csv-crops` calculation uses the current accepted native parts, original CSV parents and the actual source image, without running any model. The old zero-padding parent crop truncated three accepted part boxes; `crop_assigned_evidence` retains all three completely.

| Fish / accepted part | Native part box, xyxy | Old crop loss | Old box area lost |
|---|---|---|---:|
| 3 / Head | [1109.856, 263.683, 1459.813, 640.172] | Top 18.317 px | 4.865% |
| 3 / Body | [1006.047, 736.823, 1558.486, 1616.109] | Right 59.486 px | 10.768% |
| 5 / Body | [2193.062, 483.189, 3161.154, 973.251] | Top 5.811 px | 1.186% |

Fish 3's old crop `[997, 282, 1499, 2144]` expands to `[885, 151, 1671, 2160]`: left/top/right/bottom expansion `[112, 131, 172, 16]` pixels. Fish 5's `[1949, 489, 3555, 1089]` expands to `[1852, 386, 3652, 1186]`: expansion `[97, 103, 97, 97]`. Other current accepted evidence remains within its original crops. Exact native values and before/after area losses are retained in `results/qa/additional/csv_crop_truncation_audit.json`.

The expanded Fish 3 crop touches the image bottom; its original Model1 parent does not. That is a crop-boundary condition rather than proof that the parent fish is frame clipped. The helper changes neither the original parent anchor nor global part ownership, and it does not select additional evidence from contextual pixels. Preserving already accepted evidence fixes a crop defect without proving ownership correctness or increasing the original seven records' grading coverage.
