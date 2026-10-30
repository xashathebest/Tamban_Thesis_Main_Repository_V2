# Run the Tamban inspection dashboard

From PowerShell, start the dashboard with the project-local Python environment:

```powershell
Set-Location 'C:\Users\User\Downloads\Tamban_Thesis_Main_Repository\Thesis\sardinella-lemuru-ml'
$env:FISH_REQUIRE_BYTETRACK = '1'
.\.venv\Scripts\python.exe -m src.api
```

Open <http://127.0.0.1:8000>. `FISH_REQUIRE_BYTETRACK=1` makes startup fail
instead of silently falling back to IoU tracking when `lap` cannot load.
Check **Runtime Diagnostics** after startup; it must say `ByteTrack` before a
live inspection is accepted.

If port 8000 is already occupied by a backend reporting the IoU fallback, stop
that stopped backend and restart it with the command above. Do not run two
backends on port 8000.

If `.venv\Scripts\python.exe` is missing, create a clean project environment
with the Python that will run the dashboard, install the runtime requirements,
then install the pinned tracker wheel:

```powershell
$python = 'C:\Users\User\AppData\Local\Python\bin\python.exe'
& $python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-bytetrack.txt
```

For this repository's already prepared local environment, `lap==0.5.13` is
installed in `.venv`; no package was installed into the global interpreter.

To verify the startup state from another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/status |
  Select-Object inspection_status, camera_status, fps, tracker_backend, tracker_warning
```

`stopped`, `disconnected`, and `0.0 FPS` are normal before **Start inspection**.
They are not evidence of low inference performance. If camera index 0 is not
available, the dashboard now reports that error and returns to a clean stopped
state; select/connect the actual supported camera before retrying.

`LEMURU_CAMERA_INDEX` is read at backend startup. The Camera settings panel
shows the configured index and the bounded DirectShow/Media Foundation/default
open attempts; change the index only in the environment, then restart the
backend. The optional `LEMURU_DECISION_DEADLINE_SECONDS` setting has no default
and records timing telemetry only. Set it only after an independently approved
physical-conveyor acceptance limit exists; it never changes a count or grade.

Completed fish records are handed to SQLite through a bounded FIFO background
writer (default capacity: `FISH_EVENT_PERSISTENCE_QUEUE_CAPACITY=256`). Runtime
Diagnostics shows its depth, health, and any backpressure. At capacity, it
applies ordered backpressure rather than dropping a record or writing a newer
update ahead of an older one. Stop, reset, and policy rotation flush accepted
records before closing a session; if persistence has failed, the session stays
open and the inspection must not be treated as cleanly stopped.

To export a past durable run from the dashboard, choose **Export**, select
**Specific inspection run**, then choose the recorded run. The export is scoped
to that run's `session_id`, so its rows and recorded configuration stay
together. **Current session** remains the default for the active/latest run.

When a feed is running, Runtime Diagnostics also shows the current browser's
five-second MJPEG image-load rate. It is an observed browser event rate, not a
network/paint measurement; capture-to-display latency remains explicitly
unmeasured.
