"""Pydantic schemas - defines the API contract (what the agent sends, what the dashboard receives)."""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class ActivityIngest(BaseModel):
    """Payload the desktop agent POSTs on every sample tick."""
    device_id: str
    hostname: Optional[str] = None
    os_user: Optional[str] = None
    os_name: Optional[str] = "Windows"
    timestamp: datetime
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    is_idle: bool = False
    idle_seconds: int = 0
    interval_seconds: int = Field(default=5, ge=1, le=300)
    paused: bool = False


class IngestResponse(BaseModel):
    status: str
    device_id: str


class DeviceOut(BaseModel):
    device_id: str
    hostname: Optional[str]
    os_user: Optional[str]
    os_name: Optional[str]
    first_seen: datetime
    last_seen: datetime
    status: str  # "active" | "idle" | "paused" | "offline"
    active_seconds_today: int
    idle_seconds_today: int

    class Config:
        from_attributes = True


class AppUsage(BaseModel):
    app_name: str
    seconds: int


class OverviewOut(BaseModel):
    total_devices: int
    active_devices: int
    idle_devices: int
    offline_devices: int
    total_active_seconds_today: int
    total_idle_seconds_today: int
    top_apps_today: List[AppUsage]


class TimelineBucket(BaseModel):
    bucket_start: datetime
    active_seconds: int
    idle_seconds: int


class SessionOut(BaseModel):
    device_id: str
    hostname: Optional[str]
    app_name: Optional[str]
    window_title: Optional[str]
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    is_idle: bool
