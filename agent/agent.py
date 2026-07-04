"""
Mini Activity Analytics - Windows Desktop Agent
=================================================

A visible system-tray application that periodically samples:
  - the foreground application and window title
  - whether the user is idle (based on OS-level last-input time)
and posts each sample to the backend API.

Privacy / visibility by design:
  - Runs only as a system tray icon - never hidden, no stealth mode.
  - Tray menu lets the user Pause/Resume or Quit at any time.
  - While paused, no activity data (app name / window title) is collected
    or sent - only a lightweight "still here, but paused" heartbeat.
  - Idle detection uses the OS's built-in last-input timestamp
    (GetLastInputInfo). No keyboard/mouse hooks, no keystroke content,
    no screenshots, no camera/mic, no file or browser-history access.

Run:
    python agent.py

Configure via environment variables (or edit DEFAULT_CONFIG below):
    ACTIVITY_BACKEND_URL   e.g. http://192.168.1.10:8000
    ACTIVITY_SAMPLE_SECS   sampling interval in seconds (default 5)
    ACTIVITY_IDLE_SECS     seconds of no input before considered idle (default 60)
"""
import json
import os
import sys
import time
import uuid
import socket
import getpass
import logging
import threading
from datetime import datetime, timezone

import requests

try:
    import win32gui
    import win32process
    import win32api
    import psutil
except ImportError:
    print("This agent requires pywin32 and psutil on Windows.")
    print("Install with: pip install -r requirements.txt")
    sys.exit(1)

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("This agent requires pystray and pillow for the tray icon.")
    print("Install with: pip install -r requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ActivityAnalyticsAgent")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "agent.log")

DEFAULT_CONFIG = {
    "backend_url": os.environ.get("ACTIVITY_BACKEND_URL", "http://127.0.0.1:8000"),
    "sample_interval_seconds": int(os.environ.get("ACTIVITY_SAMPLE_SECS", "5")),
    "idle_threshold_seconds": int(os.environ.get("ACTIVITY_IDLE_SECS", "60")),
    "device_id": None,  # generated once and persisted
}

os.makedirs(APP_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("agent")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception as e:
            log.warning(f"Could not read config, using defaults: {e}")

    if not cfg.get("device_id"):
        cfg["device_id"] = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save config: {e}")


CONFIG = load_config()


# ---------------------------------------------------------------------------
# Windows-specific data collection
# ---------------------------------------------------------------------------

def get_foreground_app():
    """Returns (process_name, window_title) for the current foreground window."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None, None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        title = win32gui.GetWindowText(hwnd) or ""
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = None
        return name, title
    except Exception as e:
        log.debug(f"get_foreground_app failed: {e}")
        return None, None


def get_idle_seconds():
    """
    Seconds since the last keyboard/mouse input, using the OS-level
    GetLastInputInfo counter. This reads a timestamp only - it does not
    read *what* was typed or clicked, so it cannot capture keystrokes.
    """
    try:
        last_input_tick = win32api.GetLastInputInfo()
        current_tick = win32api.GetTickCount()
        idle_ms = current_tick - last_input_tick
        return max(0, idle_ms // 1000)
    except Exception as e:
        log.debug(f"get_idle_seconds failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

def send_sample(app_name, window_title, is_idle, idle_seconds, paused):
    payload = {
        "device_id": CONFIG["device_id"],
        "hostname": socket.gethostname(),
        "os_user": getpass.getuser(),
        "os_name": "Windows",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_name": app_name,
        "window_title": window_title,
        "is_idle": is_idle,
        "idle_seconds": int(idle_seconds),
        "interval_seconds": CONFIG["sample_interval_seconds"],
        "paused": paused,
    }
    try:
        resp = requests.post(
            f"{CONFIG['backend_url']}/api/v1/ingest",
            json=payload,
            timeout=5,
        )
        if resp.status_code != 200:
            log.warning(f"Backend rejected sample: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        # Network/backend unavailable - log and move on. Known limitation:
        # this sample is dropped rather than queued for retry (see README).
        log.warning(f"Could not reach backend: {e}")


# ---------------------------------------------------------------------------
# Sampling loop
# ---------------------------------------------------------------------------

class AgentState:
    def __init__(self):
        self.paused = False
        self.running = True


state = AgentState()


def sampling_loop():
    log.info(f"Agent started. device_id={CONFIG['device_id']} backend={CONFIG['backend_url']}")
    while state.running:
        try:
            if state.paused:
                # Send a minimal heartbeat only - no app/window data while paused.
                send_sample(None, None, False, 0, paused=True)
            else:
                idle_secs = get_idle_seconds()
                is_idle = idle_secs >= CONFIG["idle_threshold_seconds"]
                app_name, window_title = get_foreground_app()
                send_sample(app_name, window_title, is_idle, idle_secs, paused=False)
        except Exception as e:
            log.error(f"Sampling loop error: {e}")
        time.sleep(CONFIG["sample_interval_seconds"])


# ---------------------------------------------------------------------------
# System tray UI
# ---------------------------------------------------------------------------

def make_icon_image(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


ICON_RUNNING = make_icon_image((34, 197, 94, 255))   # green
ICON_PAUSED = make_icon_image((148, 163, 184, 255))  # gray


def on_toggle_pause(icon, item):
    state.paused = not state.paused
    icon.icon = ICON_PAUSED if state.paused else ICON_RUNNING
    icon.title = tray_title()
    log.info(f"Agent {'paused' if state.paused else 'resumed'} by user.")
    icon.update_menu()


def on_open_log(icon, item):
    try:
        os.startfile(LOG_PATH)
    except Exception as e:
        log.warning(f"Could not open log: {e}")


def on_quit(icon, item):
    log.info("Agent quitting (user requested).")
    state.running = False
    icon.stop()


def tray_title():
    status = "Paused" if state.paused else "Running"
    return f"Activity Analytics Agent - {status}"


def pause_label(item):
    return "Resume tracking" if state.paused else "Pause tracking"


def status_label(item):
    return f"Status: {'Paused' if state.paused else 'Running'}"


def build_menu():
    return pystray.Menu(
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(pause_label, on_toggle_pause),
        pystray.MenuItem("Open log file", on_open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )


def main():
    thread = threading.Thread(target=sampling_loop, daemon=True)
    thread.start()

    icon = pystray.Icon(
        "activity_analytics_agent",
        icon=ICON_RUNNING,
        title=tray_title(),
        menu=build_menu(),
    )
    icon.run()


if __name__ == "__main__":
    main()
