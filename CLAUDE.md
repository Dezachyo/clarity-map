# Clarity Map — Project Context

Water clarity reporting app for Israeli Mediterranean coast divers. Users submit reports from dive sites; data is visualized as colored markers and a heatmap on an interactive Leaflet map.

## Stack
- **Backend**: FastAPI (Python) — `main.py`
- **Geo logic**: Shapely + geopy — `geo.py`
- **Storage**: Google Sheets via gspread — `sheets.py`
- **Frontend**: Single HTML page + Leaflet.js — `templates/index.html`
- **Deployment**: Fly.io (always-on free tier)

## Data Model (Google Sheets columns)
```
username | submitted_at | dive_datetime | clarity_m | beach | depth_m | lat | lon
```
- `submitted_at`: server-generated timestamp
- `dive_datetime`: user-set dive time, defaults to now, can be past
- `clarity_m`: 0–40 meters (slider input)
- `depth_m`: dive depth — auto-filled from 1km=10m formula or user-set

## API Endpoints
- `GET /api/reports` → GeoJSON FeatureCollection of all reports
- `POST /api/report` → save new report to Google Sheets
- `GET /api/geo-info?lat=&lon=` → `{is_sea, depth_estimate, nearest_beach, nearest_beach_lat, nearest_beach_lon}`

## Geo Logic (geo.py)
- `is_in_sea(lat, lon)`: Shapely point-in-polygon against `data/coast_israel.geojson`
- `estimate_depth(lat, lon)`: distance to coastline in km × 10, capped at 200m
- `nearest_beach(lat, lon)`: haversine distance to each entry in `data/beaches.json`

## Coastline Data
- `data/coast_israel.geojson` — Israeli Mediterranean coastline polygon
- Source: Natural Earth 10m land polygons, cropped to Israel bbox
- Download: https://www.naturalearthdata.com/downloads/10m-physical-vectors/
- The file must contain a polygon where interior = land, so `not point.within(polygon)` = sea

## Beach List
`data/beaches.json` — ~20 hardcoded Mediterranean dive sites with lat/lon.
Mediterranean coast only. Red Sea / Eilat excluded for now.

## Credentials
- Google service account JSON stored locally at `.secrets/credentials.json` (gitignored)
- On Fly.io: set as `GOOGLE_CREDS` secret: `fly secrets set GOOGLE_CREDS="$(cat .secrets/credentials.json)"`
- Spreadsheet must be shared with the service account email
- `GOOGLE_SHEET_ID` env var holds the Sheet ID (from the spreadsheet URL)

## Local Dev
```bash
# Activate venv (every new terminal)
source .venv/bin/activate

# GOOGLE_CREDS loads automatically from ~/.zshrc (set up once with the command below)
# If it's not loading, run manually:
export GOOGLE_CREDS="$(cat '/Users/ordez/DS Projects/clarity-map/.secrets/credentials.json')"

# GOOGLE_SHEET_ID loads from .env automatically via load_dotenv() in main.py
# Sheet ID: 1EySIBsbDh2FLz3lXpNhfUKnzz_LLOCzGfr8gjzAt7NI

# Start the server
uvicorn main:app --reload
# open http://localhost:8000
# API docs at http://localhost:8000/docs
```

## One-time setup (already done)
```bash
# Add GOOGLE_CREDS to shell so it loads in every new terminal:
echo 'export GOOGLE_CREDS="$(cat '\''/Users/ordez/DS Projects/clarity-map/.secrets/credentials.json'\'')"' >> ~/.zshrc

# Install system dependency for Shapely:
brew install geos

# Download Israeli coastline GeoJSON:
python prepare_data.py
```

## Deployment
```bash
fly launch       # first time only
fly secrets set GOOGLE_CREDS="$(cat .secrets/credentials.json)"
fly secrets set GOOGLE_SHEET_ID="your_sheet_id_here"
fly deploy
```

## Visualization
- **Markers**: blue circles per report — dark navy (0m clarity) → light cyan (40m clarity)
- **Heatmap**: Leaflet.heat plugin, ~10km influence radius per report, same blue gradient
- Toggle button to show/hide heatmap layer

## Beach List Maintenance

`data/beaches.json` is the source of truth for beach names and coordinates. The frontend fetches it from `/api/beaches` at load time — no hardcoded copy to keep in sync.

### Renaming or moving beaches

Old reports in Google Sheets store the beach name as a plain string at submit time. If you rename or reposition beaches, run the migration script to re-snap old rows to the new nearest beach based on their stored `lat`/`lon`:

```bash
# Dry run — shows which rows would change, touches nothing
python migrate_beaches.py

# Apply — writes updated beach names to the sheet
python migrate_beaches.py --apply
```

Safe to run at any time. Dry run is always harmless. `--apply` only updates the `beach` column, nothing else.

## Future: Weather Data
When a report is submitted (`POST /api/report`), fetch weather at that lat/lon/time from Open-Meteo (free, no API key) and store as extra columns in the same Sheet row. Goal: build dataset to correlate weather with water clarity.

## Map Tile Options
- **Current**: `https://cdnil.govmap.gov.il/xyz/heb/{z}/{x}/{y}.png` — Israeli gov map, Hebrew labels
- **Fallback**: `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png` — CartoDB Positron, grey sea, English labels

## Owner Notes
- Owner is a data scientist, wants to understand and own the Python code
- Keep JS minimal — all logic in Python where possible
- No user auth for now — nickname only
- Mobile-first UI
