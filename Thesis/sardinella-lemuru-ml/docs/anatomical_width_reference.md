# Anatomical width measurements and reference review

`fish_geometry.py` estimates longitudinal length from a native-pixel PCA-aligned
silhouette and its centerline, rather than from an axis-aligned detector box.
The transverse profile records whole-fish maximum width, Body maximum width,
median width over the central half of the Body sections, Body longitudinal span,
and the Body-width profile coefficient of variation. The three ratios differ:

| Field | Definition |
| --- | --- |
| `relative_width_ratio` | Maximum Body width / whole-fish longitudinal length |
| `whole_fish_length_to_width_ratio` | Whole-fish longitudinal length / whole-fish maximum width |
| `body_width_to_length_ratio` | Maximum Body width / Body longitudinal span |

Lengths and widths use native pixels; ratios and profile variation are
dimensionless. A higher variation coefficient describes less uniform section
widths, not a validated quality diagnosis. The first ratio is the Class C
reference metric `body_width_to_fish_length_ratio`. It must not be compared with
reference ranges measured using either of the other ratios or the legacy bbox
proxy.

An explicitly reviewed Body pixel mask takes precedence over a Model 2 Body
polygon or its longitudinal rectangle window. Body pixels extending outside the
intended silhouette, fragmented support, mismatching parent identity, insufficient
resolution, uncertain orientation, overlap, and clipping remain reasons to
withhold measurements. Source pixels and original detector evidence are retained.
The ordinary bbox window remains a diagnostic approximation; it does not become
an independently validated Body boundary.

The candidate values remain in `candidate_measurements` when engineering checks
fail or SAM ownership/boundaries remain unvalidated. Native output dimensions,
model mask score, and successful computation do not approve anatomical accuracy.
Reviewed metrology additionally requires whole-mask measurement/ownership review,
recorded validation provenance, a reviewed Body mask, and the explicit
`body_region_validated` flag confirming its anatomical extent. A reviewed pixel
patch can localize candidate evidence without validating the maximum width of
the complete Body. These flags are supplied by external review, never inferred
from detector confidence.

## Frame and crop boundary audit

Ownership checks operate on original-frame masks. Actual foreground contact with
the original image edge remains a rejection. A detector rectangle touching the
image edge can contain background padding: for an original-frame MobileSAM
candidate with matching native provenance, that rectangle contact is recorded
separately from foreground clipping.

A second false-positive mechanism existed after cropping an otherwise complete
native silhouette to a tight fish ROI. Merely touching that ROI was previously
reported as silhouette truncation. Metrology now distinguishes it only when the
original-frame provenance, native dimensions, global foreground extent, and
retained foreground-pixel count prove that the complete silhouette remains in
the crop. Missing provenance, lost pixels, and real original-image contact still
withhold reliable metrology. This repair does not change independent ownership
validation or approve more masks by weakening anatomical checks.

## Configurable width scoring

`analyze_anatomical_body_width` consumes the reviewed geometry and supplies the
existing bounded post-weighted Class C fusion. It requires:

- Reliable native geometry with reviewed whole-fish ownership and complete Body
  support, with nonempty review provenance.
- Explicitly reviewed calibration limits and specimen ratios measured with the
  matching anatomical metric and capture source/perspective.
- A recorded reference distribution, unique specimen IDs, review provenance,
  and calibration ID/count.
- The existing independently supported Class C and baseline grading gates before
  the existing final fusion can actually apply a contribution.

Points increase continuously from zero at the reviewed normal upper reference
to ten at the reviewed extreme reference. These two limits are supplied by expert
review; the software does not select them. The existing configurable support
transfer remains capped at 0.10 and preserves Body/Head/Tail evidence and Rejected
support. An uncalibrated reference, context mismatch, missing ownership review,
or unreliable pixels cannot activate a contribution. The legacy bbox reference
configuration cannot silently calibrate the anatomical ratio. Existing bbox
measurements remain available separately for historical CSV comparisons.

No actual normal-width distributions or held-out anatomical validation records
were supplied, so no default anatomical ranges or grade changes are enabled.

## Required reference workflow

Create an empty worksheet without changing any original annotation:

```powershell
python -m src.evaluation.anatomical_width_reference template --output results/qa/sam_features/width_reference.template.json
```

Add independently reviewed specimen records with image hashes, original-pixel
length/width measurements, anatomical/ownership approval, normal/widened labels,
capture context, reviewer/reference, and independent reference/validation splits.
Repeated specimens, duplicate images, mixed capture contexts, and capture-session
leakage across splits are rejected. Complete the separate expert review block
with deliberately selected normal/extreme limits and a held-out grading report.

```powershell
python -m src.evaluation.anatomical_width_reference evaluate --input reviewed_widths.json --output results/qa/sam_features/width_reference.review.json
```

The report lists observed distributions and remaining data needs. Only a complete
external review produces a configuration proposal; the proposal always retains
`scoring_enabled=false`. The program neither verifies expert judgments nor
enables runtime grading, edits its input worksheet, or writes the application
configuration. Calibration approval and activation remain separate recorded
actions. Synthetic review flags in automated tests exercise software contracts;
they do not establish fish feature accuracy.
