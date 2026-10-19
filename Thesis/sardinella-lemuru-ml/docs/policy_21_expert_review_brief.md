# Pending expert review: two-part and structural policy

**Status: NOT APPROVED.** This brief records a proposal for the annotator and research team; it is not their confirmation. No structural-evidence gate or new production policy is approved by this document.

## Current and candidate behavior

The previous `standard` baseline requires observed Body evidence, at least one region, 50% original-weight coverage, and a final weighted support of at least 0.50, along with the other configured gates. A Body-only observation is eligible in principle, but its maximum contribution is 0.50, so it still needs to meet the final support and other gates. Its fixed weights are Body 0.50, Head 0.30, Tail 0.20; unobserved contributions remain zero. The user subsequently requested `tail_optional_v1` as the configured policy: it requires Body and Head and redistributes an unavailable Tail's weight. This request is not a recorded expert signoff or an independent evaluation.

The existing opt-in research candidate `two_part_v1` additionally requires Body and at least one of Head or Tail. It is not expert-approved or the default. With otherwise identical rules it adds a restriction and cannot increase eligibility over `standard`; any claim that it reduces Ungraded counts requires a specified different baseline and an independently evaluated comparison. Missing detection does not establish that anatomy is physically absent. A Model 2 `Rejected_*` label can contribute to the current model-derived Rejected verdict; it is not confirmation of a specific physical defect. A separate structural review record does not currently alter the AI grade.

## Questions requiring recorded annotator decisions

1. Confirm or correct the proposed consequences of a **physically confirmed** absent head and absent tail, including acceptable processing and cases where the state is uncertain.
2. Specify what observation and provenance affirmatively establish a defect, who may confirm it, and whether independent adjudication is required. What should happen if a part is occluded, outside the frame, or merely not detected?
3. Review `two_part_v1` with its unchanged weights, thresholds and candidate status. Confirm whether it is suitable for a study, and specify any intended baseline or alternate thresholds before claiming improved coverage.
4. Agree on the separate structural gate's inputs, precedence, audit trail, and behavior for unknown or conflicting evidence. Current review records are self-reported, not authenticated proof of expertise.

Record the actual annotator's name or permitted identifier, date, consultation reference, exact decisions and scope in a separate dated record; leave the proposal unapproved until that record exists. Do not insert assumed decisions or signatures.

## Evaluation required before policy change

Use the [independent validation protocol](independent_validation_protocol.md) and a locked, held-out specimen-linked set with independently reviewed fish-level grades and structural truth, including overlapping and occluded cases. Compare the same fish and unchanged original weights, retaining Ungraded outcomes and failures; report denominators, grade confusion, coverage, false rejection and relevant subgroups. The user has stated that the requested independent videos and expert labels are not yet available. No real-data policy comparison has therefore been performed. Synthetic tests demonstrate code behavior only.
