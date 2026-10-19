# Quick consultation brief

## Opening
Good afternoon, Ma'am. We want to confirm the grading policy and validation plan before changing more code. We brought the current workflow, difficult cases, dataset checks and clearly labeled policy examples. Some features and rules are still proposed, so we want to separate them from what is already implemented and tested.

## Six decisions to get today
1. **Eligible evidence:** Is Body + Head or Body + Tail enough? What happens when the head is hidden and its physical presence cannot be verified?
2. **Structural rules:** Confirm the missing-head rejection rule; clarify whether a tail-less fish can still be A, B or C; define how belly holes/tears affect grades.
3. **Weighting:** Is 50/30/20 a proposed hypothesis? Compare fixed weights and normalization separately, with an appropriate threshold for each. Ask how to handle ties.
4. **Ground truth:** Who assigns the final whole-fish grade independently? How do you identify the same physical fish across images and keep it in one split?
5. **Validation:** Which baselines, ablations, classes, conditions and acceptance criteria are required? Do not tune on the final test set.
6. **Performance:** What FPS, time-to-grade and error rates are acceptable on the declared local hardware? Separate camera FPS, processed FPS and browser display FPS.

## Present in this order
Workflow -> normal result -> difficult overlap/missing-part result -> policy table -> dataset support -> exploratory features -> actual local timing or explicit measurement gap -> decision sheet.

## Ready-to-show facts from the supplied ZIP
- Images: 861 train, 32 validation, 17 test.
- Test part annotations: A=0, B=4, C=90, Rejected=131. These are NOT whole-fish counts.
- Validation has no Grade_B_Body annotations.
- 8,799/9,093 training polygons are geometrically box-like. Boxes can be legitimate detection labels but are not precise fish-only masks.
- Body .87 A + Head .79 A: fixed score .672, coverage .80; hypothetical normalized score .84. Neither is accuracy.
- The current config uses minimum observed regions=1 and fixed original weights. Do not say the proposed two-part policy is already active.
- The appearance sample contains 158 TRAIN Body ROIs: A=40, B=40, C=38, Rejected=40. It is exploratory, not validation.

## Do not leave without recording
Exact decision; approved for implementation versus approved only for experiment; unresolved expert confirmation; owner; due date; required evidence for the next consultation.

## Closing
May we read back the agreed rules and next steps? We will leave unresolved expert criteria pending and send the decision log and evidence for your review.
