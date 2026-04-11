"""
Geospatial helpers for Clarity Map.

Requires data/coast_israel.geojson — a GeoJSON polygon of the Israeli
Mediterranean coast where the interior is land. Obtain it by:
  1. Download Natural Earth 10m land polygons:
     https://www.naturalearthdata.com/downloads/10m-physical-vectors/
  2. Crop to bbox ~(29.4, 33.8, 34.0, 35.1) lat/lon covering Israeli coast
  3. Save the result as data/coast_israel.geojson
"""

import json
import math
from pathlib import Path
from functools import lru_cache

from shapely.geometry import Point, shape
from geopy.distance import geodesic

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _load_coastline():
    """Load and cache the coastline polygon at startup."""
    path = DATA_DIR / "coast_israel.geojson"
    if not path.exists():
        raise FileNotFoundError(
            "data/coast_israel.geojson not found. "
            "See CLAUDE.md for download instructions."
        )
    with open(path) as f:
        geojson = json.load(f)
    # Support both a FeatureCollection and a bare geometry/Feature
    if geojson["type"] == "FeatureCollection":
        geometries = [shape(feat["geometry"]) for feat in geojson["features"]]
    elif geojson["type"] == "Feature":
        geometries = [shape(geojson["geometry"])]
    else:
        geometries = [shape(geojson)]
    # Union all polygons into one land mass
    from shapely.ops import unary_union
    return unary_union(geometries)


@lru_cache(maxsize=1)
def _load_beaches():
    """Load and cache the beach list."""
    with open(DATA_DIR / "beaches.json") as f:
        return json.load(f)


def is_in_sea(lat: float, lon: float) -> bool:
    """Return True if the point is in the sea (not on land)."""
    land = _load_coastline()
    point = Point(lon, lat)  # Shapely uses (x=lon, y=lat)
    return not point.within(land)


def estimate_depth(lat: float, lon: float) -> float:
    """
    Estimate sea-bottom depth at a point using the formula:
        1 km from shore ≈ 10 m depth, capped at 200 m.

    Walks the exterior ring of the coastline polygon to find the
    nearest coast segment, then computes geodesic distance.
    """
    land = _load_coastline()
    # Get the nearest point on the coastline boundary
    from shapely.ops import nearest_points
    sea_point = Point(lon, lat)
    nearest_coast_point = nearest_points(sea_point, land.boundary)[1]

    dist_km = geodesic(
        (lat, lon),
        (nearest_coast_point.y, nearest_coast_point.x)
    ).km

    depth_m = dist_km * 10
    return min(round(depth_m, 1), 200.0)


def nearest_beach(lat: float, lon: float) -> dict:
    """
    Return the closest beach from beaches.json to the given point.
    Returns a dict with keys: name, lat, lon, distance_km.
    """
    beaches = _load_beaches()
    best = None
    best_dist = float("inf")

    for beach in beaches:
        dist = geodesic((lat, lon), (beach["lat"], beach["lon"])).km
        if dist < best_dist:
            best_dist = dist
            best = beach

    return {
        "name": best["name"],
        "lat": best["lat"],
        "lon": best["lon"],
        "distance_km": round(best_dist, 2),
    }


# --- Quick self-test ---
if __name__ == "__main__":
    # Achziv sea point (just offshore)
    test_lat, test_lon = 33.05, 35.085
    print(f"is_in_sea({test_lat}, {test_lon}): {is_in_sea(test_lat, test_lon)}")
    print(f"estimate_depth: {estimate_depth(test_lat, test_lon)} m")
    print(f"nearest_beach: {nearest_beach(test_lat, test_lon)}")

    # Land point (Haifa city center)
    land_lat, land_lon = 32.794, 34.989
    print(f"\nis_in_sea({land_lat}, {land_lon}) [should be False]: {is_in_sea(land_lat, land_lon)}")
