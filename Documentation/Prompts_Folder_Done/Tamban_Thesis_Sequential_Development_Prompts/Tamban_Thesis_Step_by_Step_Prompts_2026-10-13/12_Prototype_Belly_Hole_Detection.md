# PROMPT 12 - Prototype Belly-Hole / Tear Detection (Gated on Expert Labels)

Develop a **separate experimental structural-defect detector** for visible belly holes/tears on dried Tamban. This task may begin **only after** expert-approved defect definitions and sufficient labeled examples from the previous annotation stage exist. No general texture statistic should be relabeled a verified hole detector.

## Preflight - hard stop condition

Inspect the dataset for actual expert-reviewed belly-defect positives, acceptable processed openings as negative controls, specimen IDs, annotations with localization, and an independent validation split. If these are missing, **do not fabricate training data, trained weights or performance**. Instead create a proposal plus optional loader/test scaffold, report the blockers, and stop.

## If prerequisites exist

1. Compare feasible baselines (localized segmentation, object detector or fish-crop classifier) and justify the chosen smallest viable design.
2. Associate each defect region with the correct parent fish; ensure multi-fish overlap does not transfer defects between fish.
3. Train/validate with specimen-group splits, standard augmentation restricted to training, and reproducible configs/seeds.
4. Measure defect precision/recall, localization quality if applicable, false positives on normal processing openings, uncertain/occluded cases, and inference latency.
5. Output a typed `defect_evidence` record with source, region, confidence, visibility and model version. **Do not change the final A/B/C/Rejected label yet.**
6. Add unit and integration tests using mocks; isolate any GPU/checkpoint tests as optional.

## Acceptance criteria

- No direct `defect detected => Rejected` rule without a verified expert grading criterion and separate validation.
- Results distinguish unseen/uncertain belly area from verified intact/defective anatomy.
- Any performance statement includes real denominators and a leakage-safe evaluation set.

## Report back

Explain either the data blockers or the architecture, real results, files changed, and known failure modes.
