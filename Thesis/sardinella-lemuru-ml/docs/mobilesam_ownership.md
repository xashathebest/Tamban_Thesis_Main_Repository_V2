# Experimental mask ownership checks

`src/inference/mask_ownership.py` evaluates a whole batch of MobileSAM candidate
masks in original-image pixel coordinates. It does not certify fish identities,
anatomical measurements, cracks, or a grading policy. A successful segmentation
call or a high predicted mask-quality score is never approval.

The public result is JSON-safe and has one entry per supplied parent Fish ID:

- `unavailable`: absent, empty, malformed, or incorrectly sized mask.
- `rejected`: failed pixel geometry, identity, contamination, clipping, or
  competing-mask checks.
- `ambiguous`: plausible pixel geometry but missing or uncertain anatomical
  ownership evidence.
- `checks_passed_unvalidated`: the engineering checks passed; independent
  ownership validation is still absent.

Every result retains `ownership_validated=false`, `approved_for_grading=false`,
`measurement_validated=false`, and `mask_validated_for_cracks=false`. The separate
`mask_geometry_checks_passed` field allows shadow experiments to inspect masks
whose ordinary part ownership is still unresolved. It never authorizes use in
the active grader.

The checks retain all foreground components and compare their sizes; they do
not discard a second fish and then describe the largest component as isolated.
They report foreground area, holes, a directionless principal-axis ratio, image
boundary contact, support inside the intended parent, pixels in neighboring
parents' exclusive regions, and pairwise mask overlap. Preexisting unambiguous
Head/Body detections supply consistency checks. A candidate covering a
neighbor's associated Head or Body is withheld, including from shadow proposals.
Detector-box coverage is explicitly a diagnostic ROI statistic, not a labeled
anatomical pixel mask. Missing Head or Body evidence does not establish physical
anatomy loss. Tail is optional.

`MaskOwnershipConfig` exposes the numerical rejection settings. They are
engineering defaults, not measured fish-class ranges or independently validated
ownership thresholds. SAM score does not enter them. Parent identity, prompt-box
identity, and an optional expected frame key are checked independently of mask
shape, preventing the reuse of a candidate under a different prompt or frame.

`trusted_prompt_points` accepts only explicitly reviewed part masks or polygons
with a matching parent, original-frame coordinates, recorded validation
provenance, ownership/mask validation, and reliable orientation. It chooses
interior pixels of that actual support, excluding pixels also claimed by another
reviewed parent. Ordinary Model 2 boxes produce no invented center points.

`body_support_mask` requires explicitly reviewed Body pixel support. It returns
only the intersection of those reviewed pixels and the candidate, after the
ownership checks pass and at least 95% of the reviewed Body support is retained.
This does not enlarge the reviewed region or validate the entire fish. A Body
rectangle alone produces an unavailable Body mask. Therefore ordinary
detection-only outputs cannot silently become a validated crack-analysis mask.

`shadow_mask_associations` reports `PROPOSED`, `AMBIGUOUS`, or `UNASSIGNED` part
ownership and enforces one candidate per anatomical region and parent. It leaves
raw detections and confidence values intact, always reports
`applied_to_grading=false`, and does not emit a final fish class. Its optional
effective-weight display uses the existing 50/30/20 or 62.5/37.5 rule only when
candidate Body and Head evidence is available.

Focused CPU validation: 48 new ownership tests and 12 existing association tests
passed. These cover mask/provenance reuse, fragmentation, clipping, neighboring
anatomy, mutually conflicting masks, absent required evidence, optional Tail,
reviewed-point conflicts, Body support, and shadow-only behavior. Synthetic
review flags in these tests are fixtures, not real expert approval. Real-world
false separation, merged touching fish, occlusion, prompt quality, and mask
accuracy still require independently reviewed examples. No accuracy percentage
is inferred from these checks.
