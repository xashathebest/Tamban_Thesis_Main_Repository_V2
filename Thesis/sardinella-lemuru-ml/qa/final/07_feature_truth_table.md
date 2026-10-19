# 07 — Feature truth table and research decisions

This table describes the current implementation, not expert validation. `Saved` means available in recorded per-fish analysis when measured; `Displayed` identifies the present operator interface. Diagnostics may be disabled or unavailable for an individual fish. The detailed inventory is `docs/feature_claims_audit.md`.

| Feature | Coded | Live camera | Saved / displayed | Influences final grade | Expert validated |
|---|---|---|---|---|---|
| Model 2 Body/Head/Tail class confidences | Yes | Yes | Per-fish analysis, UI and exports | Yes, weighted class support and gates | No independent fish-level validation |
| Model 1 detection confidence and parent association | Yes | Yes | Trace and UI | Yes, detection/ownership eligibility, not a grade probability | No real overlap validation |
| Mean hue, mean saturation, mean HSV value, yellow proxy | Yes | Rectangular ROI when enabled | Analysis, UI and export | No | No |
| Median hue | Yes | Rectangular ROI when enabled | Analysis and export; not the main UI line | No | No |
| Median saturation/value, brown/dark/discoloration proxies | Yes | Rectangular ROI when enabled | Analysis; not individually shown in main UI/export columns | No | No |
| Highlight/specular proxy | Yes | Rectangular ROI when enabled | Analysis and UI | No | No |
| Frame/fish/background grayscale brightness and contrast | Yes | Yes | Current camera status/UI; profile/reference may retain calibration values | No | No |
| Sharpness and representative-frame score | Yes | Yes | Frame evidence, UI and selected export fields | Only if an optional frame-quality gate is explicitly enabled; best-frame selection alone does not grade | No |
| Masked color, reflectance, texture/edge and morphology | Yes | No validated mask-based live pipeline | Offline research outputs; not live grading UI | No | No |
| Named belly-hole or crack detection | No validated detector | No | Research consultation topic only | No | No |

ROI color values can include background and are not validated defect measurements. Generic edge density is not a belly-hole detector. Physical absence requires affirmative evidence; nondetection and occlusion do not establish it. The separate structural review currently does not override an AI grade.

The configured user-requested `tail_optional_v1` requires Body and Head; the distinct proposed `two_part_v1` (Body plus Head or Tail) remains opt-in and not expert approved. A possible structural rule for a physically confirmed missing Head versus Tail requires recorded expert criteria, provenance and adjudication, followed by independent evaluation before activation. The user has stated that the needed expert-labeled recordings are not yet available; no expert signature or comparative accuracy is inferred. See `docs/policy_21_expert_review_brief.md`, `docs/belly_defect_annotation_rubric.md`, and `docs/adaptive_tail_policy.md`.

Command: `python -B -m pytest -q -p no:cacheprovider tests/test_feature_claims_qa.py tests/test_structural_evidence.py tests/test_tail_optional_policy.py --tb=short`: **19 passed, 12 subtests passed** (`07_feature_claims.log`). No production feature or policy change was made.
