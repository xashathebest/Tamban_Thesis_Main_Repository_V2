# PROMPT 09 - Research Experiment: Texture, GLCM, LBP and Edge Features

Test whether **texture and edge descriptors** improve Class B/C quality classification for Tamban dried fish. This is **not** automatic belly-hole detection and must not change the production grading rule yet. Inspect `src/features/texture.py` and the existing research training/evaluation scripts.

## Tasks

1. Reuse GLCM features (e.g., contrast, homogeneity, entropy, correlation), LBP, and gradient/edge statistics on validated fish or body-part masks, with clear resolution and color-space preprocessing.
2. Validate extraction on small images, uniform images, low light, background intrusion, touching fish and scale texture. Return missing/invalid outputs transparently.
3. Use expert-graded fish-level B/C data, grouped by individual specimen/capture source. Do not train/validate on duplicate fish or augmented copies across splits.
4. Run feature-only baselines and compare to the current weighted Model 2 baseline and the color-feature experiment **only if the same fish-level evaluation set is available**.
5. Produce ablation results, feature-importance/usage analysis (careful with correlated descriptors), class-wise metrics, and a gallery or index of false positives for manual review.
6. Document explicitly that an irregular edge is **not** necessarily a crack, tear or belly hole.

## Acceptance criteria

- Reproducible offline experiments; no live grading adjustments.
- Include lighting/noise limitations and any feature leakage risk.
- If labeled data are insufficient, report `NOT VALIDATED` and provide only testable infrastructure.

## Report back

Changed scripts/tests, measured results or blockers, and a concise recommendation: keep diagnostic, test further, or trial in fusion.
