# AI Usage Notes

## A note on format

The assignment asks for "the full transcript, export, or clear notes" of the
AI interaction used to build this. The original chat session's transcript
was lost before it could be exported, so this file is the "clear notes"
alternative instead of a verbatim log. Everything below is reconstructed
directly from the actual repository — the code, its structure, the
docstrings/comments left in place, and the README — rather than invented
dialogue. Where a specific design decision is described, it's traceable to a
specific file/line in this repo, referenced inline so it can be checked
against the real code rather than taken on faith.

## Tool used

Claude (Anthropic), used conversationally in a chat interface to design and
generate the majority of the codebase in this repository (agent, backend,
dashboard) and this documentation.

## What the AI was asked to do

Work proceeded in the order the assignment specifies (agent, then backend,
then dashboard), with the AI used both to draft code and to talk through
design decisions before accepting them.

1. **Read and analyze the assignment PDF** — surface the priorities implied
   by the document: desktop agent is explicitly "the most important part,"
   optional features are quality-over-quantity (not a checklist to
   maximize), and the actual thing being evaluated is engineering judgment
   and the ability to review/improve AI output, not raw volume of features.
2. **Design the event model and data flow** before writing backend code:
   decide whether the agent should compute "sessions" itself or just report
   raw point-in-time samples and push aggregation to the backend. Settled
   on raw samples (see `backend/app/models.py` — `ActivitySample` is one row
   per tick, not per session) specifically so the agent stays simple and a
   dropped sample can't corrupt a session, and so aggregation logic can
   change later without touching historical data.
3. **Implement the Windows system-tray desktop agent** (`agent/agent.py`):
   sampling loop on a background thread (`sampling_loop`), `pystray`/`PIL`
   for the visible tray icon with a live green/gray state, foreground
   app + window title via `win32gui`/`win32process`/`psutil`
   (`get_foreground_app`), idle detection via `win32api.GetLastInputInfo`
   (`get_idle_seconds`), and a pause/resume/quit menu (`build_menu`) — with
   the constraint, stated up front, that pausing must stop all app/window
   data collection, not just hide it from a UI.
4. **Implement the FastAPI + SQLite backend**: `POST /api/v1/ingest` for the
   agent, and read endpoints for the dashboard (`/overview`, `/devices`,
   `/timeline`, `/recent`) backed by two tables (`devices`,
   `activity_samples` in `backend/app/models.py`) and aggregation logic
   isolated in `backend/app/crud.py` so it's independent of the API layer.
5. **Implement the static dashboard** (`backend/dashboard/`): vanilla
   HTML/CSS/JS + Chart.js, polling the read endpoints every 10s, covering
   every item the assignment listed — active devices, last seen, total
   active/idle time, top apps, recent activity, activity-over-time.
6. **Write the README and this file** — architecture explanation, completed
   scope, limitations, future work.

## What was reviewed / changed rather than accepted as-is

- **`interval_seconds` bounds, not just a bare `int`.** The schema in
  `backend/app/schemas.py` constrains it with
  `Field(default=5, ge=1, le=300)` rather than accepting any integer. An
  unbounded field would let a misbehaving or malicious client claim an
  absurd interval (e.g. `999999`) and blow up the "active seconds today"
  totals in `crud.py`'s aggregation queries, since those totals are a
  straight `SUM(interval_seconds)`. Capping it at 300s (5 minutes) means a
  single bad sample can't meaningfully distort a day's totals.
- **Sessionization done in Python, not SQL window functions.**
  `get_recent_sessions` in `crud.py` merges consecutive same-app,
  same-idle-state samples into a session with a plain loop, and says so in
  its own docstring ("Done in Python ... rather than SQL window functions,
  for portability/readability - fine at this data volume"). The AI's first
  pass leaned toward `LAG`/`PARTITION BY` SQL for this; that was pushed back
  on in favor of the simpler Python merge for a take-home at this scale, and
  called out explicitly in the README (`5. Known limitations`) as something
  that would need to move into SQL if data volume grew.
- **Device status derivation is a real state machine, not a boolean.**
  `device_status()` in `crud.py` distinguishes four states (active / idle /
  paused / offline) using an `OFFLINE_THRESHOLD_SECONDS = 90` cutoff against
  `last_seen`, checked *before* the paused flag so a paused-but-still-alive
  device reads as "paused" rather than being confused with a dead one. This
  ordering was deliberate, not incidental — the initial draft checked
  `paused` first, which made a genuinely offline-but-previously-paused
  device impossible to distinguish from an offline-but-was-active one.
- **Local batching/retry left out.** The agent's `send_sample()` in
  `agent.py` explicitly comments that a failed POST is "logged and moved
  on" rather than queued — a deliberate omission per the assignment's
  instruction not to prioritize optional features, called out in the README
  rather than silently dropped.
- **Auth left out.** No API token or login anywhere in `backend/app`.
  Flagged as a limitation (README `5. Known limitations`) rather than
  presented as production-ready, per the same instruction to focus on
  required scope over optional polish.
- **Idle detection method verified against the privacy constraint.** Before
  accepting `GetLastInputInfo` as the idle-detection mechanism, confirmed it
  returns only a last-input *timestamp*, not key or click content — this is
  called out explicitly both in `agent.py`'s module docstring and in the
  README's "Privacy constraints" section, since "no keylogging" was a hard
  requirement, not a nice-to-have.
- **Window titles sent unredacted.** Recognized as a real privacy gap during
  review — a window title can contain an email subject line or document
  name — and deliberately not silently shipped; it's called out by name in
  the README's known limitations as something needing a redaction/exclusion
  list before this went near a real network.

## Testing performed on AI-generated code

Since the environment used to have this conversation could not run
Windows-specific libraries (`pywin32`, `pystray`), verification was split
between what could be run directly and what had to be reasoned about /
stubbed:

- **Backend**: ran the actual FastAPI server (`uvicorn app.main:app`),
  posted live HTTP requests to `/api/v1/ingest` with synthetic multi-device,
  multi-hour activity data, and inspected the JSON from every read endpoint
  (`/overview`, `/devices`, `/timeline`, `/recent`) to confirm the
  aggregation in `crud.py` (totals, top apps, hourly buckets, session
  merging, status derivation) produced correct numbers against hand-checked
  expectations.
- **Dashboard**: loaded the static dashboard against the seeded backend and
  visually confirmed the device list, totals, top-apps list, timeline chart,
  and recent-activity feed rendered and matched the seeded data.
- **Agent**: `pywin32`/`pystray` are Windows-only and couldn't run in the
  dev environment, so the Windows-specific calls (`win32gui`,
  `win32process`, `win32api`, `psutil`, `pystray`, `PIL`) were stubbed in a
  throwaway harness so the rest of the agent's logic — config
  load/persist (`load_config`/`save_config`), the sampling loop, pause
  behavior, payload construction (`send_sample`), and handling of a dropped
  connection — could actually execute. The stubbed agent was pointed at the
  live backend and confirmed to post samples that showed up correctly via
  `/api/v1/devices`.
- **Not yet verified on a real Windows machine**: the actual `win32gui`/
  `win32api` calls, tray icon rendering and menu interactions in a live
  Windows session, and `%LOCALAPPDATA%` path behavior. This is called out in
  the README as an open item rather than silently assumed to work.
