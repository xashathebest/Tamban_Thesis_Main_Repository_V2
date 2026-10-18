# PROMPT 04 - Introduce a Configurable Two-Part Grading Policy

Implement a **controlled, opt-in** candidate grading policy for our Tamban thesis; do not quietly change the research baseline. Our professor suggested that a fish can be considered for quality grading when its **Body and at least one of Head or Tail** are reliably detected, since requiring all parts caused frequent Ungraded outputs.

## Rules and constraints

- Keep Model 1 / Model 2 architecture intact.
- Preserve the existing **fixed** weights Body=0.50, Head=0.30, Tail=0.20. Do not automatically renormalize missing parts. For Body A=.87 and Head A=.79 with no Tail, Class A weighted support is **.672**, not .84.
- **No Body => Ungraded / review**, not automatically Rejected.
- **Body only => Ungraded** under the proposed two-part policy.
- **Body+Head or Body+Tail => eligible for grading**, subject to actual confidence, weighted-support, temporal, ownership, and visibility safeguards; eligibility does not guarantee a specific grade.
- Physically missing Head and merely **undetected** Head are different. This prompt must **not** implement `Head not detected => Rejected`.

## Requested work

1. Inspect current policy, config parsing, runtime usage, and tests (`configs/grading_engine.yaml`, `src/inference/grading_policy.py`, `src/inference/grading_engine.py`).
2. Add a named/versioned opt-in policy profile or explicit flag; leave existing behavior as a reproducible baseline until approved by the team and annotator.
3. If policy applies, require Body plus Head or Tail while retaining existing evidence thresholds and debug reason codes. Document cases where Body+Tail is only provisional because physical head status cannot be verified.
4. Add unit tests for Body-only, Body+Head, Body+Tail, Head+Tail without Body, conflicting grade labels, thresholds, and an occluded head.
5. Show a small score table contrasting fixed missing-part weights with the incorrect renormalized calculation.

## Acceptance criteria

- New policy is opt-in, tested, and documented, not silently deployed.
- Ungraded and Rejected remain semantically distinct.
- Flag expert/team decisions that are still pending rather than inventing approval.

## Report back

Changed files, sample predictions/weighted calculations, test results, and the exact flag required to enable the policy.
