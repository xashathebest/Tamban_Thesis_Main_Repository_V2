# Phase 14 — live operator states

Status: provisionally validated with simulated states and model-free tests. Physical-camera workflows remain unverified.

| Backend state | Operator display | Start | Stop |
|---|---|---|---|
| stopped / idle | Stopped and camera placeholder | Enabled only with ready model | Disabled |
| starting | Starting; camera and inference preparation | Disabled | Enabled for cancellation |
| running | Live; connecting placeholder until a frame arrives | Disabled | Enabled |
| stopping | Stopping; waiting for worker and camera | Disabled | Disabled |
| errored | Inspection needs attention; backend message shown | Enabled only with ready model | Disabled |

Control requests are serialized and report pending work. A grade uses text, identifier, evidence reason and coverage in addition to color; Ungraded remains distinct from Rejected. Upload analysis is a separate workflow. A synthetic browser state trace is in `14_synthetic_states.json`; 62 tests and 16 subtests passed in `14_live_tests.log`, with browser checks in `14_state_browser.log`. The browser did not perform actual inference or use a physical camera. Camera loss/restart, slow inference, overlap, operator use and a long-running inspection remain pending hardware.
