# AI Usage Notes

## Tool used

Claude (Anthropic), used conversationally in a chat interface to design and
generate the majority of the codebase in this repository (agent, backend,
dashboard) and this documentation.

**Action item before submitting:** export the full chat transcript from this
conversation (the interface used to have this conversation should have an
export/share option) and place it alongside this file, or paste it into a
`TRANSCRIPT.md` in this repo, per the assignment's request for "the full
transcript, export, or clear notes." The notes below summarize that
interaction but are not a substitute for the transcript itself.

## What the AI was asked to do

1. Read and analyze the assignment PDF, surface the priorities and
   evaluation criteria implied by the document (agent > backend > dashboard,
   quality over quantity on optional features, engineering judgment as the
   real thing being graded).
2. Propose and implement an event model, database schema, and API shape for
   the backend.
3. Implement a Windows system-tray desktop agent in Python that samples
   foreground app, window title, and idle state, respecting the assignment's
   explicit privacy constraints (no keylogging, no hidden tracking, visible
   + pausable).
4. Implement a FastAPI + SQLite backend exposing ingest and read endpoints.
5. Implement a static HTML/CSS/JS dashboard (Chart.js for the timeline
   chart) covering every element the assignment listed: active
   users/devices, last seen, total active/idle time, top apps, recent
   activity, activity over time.
6. Write the README (architecture, setup, completed scope, limitations,
   future work) and this file.

## What was reviewed / changed rather than accepted as-is

- **Sample interval type strictness**: the Pydantic schema originally
  accepted any number for `interval_seconds`; during integration testing
  (see below) a fractional interval was correctly rejected with a 422. This
  surfaced that the schema's validation was working as intended, and was
  left as strict `int` on purpose — the agent always sends whole-second
  intervals, so a fractional value indicates a bug, not valid input.
- **Sessionization approach**: the AI's first instinct was to reach for
  SQL window functions (`LAG`/`LEAD`) to merge consecutive samples into
  sessions. That was deliberately simplified to a Python-side merge instead,
  for readability at this project's scale — documented as a known
  limitation and explicit "would improve with more time" item, since it
  won't scale indefinitely.
- **Local batching/retry**: the AI could have added a local queue-and-retry
  layer to the agent. This was intentionally left out per the assignment's
  instruction not to prioritize optional features, and called out
  explicitly in the README rather than silently omitted.
- **Auth**: no API token / login was added, again per the instruction to
  focus on required scope. Flagged clearly as a limitation rather than
  presented as production-ready.
- **Idle detection method**: verified the AI's proposed approach
  (`GetLastInputInfo`) does not read keystroke content, only a last-input
  timestamp — confirmed this satisfies the "no keylogging" constraint
  before accepting it.

## Testing performed on AI-generated code

Since the development environment used to have this conversation cannot run
Windows-specific libraries (`pywin32`), the following verification was done
before accepting the code:

- Backend: started the real FastAPI server, sent live HTTP requests to the
  ingest endpoint, seeded ~3 hours of synthetic multi-device activity, and
  inspected the JSON from every read endpoint (`/overview`, `/devices`,
  `/timeline`, `/recent`) to confirm the aggregation logic (totals, top
  apps, hourly buckets, session merging) produced correct numbers.
- Dashboard: loaded the live dashboard in a headless browser against the
  seeded backend and visually reviewed a screenshot to confirm the UI
  rendered correctly.
- Agent: since `pywin32`/`pystray` can't run outside Windows, the
  Windows-only modules (`win32gui`, `win32process`, `win32api`, `psutil`,
  `pystray`, `PIL`) were stubbed out in a test harness so the agent's own
  logic (config load/persist, sampling loop, pause behavior, payload
  construction, error handling on a dropped connection) could run for
  real. The stubbed agent was then pointed at the live backend and
  confirmed to successfully post samples that appeared correctly in
  `/api/v1/devices`.
- **Still needs verification on an actual Windows machine** before
  submission: the real `win32gui`/`win32api` calls, the system tray icon
  rendering and menu interactions, and `%LOCALAPPDATA%` path behavior. This
  is noted as a limitation until that manual pass is done.
