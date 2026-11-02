# Bounded CPU foreground sampling

The dominant mask operation was a three-iteration OpenCV GrabCut solve over
every native pixel of each unique fish ROI. Frame-local reuse already avoided
repeating the same ROI; a cache hit did not make the original full-resolution
solve cheaper. Morphology and two connected-component passes also ran at the
full crop size. These calls receive NumPy CPU arrays and invoke no CUDA API.
No Model 1 model, checkpoint, detection threshold, training file, or GPU model
execution was changed or used for this work.

## Implementation

- [preprocessing.py](../src/inference/preprocessing.py) introduces immutable
  `RuntimeMaskSettings`, bounded working grids, explicit sampling provenance,
  detailed operation timings, and native-policy cache isolation. The same
  three-iteration GrabCut and close/open/largest-component sequence is retained.
  Native crops no larger than the configured budget retain the original pixels.
- [fish_geometry_pipeline.py](../src/inference/fish_geometry_pipeline.py) requests
  native segmentation explicitly for a validated physical-calibration
  configuration. Supplied instance masks remain separate from runtime estimates.
- [fish_geometry.py](../src/inference/fish_geometry.py) retains native-pixel
  candidate estimates from sampled masks while withholding reliable final
  measurements, physical conversion, and width-grading claims.
- [test_qualitycheck_bounded_masks.py](../tests/test_qualitycheck_bounded_masks.py)
  checks numerical native preservation, limits, dimensions, cache ownership,
  settings isolation, projection provenance, boundary/component evidence,
  unavailable cases, and physical-calibration behavior.

The per-frame cache key contains the parent identity, exact integer native ROI,
pixel digest, and effective immutable sampling settings. A native metrology
request cannot receive a cached sampled mask. Conversely, an explicit native
request shares an existing native-policy entry rather than repeating an
equivalent solve. Configuration warnings do not alter algorithm identity.

Working-grid morphology and component analysis retain their own resolution
label. Selecting the largest component does not erase evidence of a second
foreground component. The original boundary-contact test now uses boolean
boundary strips, avoiding full coordinate arrays. It has the same result on
the unchanged native path.

The sampled binary foreground is lifted with nearest-neighbor reconstruction
to the **exact native ROI dimensions**. This does not restore missing contour
detail. Metadata records `sampling.mode`, `estimated`, `native_shape`,
`working_shape`, `scale_to_native`, `native_output_shape`, and
`boundary_sampling_footprint_native_px`. The footprint describes a working-grid
cell in native pixels; it is **not a validated anatomical measurement-error
bound**. Native original-frame crop bounds and parent ownership are retained.

Explicit validated projection crops an existing native-shaped mask without
another resize. Its sampling provenance describes the source generation ROI,
while `native_output_shape` records the projected target's actual dimensions.

Sampled geometry receives
`resampled_foreground_requires_native_validation`. Candidate length, maximum
Body width, ratio, and orientation are computed in native pixels where the
remaining quality checks permit, but the reliable measurement fields and
centimeter values stay unavailable. Sampling does not resolve clipping,
overlap, missing Body association, or uncertain ownership. A valid physical
scale alone cannot make a sampled boundary validated. The native opt-out
supports future metrology validation without silently changing physical units.

## Configuration

Set these process environment variables before starting the service:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `FISH_MASK_MAX_DIMENSION` | 640 | Maximum working-grid side; zero deliberately selects the original native algorithm and disables both sampling caps. |
| `FISH_MASK_MAX_PIXELS` | 200000 | Maximum working-grid area; zero disables this area cap while retaining a positive side cap. |

Explicit settings reject invalid types and limits. Invalid environment settings
fall back to the documented defaults with recorded warnings. A new frame
captures its own settings; cached entries do not change when configuration is
altered later. A bounded working grid with fewer than twelve transverse pixels
is marked unavailable instead of inventing missing contour detail.

`stage_timings_ms` reports resize, GrabCut, raw components, morphology, final
components, native lifting, and generation wall time. The context aggregates
generation stages separately from lookup/projection time. The total includes
its children; it must not be added to them to report an end-to-end duration.
Generation attempts, cache hits, downsized calls, rejection/failure counts, and
source/working pixel totals provide supporting diagnostics. `segmentation_calls`
and `cache_misses` count generation attempts; `grabcut_executions` counts actual
OpenCV invocations. Cache hits and underresolved-grid early returns add no
invocation, and a later morphology failure does not erase an invocation that
already occurred. Underresolved early returns report zero processed working
pixels, while retaining the planned grid shape for the failure explanation.

## CPU-only paired evidence

[segmentation_benchmark.py](../results/qa/qualitycheck/segmentation_benchmark.py)
loads the pre-edit generator from the frozen source archive and compares it
with the bounded implementation. It uses one OpenCV thread, seed zero for each
measurement, one warm-up per implementation, and two measured repetitions in
each ABBA phase: four measured samples per implementation and case. It does
not load either model or access the training process.

The final samples and operation details are retained in
[segmentation_before_after.json](../results/qa/qualitycheck/segmentation_before_after.json).
Its measured optimized source is archived separately as
[segmentation_benchmark_source.py](../results/qa/qualitycheck/segmentation_benchmark_source.py).
The subsequent invocation-counter refinement does not change the segmentation
algorithm; it has separate regression coverage rather than a new speed claim.

| Case | Frozen native median | Bounded median | Observed stage speedup |
| --- | ---: | ---: | ---: |
| Controlled 1280 × 480 ellipse | 631.37 ms | 152.62 ms | 4.14× |
| Actual exported Fish #5 native ROI, 490 × 1561 | 3012.15 ms | 468.79 ms | 6.43× |

The actual read-only source was found outside the training directories. Its
hash, native frame shape, and exact crop bounds are in the JSON. The parent
touches the frame boundary, so the sample cannot establish accurate whole-fish
anatomical measurements. These measurements cover **CPU foreground extraction**,
not the complete nine-fish inspection, live-camera FPS, or independent accuracy.
Background training and other processes can affect timing; the small sample
does not establish a general hardware performance guarantee.

The optimized **native opt-out** returns a mask exactly equal to the frozen
native generator on both cases with the same seed. The bounded mask changes:
IoU against the unvalidated native mask is 0.99272 for the ellipse and 0.89723
for the actual crop; foreground area changes by approximately 0.7335% and
5.8747%, respectively. Those differences are why sampled geometry is retained
as an estimate rather than silently replacing reliable measurements. Neither
baseline nor sampled masks have independent anatomical ground truth here.

The earlier, read-only prototype is archived separately in
[segmentation_initial_profile.json](../results/qa/qualitycheck/segmentation_initial_profile.json).
Its manually resized timing excludes final native lifting and is not used as
the complete before/after result.

Focused validation after implementation: **139 passed**, including twenty-two new
bounded-mask cases. The broader qualitycheck report records the final combined
suite and API/UI validation. Model confidence, weighted grading, physical
calibration data, and width/defect grading enablement are outside this sampling
change.
