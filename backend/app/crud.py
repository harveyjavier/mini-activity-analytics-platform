"""
Data access + aggregation logic.

This is where raw samples get turned into the things the dashboard needs:
device status, daily totals, top apps, a time-series for the activity
chart, and human-readable "sessions" (consecutive samples of the same app
merged together) for the recent-activity feed.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas

# A device with no samples in the last OFFLINE_THRESHOLD is considered offline.
OFFLINE_THRESHOLD_SECONDS = 90


def upsert_device(db: Session, payload: schemas.ActivityIngest) -> models.Device:
    device = db.get(models.Device, payload.device_id)
    if device is None:
        device = models.Device(
            device_id=payload.device_id,
            hostname=payload.hostname,
            os_user=payload.os_user,
            os_name=payload.os_name,
            first_seen=payload.timestamp,
            last_seen=payload.timestamp,
            paused=payload.paused,
        )
        db.add(device)
    else:
        device.hostname = payload.hostname or device.hostname
        device.os_user = payload.os_user or device.os_user
        device.last_seen = payload.timestamp
        device.paused = payload.paused
    db.commit()
    db.refresh(device)
    return device


def add_sample(db: Session, payload: schemas.ActivityIngest) -> models.ActivitySample:
    sample = models.ActivitySample(
        device_id=payload.device_id,
        timestamp=payload.timestamp,
        app_name=payload.app_name,
        window_title=payload.window_title,
        is_idle=payload.is_idle,
        idle_seconds=payload.idle_seconds,
        interval_seconds=payload.interval_seconds,
    )
    db.add(sample)
    db.commit()
    return sample


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def device_status(device: models.Device) -> str:
    now = datetime.now(timezone.utc)
    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if (now - last_seen).total_seconds() > OFFLINE_THRESHOLD_SECONDS:
        return "offline"
    if device.paused:
        return "paused"
    return "idle" if _last_sample_idle(device) else "active"


def _last_sample_idle(device: models.Device) -> bool:
    if not device.samples:
        return False
    last = max(device.samples, key=lambda s: s.timestamp)
    return bool(last.is_idle)


def get_devices(db: Session) -> List[schemas.DeviceOut]:
    devices = db.query(models.Device).all()
    today = _today_start()
    out = []
    for d in devices:
        active, idle = _totals_for_device(db, d.device_id, today)
        out.append(
            schemas.DeviceOut(
                device_id=d.device_id,
                hostname=d.hostname,
                os_user=d.os_user,
                os_name=d.os_name,
                first_seen=d.first_seen,
                last_seen=d.last_seen,
                status=device_status(d),
                active_seconds_today=active,
                idle_seconds_today=idle,
            )
        )
    return out


def _totals_for_device(db: Session, device_id: str, since: datetime):
    rows = (
        db.query(models.ActivitySample.is_idle, func.sum(models.ActivitySample.interval_seconds))
        .filter(models.ActivitySample.device_id == device_id, models.ActivitySample.timestamp >= since)
        .group_by(models.ActivitySample.is_idle)
        .all()
    )
    active = idle = 0
    for is_idle, total in rows:
        if is_idle:
            idle = total or 0
        else:
            active = total or 0
    return active, idle


def get_overview(db: Session) -> schemas.OverviewOut:
    devices = db.query(models.Device).all()
    statuses = [device_status(d) for d in devices]

    today = _today_start()
    totals = (
        db.query(models.ActivitySample.is_idle, func.sum(models.ActivitySample.interval_seconds))
        .filter(models.ActivitySample.timestamp >= today)
        .group_by(models.ActivitySample.is_idle)
        .all()
    )
    total_active = sum(t for is_idle, t in totals if not is_idle) or 0
    total_idle = sum(t for is_idle, t in totals if is_idle) or 0

    top_apps_rows = (
        db.query(models.ActivitySample.app_name, func.sum(models.ActivitySample.interval_seconds).label("secs"))
        .filter(models.ActivitySample.timestamp >= today, models.ActivitySample.is_idle == False)  # noqa: E712
        .filter(models.ActivitySample.app_name.isnot(None))
        .group_by(models.ActivitySample.app_name)
        .order_by(func.sum(models.ActivitySample.interval_seconds).desc())
        .limit(10)
        .all()
    )

    return schemas.OverviewOut(
        total_devices=len(devices),
        active_devices=statuses.count("active"),
        idle_devices=statuses.count("idle"),
        offline_devices=statuses.count("offline") + statuses.count("paused"),
        total_active_seconds_today=int(total_active),
        total_idle_seconds_today=int(total_idle),
        top_apps_today=[schemas.AppUsage(app_name=a, seconds=int(s)) for a, s in top_apps_rows],
    )


def get_timeline(db: Session, hours: int = 24) -> List[schemas.TimelineBucket]:
    """Bucket active/idle seconds into hourly buckets for the last `hours` hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    samples = (
        db.query(models.ActivitySample)
        .filter(models.ActivitySample.timestamp >= since)
        .all()
    )

    buckets = {}
    for s in samples:
        ts = s.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bucket_key = ts.replace(minute=0, second=0, microsecond=0)
        if bucket_key not in buckets:
            buckets[bucket_key] = {"active": 0, "idle": 0}
        if s.is_idle:
            buckets[bucket_key]["idle"] += s.interval_seconds
        else:
            buckets[bucket_key]["active"] += s.interval_seconds

    result = [
        schemas.TimelineBucket(bucket_start=k, active_seconds=v["active"], idle_seconds=v["idle"])
        for k, v in sorted(buckets.items())
    ]
    return result


def get_recent_sessions(db: Session, limit: int = 30) -> List[schemas.SessionOut]:
    """
    Merge consecutive same-app samples per device into readable "sessions"
    for the recent activity feed. Done in Python (rather than SQL window
    functions) for portability/readability - fine at this data volume.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    samples = (
        db.query(models.ActivitySample, models.Device)
        .join(models.Device, models.ActivitySample.device_id == models.Device.device_id)
        .filter(models.ActivitySample.timestamp >= since)
        .order_by(models.ActivitySample.device_id, models.ActivitySample.timestamp)
        .all()
    )

    sessions: List[schemas.SessionOut] = []
    current = None
    for sample, device in samples:
        if (
            current is not None
            and current["device_id"] == sample.device_id
            and current["app_name"] == sample.app_name
            and current["is_idle"] == sample.is_idle
        ):
            current["end_time"] = sample.timestamp
            current["duration_seconds"] += sample.interval_seconds
        else:
            if current is not None:
                sessions.append(schemas.SessionOut(**current))
            current = {
                "device_id": sample.device_id,
                "hostname": device.hostname,
                "app_name": sample.app_name,
                "window_title": sample.window_title,
                "start_time": sample.timestamp,
                "end_time": sample.timestamp,
                "duration_seconds": sample.interval_seconds,
                "is_idle": sample.is_idle,
            }
    if current is not None:
        sessions.append(schemas.SessionOut(**current))

    sessions.sort(key=lambda s: s.end_time, reverse=True)
    return sessions[:limit]


def get_device_detail(db: Session, device_id: str) -> Optional[models.Device]:
    return db.get(models.Device, device_id)
