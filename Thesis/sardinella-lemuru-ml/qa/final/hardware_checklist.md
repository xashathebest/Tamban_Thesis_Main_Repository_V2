# Defense and validation hardware checklist

- [ ] Verify Python/package versions satisfy `requirements.txt`; local observed OpenCV and Ultralytics were outside its stated ranges.
- [ ] Check both registered checkpoint paths/hashes and tracker backend; verify GPU availability only on the actual machine.
- [ ] Connect the intended camera and verify lighting, positioning, permissions, calibration and a locked profile.
- [ ] Use a disposable demo database, protect or back up actual history, and verify local storage capacity.
- [ ] Rehearse start/stop/restart, representative fish/overlap and raw/processed feed selection if enabled.
- [ ] Measure actual browser preview FPS and latency separately from AI processing and CPU/network overhead.
- [ ] Prepare a permitted still-image fallback and power/network arrangements; do not expose private evidence without consent.
- [ ] Run and record the supervised 30–60-minute stability procedure and the independent labeled study when available.
