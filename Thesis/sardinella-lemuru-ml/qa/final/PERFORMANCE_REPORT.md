# Performance report — measurements pending

No representative target-camera 0/1/overlap scene benchmark, browser paint FPS, capture-to-display latency, GPU speedup, optimization gain or network/JPEG overhead was measured. The default full-frame/interval configuration is not a validated speed or accuracy optimum. Installed PyTorch reported CUDA unavailable; Model 1 reported IoU fallback because optional `lap` was missing. The optional raw preview is capped at 15 offered frames per second; that is a configured upper bound, not observed FPS.

Follow `performance_baseline.md`, `performance_changes.md`, `12_preview.md` and `stability_maintenance.md`. Pair performance measurements with same-fish count, ownership and grade comparison using independent labels before changing optimization settings.
