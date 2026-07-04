# Mini Activity Analytics Platform

A small ActivTrak-style activity analytics system: a visible Windows desktop
agent, a backend API, and a web dashboard.

```
activity-analytics/
├── agent/              Windows desktop agent (Python, system tray)
├── backend/             FastAPI backend + SQLite + static dashboard
│   ├── app/              API source
│   └── dashboard/         Static HTML/CSS/JS dashboard (served by the API)
├── README.md
└── AI_USAGE.md
```

---

## 1. Quick start

### Backend (run first)

Requires Python 3.10+.

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This creates `backend/activity.db` (SQLite) automatically and serves:
- API at `http://localhost:8000/api/v1/...`
- Dashboard at `http://localhost:8000/`

Open `http://localhost:8000/` in a browser — it will show "no devices yet"
until the agent starts sending data.

### Agent (Windows only)

```powershell
cd agent
pip install -r requirements.txt
python agent.py
```

A dot icon appears in the system tray (green = running, gray = paused).
Right-click it for **Pause tracking**, **Open log file**, and **Quit**.

By default the agent points at `http://127.0.0.1:8000`. To point it at a
backend running on another machine, set an environment variable before
launching:

```powershell
$env:ACTIVITY_BACKEND_URL = "http://<backend-host>:8000"
python agent.py
```

Other tunables (also via environment variables): `ACTIVITY_SAMPLE_SECS`
(default 5), `ACTIVITY_IDLE_SECS` (default 60).

The agent's device ID, and any settings you override, persist to
`%LOCALAPPDATA%\ActivityAnalyticsAgent\config.json`. Logs go to
`agent.log` in the same folder (openable from the tray menu).

### Dashboard

No separate setup — it's static files served by the backend at `/`. It
polls the API every 10 seconds and re-renders.

---

## 2. Architecture

```
┌──────────────────┐      HTTPS/HTTP POST        ┌──────────────────┐      fetch (poll)      ┌──────────────────┐
│  Desktop Agent    │  ───────────────────────►   │   Backend API     │  ◄────────────────────  │  Dashboard (web)  │
│  (Python, tray)   │   /api/v1/ingest             │  (FastAPI +       │   /api/v1/overview,     │  static HTML/JS,  │
│                    │   one sample every 5s        │   SQLite)         │   /devices, /timeline,  │  served by the    │
└──────────────────┘                               └──────────────────┘   /recent                │  backend at "/"   │
                                                                                                    └──────────────────┘
```

**Event model.** The agent doesn't try to decide what counts as a
"session" — it just reports what's true right now, every few seconds:
foreground app, window title, idle yes/no, and how many seconds this
sample covers. Those raw samples are stored as-is. All "session",
"total active time", "top apps" logic lives on the backend, computed at
read time. This keeps the agent simple and crash-safe (losing one sample
just means one small gap, not a corrupted session), and means the
aggregation rules can change without ever touching the agent or old data.

**Idle detection.** The agent reads Windows' own `GetLastInputInfo`
counter — a single timestamp of "when did the OS last see keyboard/mouse
input" — and compares it to the current tick count. It never sees *what*
was typed or clicked, so there's no keylogging surface at all.

**Backend.** FastAPI + SQLAlchemy + SQLite. Two tables:
- `devices` — one row per agent install, updated on every check-in
  (hostname, user, first/last seen, current pause state).
- `activity_samples` — one row per sample (device, timestamp, app,
  window title, idle flag, idle seconds, interval length).

Reads are computed with SQL aggregation (`GROUP BY app_name`,
`GROUP BY is_idle`, etc.) for totals and top apps, and a small Python pass
that merges consecutive same-app samples into human-readable "sessions"
for the recent-activity feed and device status.

**Dashboard.** Plain HTML/CSS + vanilla JS + Chart.js, served directly by
FastAPI's static file mount — no build step, no Node toolchain. It polls
five read endpoints and renders: device list with live status badges,
today's active/idle totals, a top-apps bar list, an hourly stacked
active/idle chart (last 24h), and a recent-activity feed.

**Why SQLite, not Postgres/etc.:** this is a take-home evaluated for
architecture and judgment at a small scale, not for production
concurrency. SQLite means `pip install` + `uvicorn` is the entire backend
setup — no Docker, no DB server, no connection strings. The data access
layer (`crud.py`) is isolated behind plain SQLAlchemy calls, so swapping
in Postgres later is a connection-string change, not a rewrite.

---

## 3. What's implemented

- **Desktop agent (Windows, Python, system tray)**
  - Foreground app + window title
  - Active vs. idle (OS-level last-input time, no hooks)
  - Timestamps / sample duration
  - Device ID (persisted) + hostname + OS username
  - Periodic heartbeat (every sample doubles as a liveness signal)
  - Visible tray icon at all times; one-click Pause/Resume; Quit
  - While paused, no app/window data is collected or sent
  - Configurable backend URL / sampling interval / idle threshold via env vars
- **Backend API**
  - Ingest endpoint with request validation (Pydantic)
  - Read endpoints for overview stats, device list, hourly timeline, recent activity
  - Device status derivation (active / idle / paused / offline)
- **Dashboard**
  - Active users/devices, last seen per device, total active/idle time,
    top applications, recent activity, activity over time — every item
    the assignment asked for
  - Auto-refreshes every 10s; shows a "backend unreachable" state if the
    API goes down

## 4. What's not implemented (by choice)

Per the assignment, optional features were deliberately deprioritized in
favor of a solid required scope:
- No Chrome extension
- No local batching/retry queue on the agent (a dropped sample due to a
  network blip is just skipped, not queued — see limitations below)
- No auth/API token on the backend (anyone who can reach the backend can
  post samples or read the dashboard — fine for a local take-home, not for
  production)
- No productive/unproductive app classification
- No date-range filtering (dashboard always shows "today" for totals, "last
  24h" for the chart and recent feed)

## 5. Known limitations

- **No offline queue.** If the backend is unreachable when the agent tries
  to send a sample, that sample is dropped (logged, not retried). Over a
  5-second sampling interval this only loses a few seconds of data per
  outage, but it's not zero-loss.
- **No auth.** The ingest endpoint accepts data from anyone who can reach
  it, and the dashboard has no login. Would need at minimum an API token on
  `/api/v1/ingest` and basic auth (or SSO) in front of the dashboard before
  this went anywhere near a real network.
- **Single SQLite file.** Fine for one team's worth of devices; would need
  Postgres (or similar) plus connection pooling for real concurrent write
  load from many agents.
- **Sessionization is O(n) in Python** over the last 24h of samples for the
  recent-activity feed. At small scale (a handful of devices, 5s sampling)
  this is fast; at real scale it should move into SQL (window functions)
  or a scheduled pre-aggregation job.
- **Window titles are sent in full.** Titles can contain sensitive
  information (email subject lines, document names). There's no redaction
  or per-app exclusion list yet — see below.
- **Idle threshold is global**, not configurable per user from the
  dashboard — only via an environment variable on the agent itself.

## 6. What I'd improve with more time

- **Local batching + retry** on the agent: buffer samples to a small local
  file when the backend is unreachable, flush on reconnect. This was the
  single most valuable optional feature on the list and the most natural
  next step.
- **Privacy controls surfaced properly**: an excluded-apps list (e.g. never
  record title for password managers or banking apps) and a visible
  "tracking paused until 5pm" schedule, configurable from the tray menu
  rather than a config file.
- **Auth**: a simple per-agent API token issued by the backend, plus basic
  login for the dashboard.
- **Move sessionization into SQL** (SQLite supports window functions) once
  data volume would make the Python merge slow.
- **Date range filtering** and a per-device detail page, both called out
  as optional features in the brief.
- **Package the agent** as a single .exe (PyInstaller) with a proper
  installer, rather than "run with python agent.py".

---

## 7. Privacy constraints — how they're satisfied

- No keylogging: idle detection reads a single OS timestamp, never key
  content.
- No camera/microphone/file monitoring/browser history import: none of
  these are touched anywhere in the codebase.
- No hidden tracking: the agent only exists as a visible tray icon; there
  is no way to run it without that icon appearing.
- Pause is one click away from the tray icon, and while paused no activity
  content is collected or transmitted.
