"""
Clarity Map — FastAPI backend.

Routes:
  GET  /                        → serve the map page
  GET  /api/reports             → all reports as GeoJSON FeatureCollection
  POST /api/report              → save a new report
  GET  /api/geo-info?lat=&lon=  → sea check + depth estimate + nearest beach
  GET  /api/grid                → mean clarity per grid cell as GeoJSON polygons
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List

from collections import defaultdict

import geo
import sheets

GRID_SIZE = 0.05  # degrees ≈ 5 km per cell

app = FastAPI(title="Clarity Map")

BASE_DIR = Path(__file__).parent
BEACHES_FILE = BASE_DIR / "data" / "beaches.json"
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── HTML pages ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin/beaches", response_class=HTMLResponse)
async def admin_beaches(request: Request):
    return templates.TemplateResponse("admin_beaches.html", {"request": request})


# ── Beaches API (read + write beaches.json) ────────────────────────────────────

class BeachEntry(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lat: float = Field(..., ge=29.0, le=33.5)
    lon: float = Field(..., ge=34.2, le=36.0)

@app.get("/api/beaches")
async def get_beaches():
    return json.loads(BEACHES_FILE.read_text())

@app.get("/api/coastline")
async def get_coastline():
    return json.loads((BASE_DIR / "data" / "coast_israel.geojson").read_text())

@app.post("/api/beaches")
async def save_beaches(beaches: List[BeachEntry]):
    if not beaches:
        raise HTTPException(status_code=400, detail="Beach list cannot be empty")
    data = [b.model_dump() for b in beaches]
    BEACHES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    geo._load_beaches.cache_clear()
    return {"saved": len(data)}


# ── Beach migration (re-snap old reports to current beach list) ────────────────

def _compute_migration_changes() -> list[dict]:
    """Return rows whose stored beach name differs from the nearest beach by coords."""
    sheet = sheets._get_sheet()
    rows = sheet.get_all_values()
    if not rows:
        return []
    header = rows[0]
    try:
        lat_i   = header.index("lat")
        lon_i   = header.index("lon")
        beach_i = header.index("beach")
    except ValueError:
        return []
    changes = []
    for i, row in enumerate(rows[1:], start=2):
        try:
            lat = float(row[lat_i])
            lon = float(row[lon_i])
        except (ValueError, IndexError):
            continue
        old_name = row[beach_i] if len(row) > beach_i else ""
        new_name = geo.nearest_beach(lat, lon)["name"]
        if old_name != new_name:
            changes.append({"row": i, "old": old_name, "new": new_name})
    return changes

@app.get("/api/beaches/migration-preview")
async def migration_preview():
    changes = _compute_migration_changes()
    return {"changes": changes}

@app.post("/api/beaches/migration-apply")
async def migration_apply():
    changes = _compute_migration_changes()
    if changes:
        sheets.update_rows_beach([(c["row"], c["new"]) for c in changes])
    return {"updated": len(changes)}


# ── GeoJSON reports ────────────────────────────────────────────────────────────

@app.get("/api/reports")
async def get_reports():
    """Return all reports as a GeoJSON FeatureCollection."""
    records = sheets.get_all_reports()
    features = []
    for r in records:
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
        except (KeyError, ValueError):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "username": r.get("username", ""),
                "submitted_at": r.get("submitted_at", ""),
                "dive_datetime": r.get("dive_datetime", ""),
                "clarity_m": r.get("clarity_m", 0),
                "beach": r.get("beach", ""),
                "depth_m": r.get("depth_m", 0),
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ── Submit report ──────────────────────────────────────────────────────────────

class ReportIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    dive_datetime: str  # ISO8601, e.g. "2024-06-01T09:30"
    clarity_m: float = Field(..., ge=0, le=40)
    beach: str = Field(..., min_length=1, max_length=100)
    depth_m: float = Field(..., ge=0, le=200)
    lat: float = Field(..., ge=29.0, le=33.5)
    lon: float = Field(..., ge=34.2, le=36.0)


@app.post("/api/report", status_code=201)
async def submit_report(report: ReportIn):
    """Validate and save a new dive report."""
    if not geo.is_in_sea(report.lat, report.lon):
        raise HTTPException(status_code=400, detail="Location is not in the sea")

    try:
        datetime.fromisoformat(report.dive_datetime)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dive date/time format")

    sheets.save_report(
        username=report.username,
        dive_datetime=report.dive_datetime,
        clarity_m=report.clarity_m,
        beach=report.beach,
        depth_m=report.depth_m,
        lat=report.lat,
        lon=report.lon,
    )
    return {"status": "ok"}


# ── Clarity grid ──────────────────────────────────────────────────────────────

@app.get("/api/grid")
async def get_grid():
    """
    Divide the sea into GRID_SIZE° cells, average clarity of all reports
    within each cell, return as GeoJSON polygons coloured by mean clarity.
    Only cells that contain at least one report are returned.
    """
    records = sheets.get_all_reports()

    # Bucket reports into grid cells
    cells = defaultdict(list)  # key → list of (lat, lon, clarity)
    for r in records:
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
            clarity = float(r["clarity_m"])
        except (KeyError, ValueError):
            continue
        cell_lat = round(int(lat / GRID_SIZE) * GRID_SIZE, 6)
        cell_lon = round(int(lon / GRID_SIZE) * GRID_SIZE, 6)
        cells[(cell_lat, cell_lon)].append((lat, lon, clarity))

    # Build GeoJSON polygon centered on mean position of reports in each cell
    features = []
    for values in cells.values():
        mean_lat = sum(v[0] for v in values) / len(values)
        mean_lon = sum(v[1] for v in values) / len(values)
        mean_clarity = sum(v[2] for v in values) / len(values)
        half = GRID_SIZE / 2
        s, n = mean_lat - half, mean_lat + half
        w, e = mean_lon - half, mean_lon + half
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
            },
            "properties": {
                "mean_clarity": round(mean_clarity, 1),
                "report_count": len(values),
            },
        })

    return {"type": "FeatureCollection", "features": features}


# ── Clarity stats ─────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats(hours: int = 24):
    """Return mean clarity for reports whose dive_datetime is within the last N hours."""
    if hours not in (24, 48, 168):
        raise HTTPException(status_code=400, detail="hours must be 24, 48, or 168")
    records = sheets.get_all_reports()
    cutoff = datetime.now() - timedelta(hours=hours)
    values = []
    for r in records:
        try:
            dt = datetime.fromisoformat(r["dive_datetime"])
            clarity = float(r["clarity_m"])
        except (KeyError, ValueError):
            continue
        if dt >= cutoff:
            values.append(clarity)
    if not values:
        return {"mean_clarity": None, "count": 0, "hours": hours}
    return {
        "mean_clarity": round(sum(values) / len(values), 1),
        "count": len(values),
        "hours": hours,
    }


# ── Geo info for map click ─────────────────────────────────────────────────────

@app.get("/api/geo-info")
async def geo_info(lat: float, lon: float):
    """
    Called when user clicks the map.
    Returns sea/land status, depth estimate, and nearest beach.
    """
    in_sea = geo.is_in_sea(lat, lon)
    if not in_sea:
        return {"is_sea": False}

    depth = geo.estimate_depth(lat, lon)
    beach = geo.nearest_beach(lat, lon)

    return {
        "is_sea": True,
        "depth_estimate": depth,
        "nearest_beach": beach["name"],
        "nearest_beach_lat": beach["lat"],
        "nearest_beach_lon": beach["lon"],
    }
