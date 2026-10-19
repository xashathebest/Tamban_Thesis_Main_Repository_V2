# Prompt 12: Improve perceived smoothness truthfully

**Priority / phase:** P1 - live operator experience

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Improve perceived smoothness truthfully.

### Inspection and implementation tasks

Review `src/api/camera.py` capture/inference/JPEG streaming and MJPEG endpoint in `src/api/app.py`. The repository already has a capacity-one latest-frame queue: preserve it unless measurement proves a problem. Explore a lightweight independent video preview path that can continue at camera capture cadence while AI inference runs at its genuine processing rate.
If overlays are from a previous analyzed frame, show them as a dated/stale overlay with clear timestamps or display processed feed separately; NEVER overlay stale grades on a fresh fish as if current. Handle backpressure, disconnections, camera release, worker restart, subscriber count, and multiple clients.
Make stream modes and FPS labels clear: Preview FPS, AI Processing FPS, and Latency.

### Required verification

Measure actual browser-visible smoothness and latency, CPU/JPEG/network overhead, multi-client behavior, disconnect/reconnect, and accuracy invariants. If hardware cannot verify, provide a safe behind-flag implementation and mark field test BLOCKED.

### Deliverables for this step

Before/after stream trace, real display FPS measurement, latency and stale-overlay policy, rollback procedure.

## Execution rules (apply to this prompt)

- Operate on the **latest repository state**; earlier audit findings are leads to verify, not proof that a bug is still present. If already fixed, document evidence and make no unnecessary changes.
- Inspect relevant code and reproduce the issue **before** editing. Make incremental, reviewable changes; preserve working features and the two-model architecture.
- Missing large YOLO checkpoints in a shared ZIP are expected. Clearly distinguish simulated/model-free tests from actual model inference; label unavailable evaluations **BLOCKED**.
- Do not change scientific grade weights, required parts, rejection criteria, confidence interpretation, or feature-to-grade rules without explicit research approval and validation. No detected head is NOT proof the fish physically lacks a head; **Ungraded** is not **Rejected**.
- Include regression tests, full test commands/results, files changed, any API/config behavior change, and a rollback or feature flag when the behavior is significant. No fabricated measurements or claims of 100% accuracy.
- Stop and request approval before destructive dataset migrations, incompatible database/schema changes, irreversible historical result changes, or scientifically material policy decisions.

### Completion response format

1. **Finding/status:** confirmed bug, already fixed, improvement, or blocked, with source paths and short evidence.
2. **Changes made:** precise files/functions, concise before vs after.
3. **Tests:** commands, pass/fail/skip/blocked counts and relevant output.
4. **Risks and open questions:** anything requiring expert approval, camera, GPU or checkpoint.
5. **Next action:** handoff to the next numbered prompt without starting it.
