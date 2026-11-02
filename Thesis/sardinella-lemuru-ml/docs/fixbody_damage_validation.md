# Surface-discontinuity evidence and controlled validation

The surface diagnostic identifies narrow interior dark lines that warrant review. It does not diagnose cracks, fractures, or tears, validate damage, assess biological severity, or change a fish grade. No real-fish precision, recall, sensitivity, specificity, expert agreement, or biological accuracy has been established by this work.

The implementation is [damage.py](../src/features/damage.py). The API stores its evidence under `analysis.surface_damage`. Frame integration and coordinate provenance are handled by [frame_diagnostics.py](../src/inference/frame_diagnostics.py); foreground-mask sharing is handled by [preprocessing.py](../src/inference/preprocessing.py).

## Evidence generation

The diagnostic consumes the original RGB crop and its aligned foreground segmentation. Accepted runtime mask metadata uses `status="validated_for_features"`. This records software foreground checks; it does not establish anatomical correctness, reference segmentation accuracy, or crack validation. `mask_validated_for_cracks` remains `false`.

The supplied mask is never expanded, opened, or closed by the damage analysis. A distance-based interior excludes segmentation boundaries and thin features such as fins. Explicitly rejected masks, empty masks, insufficient interior support, and known overlapping, ambiguous, clipped, or partially visible parent fish cause abstention. A missing context flag does not establish that a fish is fully visible or isolated.

Within that interior, the implemented checks are:

1. Apply a small Gaussian filter and a black-hat dark-line response. The elliptical filter width is bounded to 9–21 pixels. A median/MAD noise estimate sets the response threshold, with a minimum of 12 intensity levels.
2. Reject short, broad, or insufficiently elongated connected components. The minimum extent is the larger of 12 pixels and 5% of the crop diagonal; principal-axis elongation must be at least 4.
3. Recheck candidate pixels against luminance computed directly from the original RGB image. Samples on both sides of the proposed line must remain within the foreground. At least 60% of the component must have two-sided contrast of at least 12 levels on the 0–255 luminance scale. This rejects a simple illumination step without treating processed edges as original-image confirmation.
4. Recompute extent on supported original-image pixels. Withhold three or more similarly oriented lines with comparable lengths as possible repeated surface/anatomical texture. Retain at most 12 locations and draw only their supported pixels.

These are conservative heuristic checks. Natural scales, gill markings, lateral lines, folds, narrow shadows, and other anatomy can still resemble a qualifying line. Repeated real damage can be suppressed by the texture filter. Broad, curved, low-contrast, boundary-connected, or occluded defects may be missed. The output therefore retains `damage_type="unclassified_surface_discontinuity"`.

## Interpretation and coordinates

| Output | Meaning |
| --- | --- |
| `status="not_detected"`, `label/evidence_state="No reliable evidence"` | No candidate survived the checks. This does not establish absence of damage. |
| `status="unavailable"`, `label/evidence_state="No reliable evidence"` | The available mask or parent context does not support reliable analysis. The reason is retained. |
| `status="suspected"`, `label/evidence_state="Suspected Damage"` | Localized line evidence warrants review; its cause remains unvalidated. |
| `Validated Damage` | Never emitted automatically by this diagnostic. It requires a separate validated review process and provenance. |
| `confidence` | Uncalibrated evidence strength, explicitly marked `heuristic_not_probability` and `confidence_calibrated=false`; it is not a probability of damage or measured accuracy. |
| `severity="unassessed"` | No validated severity estimate exists. Severity requires expert labels and reference measurements. |
| `estimated_length_px` | Principal-axis support extent in pixels, marked `straight_line_support_extent_not_full_crack_length`; it is not a curved crack path, full defect length, or physical measurement. |

No-evidence results have `confidence=null`, `estimated_length_px=null`, no locations, and an empty overlay. The feature function retains `validation_status="unvalidated"`, `mask_validated_for_cracks=false`, and `grade_adjustment=0.0`. Existing Model 2 grading weights and decisions do not use these candidates as penalties.

The feature function returns native input-crop coordinates: location boxes, two supported endpoints, and an aligned transient `overlay_mask`. The frame adapter adds `parent_track_id`, `frame_id`, `crop_bounds`, `coordinate_space="crop_local_native_pixels"`, mask metadata, and a translated `frame_bbox` for each location. Endpoints remain crop-local; add the crop origin to map them into the original frame. The overlay is applied using the damage crop's bounds, which can differ from the padded grading crop. Mask arrays stay out of serialized inspection evidence.

## Controlled tests

The following targeted command passed **40 tests**: 3 existing damage cases, 23 added damage reliability cases, 4 exact GLCM histogram cases, and 10 existing handcrafted-feature cases.

```powershell
python -m pytest tests/test_damage.py tests/test_damage_reliability.py tests/test_texture_histogram.py tests/test_handcrafted_features.py -q -p no:cacheprovider
```

The tests are [test_damage.py](../tests/test_damage.py), [test_damage_reliability.py](../tests/test_damage_reliability.py), [test_texture_histogram.py](../tests/test_texture_histogram.py), and [test_handcrafted_features.py](../tests/test_handcrafted_features.py).

| Controlled case | Checked outcome |
| --- | --- |
| One dark line drawn from `(30,35)` to `(145,85)`, 3-pixel stroke, on a uniform 120×180 RGB image | Suspected evidence; extent within 8% of the known drawn centerline length; supported overlay pixels lie on the original dark stroke and within the foreground. Endpoints lie within the reported location. |
| Two elongated dark strokes, existing regression fixture | Suspected supporting evidence remains available. |
| Uniform surface | No reliable evidence and no fabricated confidence, length, or locations. |
| Single shadow step, broad dark band, segmentation-boundary line, small scale-like circles, three repeated parallel bands, bright line | No reliable damage evidence in these specific constructed scenes. The three-band fixture exercises repeated-texture rejection. |
| Randomly changed background around an unchanged masked line | Identical evidence and overlay; input mask remains unchanged. |
| Visible line with each known overlap, ambiguity, clipping, or partial-visibility flag | Unavailable with an explanation. |
| Explicitly rejected mask metadata, empty foreground, or thin foreground | Unavailable rather than a suspected or validated defect. |
| Foreground metadata marked `validated_for_features` | Candidate analysis can proceed, while crack validation remains false. |
| Normalized floating-point RGB versus equivalent uint8 RGB | Identical evidence and overlay; bounded serialized evidence is JSON-safe. |
| Four-channel RGB, NaN RGB, out-of-range floating-point RGB, or NaN mask | Explicit input error. |
| Irregular texture masks, distances exceeding image dimensions, and quantization levels 4–256 | The optimized symmetric GLCM exactly matches the former indexed-addition count oracle, including valid-pair counts. |

[texture.py](../src/features/texture.py) now uses integer histogramming for GLCM pair counts. This preserves the measured texture features. Damage analysis no longer runs a duplicate full texture extraction to derive a count-based damage confidence. Edge density and candidate count alone no longer promote damage evidence.

These tests establish software behavior on controlled fixtures. The drawn lines are known image patterns, not expert-labeled biological cracks. Passing them does not establish real-fish classification accuracy, calibrated confidence, severity thresholds, or reliable fracture/tear diagnosis.

## Archived component measurements

The controlled component records are [before.json](../results/qa/fixbody/before.json) and [after.json](../results/qa/fixbody/after.json). The [paired software runner](../results/qa/fixbody/paired_software.py) compares the archived [baseline source snapshot](../results/qa/fixbody/baseline_source.zip) with the current source using [fixbody_benchmark.py](../src/evaluation/fixbody_benchmark.py). Both records are explicitly scoped `SOFTWARE_ONLY_SCRIPTED_DETECTIONS`, `accuracy="NOT_VALIDATED"`, and `real_camera_fps="NOT_MEASURED"`.

Each component times damage analysis on the same synthetic 100×300 crop and already generated mask. The controlled process order is `before1, after1, after2, before2` (ABBA). Every worker starts with OpenCV restricted to one thread and initial RNG seed 0. Each worker performs one unreported warm-up and five measured repetitions per component, giving two worker runs and ten pooled timing samples for each source version. Median milliseconds, rounded to four decimal places, are:

| Archived scene | Before | After | Evidence result |
| --- | ---: | ---: | --- |
| Clean ellipse | 11.1056 | 1.1260 | `not_detected` in both; the corrected display label is “No reliable evidence.” |
| Dark line on ellipse | 11.0838 | 2.4901 | `suspected` in both; fragmented output changes from 20 locations/10-pixel maximum box extent to one original-image-supported location/109.23-pixel principal-axis extent. |
| Stripes on ellipse | 9.6225 | 7.6613 | `not_detected` in both; the corrected display label is “No reliable evidence.” |

The archived dark-line confidence changes from 0.8 to 0.845 under a different, explicitly uncalibrated heuristic. That numerical increase is not an accuracy improvement. The location and extent changes are intentional evidence-method changes, so they should be reviewed separately from performance-only equivalence. Timing samples, p95 values, process order, and control settings remain in the JSON records. The original unpaired records are retained separately as [before_initial_unpaired.json](../results/qa/fixbody/before_initial_unpaired.json) and [after_initial_unpaired.json](../results/qa/fixbody/after_initial_unpaired.json); their timings are not used in this table. These small controlled software measurements do not establish statistical significance, field or real-camera FPS, GPU throughput, or performance on all fish images. The main fixbody report carries whole-pipeline measurements and full-suite results.

Real-fish validation still needs independently annotated defect locations, expert-confirmed defect types and severity, reference lengths, challenging normal texture/shadow examples, and an evaluation split separate from threshold selection. Physical units additionally require image-specific calibration. Until then, this evidence remains supporting diagnostics with no automatic grading penalties.
