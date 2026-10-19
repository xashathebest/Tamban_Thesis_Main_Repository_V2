# Phase 15 — secondary workflows

Status: provisionally validated with temporary data and headless browser tests.

History provides session selection, fish ID search, filters, pagination and AI/manual grade fields. Review actions include session identity and preserve the original AI grade; a saved manual grade can be cleared. Settings distinguish detector thresholds from visual feed options and lock policy changes while active. Export supports selected fields or explicit all-evidence mode and current, today or custom dates. Open-ended custom date ranges remain valid. Invalid empty field selections or reversed dates now disable export; failures appear within the export dialog. A request in flight cannot be submitted twice even if form controls change.

`15_workflow_tests.log`: 76 passed, one warning. `15_export_browser.log` validates selection, range validation and a mocked export failure; `15_review_browser.log` validates a historical review with a reused track ID and unchanged current fish. `13_dashboard_smoke.log` checks pagination and stale request cancellation. Screenshot coverage is the stopped dashboard from phase 13; refresh persistence, exhaustive 422 interaction and keyboard-only secondary workflows have not all been verified.
