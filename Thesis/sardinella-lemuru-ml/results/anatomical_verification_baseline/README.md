# Bounded actual-checkpoint anatomy baseline

Collected on November 24, 2026 using the existing production Model 1, Model 2,
and association evaluator. No masks, secondary verifier, training, model-file
writes, or confidence/association-threshold changes were made by this run.

From the project root in PowerShell:

```powershell
& 'C:/Users/User/AppData/Local/Python/bin/python.exe' -B results/anatomical_verification_baseline/collect_baseline.py
```

`baseline.json` retains full parent boxes, post-NMS production Model 2 outputs,
every association decision, per-parent accepted Head/Body confidence, best
unaccepted candidate with gate failures, original image SHA256 and unchanged
checkpoint SHA256. The four images are the three existing real association
fixtures plus one additional test photo; these were selected before inference.

| Photo stem (abbreviated) | Parents | Raw Head/Body/Tail | Accepted Head/Body/Tail | Ungraded |
| --- | ---: | --- | --- | ---: |
| WIN_20260823_22_09_34_Pro | 6 | 4 / 6 / 3 | 1 / 6 / 0 | 5 |
| WIN_20260902_18_40_32_Pro | 8 | 6 / 7 / 2 | 1 / 5 / 0 | 7 |
| WIN_20260902_18_56_53_Pro | 7 | 6 / 8 / 2 | 1 / 7 / 1 | 6 |
| 1000094989 | 6 | 5 / 6 / 6 | 2 / 3 / 2 | 5 |
| Total | 27 | 21 / 27 / 13 | 5 / 21 / 3 | 23 |

Twenty-two parents lack an accepted Head. Their best global same-region
candidate fails only the association-score gate in nine cases, has eligible
but competing-parent ambiguity in seven, fails containment/center/score in
four, and fails containment/score in two. Six parents lack an accepted Body:
three competing-parent ambiguities and one each of score-only,
containment/score, or containment/center/score failure. The best global
candidate is a diagnostic comparison, not a claim that the candidate belongs
to that parent.

For example, fish 4 in `WIN_20260902_18_56_53_Pro` has a Head candidate with
detector confidence 0.810576 and containment 0.858951, but association score
0.674251 is below the unchanged 0.70 threshold. A strong detector candidate
can therefore coexist with missing accepted evidence.

The active Model 1 SHA256 is
`c79f597c2ed51b45ac2911cdbc744f8d2a4bea2411efc6a6ec0d4bcab35901e2`;
Model 2 is
`f74cd336b6ba9274f3bbbad845f64d03d0d4cc78e79cf1c0392d0b07d1d53222`.
Both were checked before and after inference. This run used CPU FP32, one
Torch CPU thread, Torch 2.11.0+cu128 and Ultralytics 8.4.197. CUDA remained
uninitialized during collection. Separate read-only hardware discovery found
an NVIDIA RTX 2050 with 4096 MiB and available CUDA. Bare `python` resolves
to a nonfunctional WindowsApps alias on this machine; the explicit interpreter
above works. The optional `lap` dependency is absent; these baseline calls use
untracked `detect`, while live ByteTrack falls back to the existing IoU tracker.

These are development compatibility and software-gate measurements. The
COCO labels have no fish identity, physical missing-head/body annotation, or
independent expert ownership labels. Historical training exposure is known.
No anatomical-presence, absence, ownership accuracy, or rejection-accuracy
percentage can be computed from these data. Single-pass timings in the JSON
include first-use effects and are not a repeated performance benchmark.

## Current end-to-end secondary verification

The actual upload analyzer was then run on the same four original photos using
the current Model 1, Model 2 and MobileSAM backend, CPU FP32, one Torch thread,
and no configured anatomical review catalog:

```powershell
& 'C:/Users/User/AppData/Local/Python/bin/python.exe' -B results/anatomical_verification_baseline/collect_secondary_results.py
```

`secondary_results.json` records per-fish primary detections/confidence,
PRESENT/UNCERTAIN states, secondary geometry/reasons, native mask diagnostics,
existing quality grades and frame inference provenance. All runtime assertions
passed:

- Four fish with both accepted primary Head and Body detections skip secondary
  anatomy processing and retain an empty secondary geometry report.
- Twenty-three fish activate verification and remain UNCERTAIN; no silhouette
  alone authorizes automatic anatomical rejection.
- Eighteen masks pass native geometry checks. Three sufficiently isolated masks
  produce continuous-support/endpoint geometry candidates, whose anatomical
  direction remains UNCERTAIN. Geometry passing does not validate anatomy.
- Twenty uncertain reports contain overlap, neighbor, or association-ambiguity
  evidence.
- Exactly one actual MobileSAM encoder pass per original frame (four total),
  27 prompt decodes, and zero GrabCut calls are recorded. The anatomical branch
  reuses existing cached candidates.
- All three checkpoint SHA256 values remain unchanged. MobileSAM's checkpoint
  integrity is verified; CUDA remains uninitialized.

The final quality counters contain two Class C, two Rejected and 23 Ungraded.
Both Rejected verdicts come from unchanged Model 2 quality grading; automatic
anatomical rejections are zero. Whole-frame single-pass processing intervals
are 10.35, 5.31, 7.25 and 3.95 seconds, including existing feature diagnostics
and first-use effects. These CPU measurements do not establish GPU throughput
or incremental anatomical-verification overhead.

No actual confirmed headless/bodyless labels are available for these photos;
this run demonstrates abstention and inference reuse, not absence-detection
accuracy.
