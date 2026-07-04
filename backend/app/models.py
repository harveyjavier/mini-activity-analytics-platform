"""
Data model.

Two tables:

- Device: one row per machine/agent install. Updated on every ingest with
  last_seen so we always know which devices are currently reporting.

- ActivitySample: one row per periodic sample sent by the agent (default
  every 5s). Each sample represents a short slice of time
  (`interval_seconds`) and records what was in the foreground and whether
  the user was idle during that slice. Storing raw samples (rather than
  pre-computed sessions) keeps the agent simple and lets the backend derive
  sessions, totals, and time-series data however is needed - including
  changing the aggregation logic later without touching the agent.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)
    hostname = Column(String, nullable=True)
    os_user = Column(String, nullable=True)
    os_name = Column(String, nullable=True)
    first_seen = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow, index=True)
    paused = Column(Boolean, default=False)  # last known pause state reported by agent

    samples = relationship("ActivitySample", back_populates="device")


class ActivitySample(Base):
    __tablename__ = "activity_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.device_id"), index=True)
    timestamp = Column(DateTime, index=True)
    app_name = Column(String, nullable=True)
    window_title = Column(String, nullable=True)
    is_idle = Column(Boolean, default=False)
    idle_seconds = Column(Integer, default=0)
    interval_seconds = Column(Integer, default=5)  # duration this sample represents

    device = relationship("Device", back_populates="samples")


Index("ix_samples_device_timestamp", ActivitySample.device_id, ActivitySample.timestamp)
