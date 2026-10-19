# PROMPT 05 - Add Explicit Structural Integrity Evidence Without False Rejection

Improve our Tamban grading system's handling of **physically missing Head/Tail** versus **not detected or not visible**. Expert guidance is currently *provisional*: a physically missing head reportedly means Rejected, while a fish missing its tail can still be considered for A/B/C grading. This must be reconfirmed and documented before using automatic rejection rules.

## Requested work

1. Trace existing `Rejected_Head` / `Rejected_Body` / `Rejected_Tail` model-class predictions and compare them with explicit structural `head_physically_missing` and `tail_physically_missing` facts. These are **different kinds of evidence**.
2. Introduce (or reuse, if present) a typed structural evidence representation with `present`, `confirmed_absent`, and `unknown_or_occluded`, plus source (`expert_review`, `verified_detector`, or `unverified`), confidence/provenance and timestamp. Default to **unknown**, never inferred absence from a missing bounding box.
3. Safely expose manual expert-review input/output and traceable reason codes. If the confirmed-head-absence rejection rule is implemented, keep it behind a disabled flag until expert approval and evidence-quality requirements are met.
4. Allow a verified missing-tail scenario to remain **eligible**, not automatically Rejected, while leaving any expert-imposed maximum grade unspecified until confirmed.
5. Add tests for confirmed absent head, head occluded, head detector miss, missing tail, no body, and conflicting structural evidence.

## Acceptance criteria

- No detection result by itself is translated into physical absence.
- Structural Rejected is traceable to a verified criterion, not a missing part label.
- Unknown anatomy remains reviewable and never masquerades as confirmed rejection.

## Report back

Show the evidence schema, policy gates/defaults, tests/results, and the unanswered expert questions. Do not claim the annotator has approved a rule without signed/recorded confirmation.
