# Secondary anatomical verification

Model 2 remains the primary detector. A missing accepted Head or Body now
activates a separate anatomical verification gate. The gate preserves the
existing quality scores, weights, thresholds, model weights and optional Tail.
Unvalidated silhouette measurements cannot automatically reject a fish.

## Audit findings

The active models are the existing one-class YOLO26s parent detector and
12-class YOLO26m quality/part detector. The four-photo native-checkpoint audit
found 27 parent fish, but only five accepted Heads and 21 accepted Bodies.
An association failure is a major reason for unavailable per-fish anatomy:
one Head candidate had detector confidence 0.810576 and containment 0.858951,
but its association score 0.674251 failed the unchanged 0.70 ownership gate.
Another seven best unaccepted Head candidates had competing-parent ambiguity.
These candidates cannot safely be assigned to a particular fish merely because
that fish lacks a Head detection.

The COCO labels contain grade-part boxes, not confirmed physical absence or
expert parent identity. The available test images also have historical training
exposure. These data support software compatibility checks, not missing-anatomy
accuracy claims. See the [baseline records and commands](../results/anatomical_verification_baseline/README.md).

The existing rejection paths are quality-class scoring, an optional trained
Rejected-part override, and a source-bound Head-integrity review hold. There was
no automatic independent physical-absence verifier for both Head and Body.
The older `StructuralEvidence` records remain review claims with no automatic
grade effect; they lack the source/frame/parent binding required by this gate.

## Current decision behavior

1. Both accepted Head and Body pass the existing part confidence threshold
   and are reliably associated with the same fish and frame:
   anatomical status is `PRESENT`; secondary geometry and catalog lookup are
   skipped. Continue the existing grading pipeline.
2. A required part is undetected or below the threshold: activate secondary
   verification for that part. Primary confidence describes accepted evidence
   for this fish, not the strongest arbitrary box anywhere in the image.
3. Reuse the current fish's existing segmentation. Inspect axis, direction,
   longitudinal tissue support, width profile and endpoint cut candidates.
   These observations remain uncalibrated and yield `UNCERTAIN` by themselves.
4. Independent, same-fish/frame/source reviewed evidence confirms physical
   absence: return `MISSING`, set final grade to `Rejected`, and record
   `RJ_CONFIRMED_MISSING_HEAD` or `RJ_CONFIRMED_MISSING_BODY`. No quality support
   or probability is invented for this anatomical override.
5. Independent evidence confirms presence: return `PRESENT` and continue the
   existing quality gates. Presence does not supply the missing part's quality
   grade. The active tail-optional policy may therefore still require review
   until reliable Head/Body grade evidence is available.
6. Conflicting, absent, stale, obscured or unsafe evidence: return `UNCERTAIN`
   with `NEEDS_REVIEW`; do not automatically reject for missing anatomy.

`Tail` is never investigated by this gate. Its existing quality evidence and
weighting remain governed by the original grading policy. Existing trained
Rejected quality labels can still reject normally when required anatomy passes.

The gate runs after the existing quality/fusion pipeline. Weighted scores,
contributions, effective weights, margins and provisional quality evidence are
preserved. Final verdict fields, nested fusion verdicts, UI badges and exports
agree on the final anatomical outcome. Current-frame uncertainty blocks a saved
temporal grade from concealing an unresolved anatomical observation; a later
complete primary observation can recover normally.

## Mask isolation and uncertainty safeguards

The new `RuntimeMaskContext.anatomical_candidate()` accessor reuses native
MobileSAM candidates without another encoder or prompt call. It checks current
source pixels, parent identity, native coordinates and geometry ownership.
It deliberately uses `mask_geometry_checks_passed`, because the existing
feature accessor's `engineering_checks_passed` already requires both detected
Head and Body and would otherwise prevent investigating either missing part.

Pixels potentially belonging to a neighboring parent's box make a candidate
unavailable. A failed neighboring mask is not evidence that its pixels belong
to this fish. Crops losing foreground, image-edge contact, merged/fragmented
masks, inadequate transverse tissue, uncertain axis direction and substantial
curvature withhold confident geometric interpretation. Full-frame/crop source
mismatches block reviewed anatomical decisions as well.

PCA gives an axis with a 180-degree ambiguity. Only an owned Head or Tail anchor
can resolve direction; Body elongation alone cannot identify the Head end. A
flat endpoint, mask discontinuity or high SAM mask-quality score cannot prove
that anatomical tissue is missing.

Geometry uses a working grid bounded to 384 pixels on its longest side. There
is no new GPU model, inference retry, checkpoint download, training job or
inference threshold change. Existing MobileSAM frame scheduling and CPU/GPU
fallback remain in place. Optional geometry failures become unavailable
evidence without aborting image, uploaded-video or camera inference.

## Independently reviewed anatomy records

The current automatic absence authority is independently reviewed anatomy.
No validated secondary anatomy detector or missing-anatomy calibration exists
in this checkout. Consequently, without independent records, genuine headless
or bodyless fish remain `UNCERTAIN` when Model 2 misses the relevant part.
This is the intentional false-rejection safeguard, not validated automatic
headless-fish recognition.

The trusted Python grading adapter accepts `anatomical_evidence=[...]`.
For normal inference an optional local catalog can be configured using
`FISH_ANATOMICAL_EVIDENCE_PATH`. The catalog is loaded only when a required
primary part is unavailable. Its schema is:

```json
{
  "schema_version": "anatomical_evidence_v1",
  "records": [
    {
      "region": "Head",
      "state": "confirmed_absent",
      "source": "expert_review",
      "fish_id": 7,
      "frame_id": "the-current-observation-frame-id",
      "source_id": "uploaded_photo",
      "frame_pixels_sha256": "the-actual-64-character-native-frame-sha256",
      "reviewed": true,
      "ownership_validated": true,
      "visibility_validated": true,
      "reviewer": "actual-reviewer-identifier",
      "review_id": "actual-review-record-identifier",
      "confidence": 0.99
    }
  ]
}
```

This is a schema illustration, not an approved example. `region` supports Head
and Body; `state` supports `present` and `confirmed_absent`. Every observation
must match the actual fish ID, frame ID, source ID and native-frame pixel hash.
Recorded ownership and visibility must be explicitly validated, with reviewer
and review identifiers. If a numeric reviewer confidence is supplied, it must
be finite and at least 0.95; it remains a review assertion, not calibrated
accuracy. A hard reviewed label may omit numerical confidence. Low confidence,
conflicting records, clipping, overlap, occlusion, uncertain parent ownership,
source mismatch or an unusable frame withhold anatomical confirmation.

The local catalog follows the existing trusted review-artifact model. The
system validates record consistency and source binding; it does not authenticate
the reviewer's identity or certify the truth of a supplied assertion. Catalogs
are limited to 1 MiB/1000 records; malformed or missing files fail closed.
Plain old Head/Tail structural review claims do not satisfy this schema.

## Supporting technology assessment

| Technology | Practical role | Decision |
| --- | --- | --- |
| Existing MobileSAM and OpenCV | Fish-specific silhouette, continuity, width and endpoint diagnostics; shared existing frame embedding | Implemented for conservative investigation; anatomical semantics remain unvalidated |
| SAM 2 | Possible future temporal mask propagation | Adds another checkpoint/dependency; no RTX 2050 latency or accuracy benefit demonstrated here |
| Independent small YOLO anatomy detector | Semantic Head/Body/Tail detection distinct from quality labels | Strong future option after approved training and expert labels for intact, physically absent, occluded and overlapping parts |
| Fish-specific keypoints | Snout, head/body boundary and body/tail boundary; directional orientation | Requires fish landmark labels and approved training; generic human pose weights do not provide fish anatomy |

Primary technical references: [MobileSAM](https://github.com/ChaoningZhang/MobileSAM),
[Ultralytics MobileSAM](https://docs.ultralytics.com/models/mobile-sam/),
[SAM 2](https://github.com/facebookresearch/sam2),
[Ultralytics keypoints](https://docs.ultralytics.com/tasks/pose/), and
[OpenCV contour geometry](https://docs.opencv.org/4.x/d1/d32/tutorial_py_contour_properties.html).
The deployment choices above are engineering judgments for the existing stack,
not performance claims extrapolated from another GPU.

## UI and export evidence

Live/result/detail/history views show accepted Model 2 Head/Body/Tail status and
confidence, secondary activation, each part's `PRESENT`/`MISSING`/`UNCERTAIN`
state, evidence source, confidence and reason. Confirmed absence displays the
explicit automatic rejection reason. CSV/XLSX expose 34 corresponding readable
and JSON evidence fields. Historical records without anatomy evidence display
`UNAVAILABLE`. `undetected_regions` describes primary misses;
`missing_regions` contains only independently confirmed physical absence.
Tail is displayed as optional and cannot activate anatomical rejection. A
missing or unavailable primary detection has no fabricated confidence value.
Readable evidence includes source, reviewer, review ID, fish ID and frame ID;
NEEDS REVIEW shows the unresolved association, visibility or evidence reason.

## Association and visibility follow-up

The November 25 review tightened the primary pass so ambiguous ownership,
unreliable parents and mismatched source evidence cannot produce a successful
anatomy claim from two boxes alone. Secondary absence confirmation also withholds
occluded, partially visible or incomplete silhouettes, and rejects malformed
visibility flags. Boolean or fractional identifiers cannot alias an integer
fish or frame ID. Reviewed anatomical records retain their original frame ID.

Masks and silhouette diagnostics carry the requested fish/frame identity and
native crop coordinates. Cached masks cannot cross logical frames even when
the image array is reused. Photo/video crop inference now uses the source
frame ID, with fish ID stored separately. Existing feature calculations, crack
detection, brightness analysis and the configured 70% Model 2 / 30% supporting
feature weights are unchanged by these additional anatomical safeguards.

## Actual validation

The [real-model secondary run](../results/anatomical_verification_baseline/secondary_results.json)
processed four original development photos with the existing Model 1, Model 2
and MobileSAM on CPU FP32. All three checkpoint hashes were unchanged.

- 27 fish; four complete primary anatomical checks skipped secondary geometry.
- 23 activated checks remained `UNCERTAIN`; zero automatic anatomical rejections.
- 18 native masks passed geometry checks; three yielded silhouette profiles,
  all with unresolved anatomical direction.
- Four actual MobileSAM encoder passes and 27 existing prompt decodes; zero
  additional segmentation inference or GrabCut calls from this gate.
- Two existing Rejected quality grades were retained for fish passing anatomy.

These observations demonstrate conservative behavior and inference reuse on
available photos. There are no independently labeled genuine headless/bodyless
specimens in the available validation corpus, so missing-part accuracy and
false-rejection rates remain unmeasured. The new synthetic regression tests
exercise intact, headless-shaped, bodyless-shaped, rotated, overlapping and
clipped silhouettes, authoritative review outcomes, source conflicts, temporal
recovery, scoring preservation and UI/CSV consistency. Synthetic shapes and
review fixtures are software-contract tests, not biological validation.

The full repository regression completed with **2,338 passed, 12 skipped** and
127 passing subtests in 104.51 seconds. The focused new anatomy/UI/export suite
completed with 147 passed. JavaScript syntax and Git whitespace checks passed.
The [saved regression log](../results/anatomical_verification_baseline/regression_final.log)
and [JUnit results](../results/anatomical_verification_baseline/regression_final.xml)
retain the run details. The checks cover existing image, uploaded-video and
camera software paths; this session did not capture a physical live camera or
validate genuine missing-part specimens.

The November 25 follow-up regression completed with **2,487 passed, 12 skipped**
and 127 passing subtests. The [follow-up log](../results/anatomical_verification_baseline/review_regression.log)
and [JUnit results](../results/anatomical_verification_baseline/review_regression.xml)
cover the stricter association, visibility and identity behavior. The actual
four-photo Model 1/Model 2/MobileSAM rerun retained four primary passes and 23
review cases with zero automatic anatomical rejections and unchanged checkpoint
bytes. These remain development compatibility observations, not independent
missing-part validation.

Before enabling a future automatic semantic detector or calibrated geometric
absence rule, collect expert-labeled genuine missing-part examples and measure
false rejections on independent intact, overlapping, edge-clipped and
foreshortened fish. Existing models require no retraining for the current safe
integration. Any proposed new training needs the owner's approval.
