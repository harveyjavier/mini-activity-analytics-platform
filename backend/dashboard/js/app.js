// Same-origin API since the dashboard is served by the backend itself.
const API_BASE = "";
const REFRESH_MS = 10000;

let chart = null;

function fmtDuration(totalSeconds) {
  if (!totalSeconds || totalSeconds < 0) return "0m";
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${totalSeconds}s`;
}

function fmtRelativeTime(isoString) {
  const then = new Date(isoString + (isoString.endsWith("Z") ? "" : "Z"));
  const now = new Date();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function fmtClockTime(isoString) {
  const d = new Date(isoString + (isoString.endsWith("Z") ? "" : "Z"));
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function badge(status) {
  const labels = { active: "Active", idle: "Idle", offline: "Offline", paused: "Paused" };
  return `<span class="badge ${status}"><span class="bdot"></span>${labels[status] || status}</span>`;
}

async function fetchJSON(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function refreshAll() {
  try {
    const [overview, devices, timeline, recent] = await Promise.all([
      fetchJSON("/api/v1/overview"),
      fetchJSON("/api/v1/devices"),
      fetchJSON("/api/v1/timeline?hours=24"),
      fetchJSON("/api/v1/recent?limit=25"),
    ]);
    renderOverview(overview);
    renderDevices(devices);
    renderTimeline(timeline);
    renderRecent(recent);
    setConnStatus(true);
  } catch (err) {
    console.error(err);
    setConnStatus(false);
  }
  document.getElementById("last-updated").textContent =
    "updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setConnStatus(ok) {
  const el = document.getElementById("conn-status");
  el.classList.toggle("ok", ok);
  el.innerHTML = ok
    ? `<span class="dot"></span> Live`
    : `<span class="dot"></span> Backend unreachable`;
}

function renderOverview(o) {
  document.getElementById("stat-active-devices").textContent = o.active_devices + o.idle_devices;
  document.getElementById("stat-devices-sub").textContent = `of ${o.total_devices} total`;
  document.getElementById("stat-active-time").textContent = fmtDuration(o.total_active_seconds_today);
  document.getElementById("stat-idle-time").textContent = fmtDuration(o.total_idle_seconds_today);

  const top = o.top_apps_today[0];
  document.getElementById("stat-top-app").textContent = top ? top.app_name : "—";
  document.getElementById("stat-top-app-sub").textContent = top ? fmtDuration(top.seconds) + " today" : "no data yet";

  const list = document.getElementById("top-apps-list");
  if (!o.top_apps_today.length) {
    list.innerHTML = `<div class="empty-row">No activity recorded yet</div>`;
  } else {
    const max = o.top_apps_today[0].seconds || 1;
    list.innerHTML = o.top_apps_today.map(a => `
      <div class="bar-row">
        <div class="bar-row-top">
          <span class="app-name">${escapeHtml(a.app_name)}</span>
          <span class="app-time">${fmtDuration(a.seconds)}</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${(a.seconds / max) * 100}%"></div></div>
      </div>
    `).join("");
  }
}

function renderDevices(devices) {
  document.getElementById("devices-count-hint").textContent = `${devices.length} device${devices.length === 1 ? "" : "s"}`;
  const tbody = document.getElementById("devices-tbody");
  if (!devices.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No devices have reported yet. Start the agent to see data here.</td></tr>`;
    return;
  }
  tbody.innerHTML = devices.map(d => `
    <tr>
      <td>${badge(d.status)}</td>
      <td>
        <div class="device-name">${escapeHtml(d.hostname || d.device_id)}</div>
        <div class="device-sub mono">${escapeHtml(d.device_id)}</div>
      </td>
      <td>${escapeHtml(d.os_user || "—")}</td>
      <td class="mono">${fmtRelativeTime(d.last_seen)}</td>
      <td class="mono">${fmtDuration(d.active_seconds_today)}</td>
      <td class="mono">${fmtDuration(d.idle_seconds_today)}</td>
    </tr>
  `).join("");
}

function renderRecent(sessions) {
  const tbody = document.getElementById("recent-tbody");
  const real = sessions.filter(s => !s.is_idle && s.app_name);
  if (!real.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">No recent activity</td></tr>`;
    return;
  }
  tbody.innerHTML = real.map(s => `
    <tr>
      <td>${escapeHtml(s.hostname || s.device_id)}</td>
      <td>${escapeHtml(s.app_name || "—")}</td>
      <td class="device-sub">${escapeHtml(s.window_title || "—")}</td>
      <td class="mono">${fmtDuration(s.duration_seconds)}</td>
      <td class="mono">${fmtClockTime(s.end_time)}</td>
    </tr>
  `).join("");
}

function renderTimeline(buckets) {
  const labels = buckets.map(b => fmtClockTime(b.bucket_start));
  const active = buckets.map(b => Math.round(b.active_seconds / 60));
  const idle = buckets.map(b => Math.round(b.idle_seconds / 60));

  const ctx = document.getElementById("timeline-chart").getContext("2d");
  if (chart) {
    chart.data.labels = labels;
    chart.data.datasets[0].data = active;
    chart.data.datasets[1].data = idle;
    chart.update();
    return;
  }
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Active (min)", data: active, backgroundColor: "#3E63FA", borderRadius: 4, stack: "s" },
        { label: "Idle (min)", data: idle, backgroundColor: "#F5D68B", borderRadius: 4, stack: "s" },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "top", labels: { boxWidth: 10, font: { size: 11 } } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 } } },
        y: { stacked: true, grid: { color: "#EEF0F5" }, ticks: { font: { size: 10 } } },
      },
    },
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.getElementById("refresh-btn").addEventListener("click", refreshAll);
refreshAll();
setInterval(refreshAll, REFRESH_MS);
