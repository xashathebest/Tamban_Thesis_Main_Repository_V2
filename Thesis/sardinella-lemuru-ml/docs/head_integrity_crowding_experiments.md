# Crowded-fish head-integrity experiments

The user confirmed `WIN_20261106_15_18_19_Pro.jpg` as the previously successful four-fish image and `WIN_20261105_14_14_54_Pro.jpg` as the six-fish failure. The user identified the fourth and sixth fish from the left as headless. These are user-supplied qualitative target labels, not an independent calibration or held-out accuracy cohort.

The new stage baseline captures all 162 Python/configuration files in [baseline_source.zip](../results/qa/head_integrity_crowding_stage2/baseline_source.zip), with [SHA-256 hashes](../results/qa/head_integrity_crowding_stage2/baseline_source_hashes.json), before the crowded-scene changes. Both detectors use configured `cuda:0` in FP32 (the runtime leaves FP16 disabled pending numerical validation), and MobileSAM retains its configured CPU FP32 default. No model replacement, training, detector threshold change or silhouette-threshold fitting was used. A separate process also tested MobileSAM on `cuda:0` without changing persistent device settings. The GPU probe found an RTX 2050 with 4 GB and approximately 2.7 GB free before evaluation.

The detector's confidence order differs from visual left-to-right order:

| Position from left | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---:|---:|---:|---:|---:|---:|
| Model 1 fish ID | 2 | 3 | 1 | **6** | 5 | **4** |

See the [annotated overview](../results/qa/head_integrity_crowding_stage2/six_left_to_right_overview.jpg) and native SAM crop overlays for [Fish 6 / fourth from left](../results/qa/head_integrity_crowding_stage2/snapshot_six/native_fish6.jpg) and [Fish 4 / sixth from left](../results/qa/head_integrity_crowding_stage2/snapshot_six/native_fish4.jpg).

## Demonstrated blockers

Both target masks already isolate their respective fish, and pass the native mask geometry and neighbor-contamination checks. Their independent ownership eligibility fails because the normal part-association process provides no Body detection. Both full native silhouettes exhibit the existing slanted-cut geometry opposite a posterior tail. This is separate geometric torso evidence; it does not create a Model 2 Body detection or authorize normal quality grading.

| Target | Native foreground box | Maximum raw Head confidence | Existing accepted-part threshold | Native geometry |
|---|---|---:|---:|---|
| Fish 6 / fourth from left | `[2136, 362, 3016, 1783]` | 0.061256 | 0.25 | Slanted anterior cut; rise fraction 0.1954, persistence 0.6210, asymmetry 0.2837 |
| Fish 4 / sixth from left | `[3161, 35, 3582, 2001]` | 0.213064 | 0.25 | Slanted anterior cut; rise fraction 0.1858, persistence 0.5578, asymmetry 0.3920 |

Fish 6's original parent box starts at x=2149.07. Cropping the native mask to that box removes 13 columns of genuine foreground and therefore introduces an artificial boundary. Full-native geometry must retain the excluded pixels and continue checking the original image boundary.

The diagnostic flag also changes the old result. In the configured GPU baseline, the four-fish source gives one Rejected fish with raw diagnostic output disabled, but zero Rejected fish with raw output enabled. The latter exposes detections down to 0.001 that the old integrity path treats as hard vetoes. The maximum such Head confidence on the previously successful Fish 1 is only 0.061914. These diagnostic candidates are below the unchanged 0.25 part-evidence threshold. They should remain visible in diagnostics without changing grade decisions.

The six-fish baseline gives zero Rejected and six Ungraded results in either diagnostic mode. Its ordinary full-frame Model 2 output has four detections above 0.25: three Head candidates and one Body candidate. Only the Body associates to Fish 5 under the unchanged association rules.

## Prompt and crop experiments

All variants reuse the existing MobileSAM checkpoint and preserve the existing ownership gates. The variants are development experiments, not independently validated masks.

- Native box prompting already produces clean target masks.
- Positive and negative points from exclusive candidate-mask cores do not resolve missing Body evidence. They fragment Fish 6's mask in this scene.
- Running SAM on padded isolated crops does not resolve missing Body evidence. It introduces pair-overlap conflict for Fish 6 and sometimes fragments other masks.
- Running the same Model 2 at 0.25 on padded parent crops recovers additional Body candidates, but also produces Head detections on the user's headless targets: Fish 4 receives a 0.4331 Head candidate near the severed terminal face. The prior four-fish headless Fish 1 receives a 0.5484 Head candidate in its crop. Crop inference is therefore not a uniformly reliable recovery path.

Mapped crop detections were made to compete globally through the existing association implementation, both with boxes alone and with candidate-mask center support. This demonstrated possible evidence recovery, but did not establish independent ownership correctness. No crop detector recovery or unvalidated prompt variant was activated based on these examples.

The useful correction is to evaluate the already isolated native masks with the independent anatomical requirements, retain the existing part-evidence threshold, and keep missing Model 2 Body evidence distinct from measurable geometric torso support. Native clipping, mask contamination, Head evidence at the existing threshold and ambiguous geometry must continue to withhold rejection.

## Artifacts and reproduction

The [SAM experiment JSON](../results/qa/head_integrity_crowding_stage2/snapshot_experiments.json) contains every native/point/crop ownership outcome and anatomy measurement. The [crop-detection JSON](../results/qa/head_integrity_crowding_stage2/crop_detection.json) records each mapped detection, raw Head intersection and global association. The [configured-backend baseline](../results/qa/head_integrity_crowding_stage2/before_pipeline.json) records all six scenarios in both diagnostic modes.

```powershell
.\.venv\Scripts\python.exe -B results/qa/head_integrity_crowding_stage2/experiments.py --source snapshot
.\.venv\Scripts\python.exe -B results/qa/head_integrity_crowding_stage2/crop_detection.py
.\.venv\Scripts\python.exe -B results/qa/head_integrity_crowding_stage2/compare_pipeline.py --phase before
.\.venv\Scripts\python.exe -B results/qa/head_integrity_crowding_stage2/compare_pipeline.py --phase after
```

Independent biological calibration remains unavailable. The user-confirmed target labels and synthetic/qualitative controls support development regression checks; they do not supply an independent recall or false-rejection-rate estimate.
