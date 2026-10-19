# Tamban Thesis - Detailed Code QA Fix Prompts

**Audit source:** `Thesis-main (2).zip` supplied on 13 October 2026.  
**Audit date:** 14 October 2026.  
**Purpose:** Separate one-at-a-time AI coding prompts for independently checking and fixing confirmed defects and other high-value engineering/research risks.  
**Number of prompts:** 23, each a standalone `.md` file.

## How to work through the prompts

1. Make a backup or create a Git branch before changes. Attach the CURRENT repository to your coding assistant, not just the old audit.
2. Start with `01_Baseline_Reproducible_Test_Audit.md`. It should measure the baseline and identify local setup limitations.
3. Apply **one** numbered prompt, inspect the diff, run its regression tests and the model-free suite, commit the change, and only then advance.
4. When a prompt says SOURCE-CONFIRMED or CONDITIONAL RISK, ask the coding assistant to reproduce it on your environment before editing. Do not treat the desired solution as proven.
5. Prompts **21** and **22** require external annotator confirmation or independent data. Never replace that with assumptions or made-up metrics.
6. Perform **23** last. Do not use this prompts ZIP as a claim that the fixes have already been implemented.

## Priority map

| Stage | Prompts | Why now |
|---|---|---|
| Baseline | 01 | Reproduce and protect working behavior |
| Blocking data integrity | 02-06 | Stop unsafe model/session transitions and partial state changes |
| Export and tracking integrity | 07-14 | Reliable evidence, fish identity, and model provenance |
| Robustness and portability | 15-19 | Uploads, large history, reviews, CI, optional LAN security |
| Scientific truthfulness | 20-22 | Accurate feature claims, approved grading rules, independent labels |
| Release | 23 | Full regression and locked evaluation |

## Findings categories used in prompts
- **REPRODUCED:** verified with a deterministic model-free test.
- **SOURCE-CONFIRMED:** a problematic branch/state-flow is visible in code; field incidence is not measured.
- **CONDITIONAL RISK:** needs a special workload, malformed request, network deployment, or hardware setup to occur.
- **REQUIRES EXPERT SIGNOFF / RESEARCH BLOCKER:** cannot be solved honestly by changing source code alone.

## Non-negotiable project facts
- Model 1: whole-fish detection and counting; Model 2: graded body-part detections.
- The 50/30/20 Body/Head/Tail weights are **current proposed policy**, not independently validated truth. Current live standard policy uses `minimum_regions_observed: 1`; the adviser suggested body plus head or tail.
- A physically absent head may imply Rejected per provisional expert guidance, but **head not detected** is NOT proof the head is absent. A physically missing tail may still be considered for grading, subject to expert confirmation.
- No original large model checkpoints were included; the missing files should not be counted as code defects.
- No real-device FPS or real-checkpoint model-accuracy measurements were run in this QA session.

Read `AUDIT_FINDINGS.md` for source references and test evidence. The file `REPRODUCTION_NOTES.md` records exact model-free examples.
