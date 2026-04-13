"""
Windguru forecast scraper for Tel-Aviv (station 308).
Uses the Windguru internal API (no Selenium needed) — fetches wind and wave
forecasts via two model calls, merges them, and returns a DataFrame.

Usage (standalone test):
    python wgscraper.py
"""

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta


STATION_URL = "https://www.windguru.cz/308"
FORECAST_API = "https://www.windguru.cz/int/iapi.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": STATION_URL,
}


def _fetch_model(session: requests.Session, id_spot: int, id_model: int) -> dict:
    params = {
        "q": "forecast",
        "id_spot": id_spot,
        "id_model": id_model,
        "runing": 4,
        "id_filetype": 1,
        "WGCACHEABLE": 21600,
        "_mha": 1,
    }
    resp = session.get(FORECAST_API, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def scrape_windguru(id_spot: int = 308, days: int = 3) -> pd.DataFrame:
    """
    Scrape Windguru forecast for the given spot.

    Args:
        id_spot: Windguru station ID (default 308 = Tel-Aviv).
        days: how many days of forecast to return (default 3).

    Returns:
        DataFrame with columns:
            forecast_datetime, wind_speed, gust_speed, wind_dir,
            swell_height, swell_period, swell_dir, station_id, station_name
    """
    session = requests.Session()

    # Get session cookie by visiting the station page
    session.get(STATION_URL, headers=HEADERS, timeout=15)

    # Wind data: GFS 13km (model 3)
    wind_data = _fetch_model(session, id_spot, id_model=3)
    # Wave data: GFS Wave Height (model 84)
    wave_data = _fetch_model(session, id_spot, id_model=84)

    wind_fcst = wind_data["fcst"]
    wave_fcst = wave_data["fcst"]

    # Build DataFrames for each model indexed by forecast hour offset
    wind_df = pd.DataFrame({
        "hour_offset": wind_fcst["hours"],
        "wind_speed":  wind_fcst["WINDSPD"],
        "gust_speed":  wind_fcst["GUST"],
        "wind_dir":    wind_fcst["WINDDIR"],
    })

    wave_df = pd.DataFrame({
        "hour_offset":   wave_fcst["hours"],
        "swell_height":  wave_fcst["HTSGW"],
        "swell_period":  wave_fcst["PERPW"],
        "swell_dir":     wave_fcst["DIRPW"],
    })

    merged = pd.merge(wind_df, wave_df, on="hour_offset", how="inner")

    # Trim to requested number of days, then build all new columns via assign
    max_hours = days * 24
    init_ts = wind_fcst["initstamp"]
    init_dt = datetime.fromtimestamp(init_ts, tz=timezone.utc)

    df = merged[merged["hour_offset"] <= max_hours].reset_index(drop=True)
    df.loc[:, "forecast_datetime"] = df["hour_offset"].apply(
        lambda h: (init_dt + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
    )
    df.loc[:, "station_id"] = id_spot
    df.loc[:, "station_name"] = "Tel-Aviv"  # static for now; extend when adding more stations
    df = df[[
        "forecast_datetime",
        "wind_speed", "gust_speed", "wind_dir",
        "swell_height", "swell_period", "swell_dir",
        "station_id", "station_name",
    ]]

    print(f"✅ Scraped {len(df)} forecast rows for station {id_spot}")
    return df


if __name__ == "__main__":
    df = scrape_windguru()
    print(df.head(10).to_string())
    print(f"\nShape: {df.shape}")
    print(f"Date range: {df['forecast_datetime'].iloc[0]} → {df['forecast_datetime'].iloc[-1]}")
