# Status polling fixture measurement

Measured with `python -m src.evaluation.status_polling_benchmark --repetitions 12` on this Windows machine, using an isolated synthetic SQLite database and FastAPI's in-process test client. No camera or real inspection records were used. Values include test-client and JSON serialization overhead; these are not production network or camera FPS measurements. Source data: `status_polling_fixtures.csv`.

| Synthetic fish | Legacy p50 / p95 (ms) | Live p50 / p95 (ms) | Legacy / live response bytes | SELECTs per request, legacy / live |
|---:|---:|---:|---:|---:|
| 0 | 5.336 / 5.907 | 4.758 / 4.946 | 19,108 / 12,330 | 1 / 1 |
| 100 | 5.681 / 6.246 | 4.029 / 4.696 | 24,399 / 12,332 | 1 / 1 |
| 1,000 | 17.521 / 23.468 | 5.121 / 5.931 | 73,001 / 12,333 | 1 / 1 |
| 10,000 | 139.675 / 226.910 | 4.544 / 5.299 | 568,003 / 12,334 | 1 / 1 |

The number of SELECT statements did **not** decrease: the live endpoint reads one indexed revision row instead of loading all session records. The archive in the in-memory tracker was empty in this fixture; real-session performance and concurrent writes may differ. Twelve samples do not establish a production p95. Analytics requests on record revisions add work separately and are not included in the live-poll timings. The legacy response remains available for existing clients.
