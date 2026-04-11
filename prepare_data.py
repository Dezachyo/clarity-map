"""
One-time setup script: downloads the Natural Earth coastline and
crops it to the Israeli Mediterranean coast bounding box.

Run once before starting the server:
    pip install geopandas requests
    python prepare_data.py
"""

import io
import zipfile
from pathlib import Path

import requests
import geopandas as gpd

OUT_PATH = Path("data/coast_israel.geojson")
URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"

# Israeli Mediterranean coast bounding box (lon_min, lat_min, lon_max, lat_max)
BBOX = (33.8, 29.4, 36.0, 33.5)

def main():
    print("Downloading Natural Earth 10m land polygons (~4 MB)...")
    resp = requests.get(URL, timeout=60)
    resp.raise_for_status()

    print("Extracting...")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        z.extractall("data/_ne_tmp")

    print("Cropping to Israeli coast...")
    world = gpd.read_file("data/_ne_tmp/ne_10m_land.shp")
    israel = world.cx[BBOX[0]:BBOX[2], BBOX[1]:BBOX[3]]

    if israel.empty:
        raise ValueError("Crop returned empty GeoDataFrame — check bbox")

    israel.to_file(OUT_PATH, driver="GeoJSON")
    print(f"Saved: {OUT_PATH}  ({OUT_PATH.stat().st_size // 1024} KB)")

    # Clean up temp files
    import shutil
    shutil.rmtree("data/_ne_tmp")
    print("Done. You can now run: uvicorn main:app --reload")

if __name__ == "__main__":
    main()
