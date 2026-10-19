# Phase 13 — navigation and dashboard

Status: provisionally validated in simulated data and headless Chrome, not on physical devices.

Live Inspection owns the camera, Analyze Image, feed display controls and session analytics disclosure. History and Review are separate views; Model and optional Expert are separate views. Analytics navigation opens the disclosure inside Live. Settings and Export use the desktop sidebar or, on widths below 1024 px, the header. The duplicate settings display controls remain hidden to preserve their IDs and synchronized handler compatibility; the visible controls are next to the feed. Camera calibration remains a separate camera action.

`tests/navigation_qa_smoke.py` checked keyboard activation of each primary view and Settings/Export, one visible Settings/Export entry at 390 and 1280 px, and the Analytics destination. Headless screenshots are `13_navigation_mobile.png` and `13_navigation_desktop.png`; no before screenshot was captured. Focused dashboard/history/export tests passed 53 tests and four subtests; existing dashboard polling/history smoke passed. A first smoke harness failed on an import and a second did not send the browser Enter character; the corrected harness passed. Actual operator usability, physical devices and assistive technology have not been assessed.
