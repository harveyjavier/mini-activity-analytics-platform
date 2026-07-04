"""
Mini Activity Analytics - Backend API

Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Serves:
- POST /api/v1/ingest        <- agent posts samples here
- GET  /api/v1/overview      <- summary stats for dashboard header
- GET  /api/v1/devices       <- device list w/ status + today's totals
- GET  /api/v1/devices/{id}  <- single device detail
- GET  /api/v1/timeline      <- hourly active/idle seconds for the chart
- GET  /api/v1/recent        <- recent activity feed (sessionized)
- GET  /                     <- static dashboard (index.html)
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import os

from . import models, schemas, crud
from .database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mini Activity Analytics API", version="1.0.0")

# CORS left open since the agent and dashboard may run on different hosts
# on the local network during evaluation. Tighten this for real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/ingest", response_model=schemas.IngestResponse)
def ingest(payload: schemas.ActivityIngest, db: Session = Depends(get_db)):
    crud.upsert_device(db, payload)
    # Don't store a row for paused ticks with no app data - nothing useful to aggregate.
    if not payload.paused:
        crud.add_sample(db, payload)
    return schemas.IngestResponse(status="ok", device_id=payload.device_id)


@app.get("/api/v1/overview", response_model=schemas.OverviewOut)
def overview(db: Session = Depends(get_db)):
    return crud.get_overview(db)


@app.get("/api/v1/devices", response_model=List[schemas.DeviceOut])
def devices(db: Session = Depends(get_db)):
    return crud.get_devices(db)


@app.get("/api/v1/devices/{device_id}")
def device_detail(device_id: str, db: Session = Depends(get_db)):
    device = crud.get_device_detail(db, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    all_devices = {d.device_id: d for d in crud.get_devices(db)}
    return all_devices.get(device_id)


@app.get("/api/v1/timeline", response_model=List[schemas.TimelineBucket])
def timeline(hours: int = 24, db: Session = Depends(get_db)):
    return crud.get_timeline(db, hours=hours)


@app.get("/api/v1/recent", response_model=List[schemas.SessionOut])
def recent(limit: int = 30, db: Session = Depends(get_db)):
    return crud.get_recent_sessions(db, limit=limit)


# --- Serve the static dashboard at "/" ---
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
