"""
Google Sheets read/write helpers for Clarity Map.

Setup:
  1. Create a Google Cloud project, enable Sheets API + Drive API
  2. Create a service account, download the JSON key
  3. Share your spreadsheet with the service account email
  4. Set env vars:
       GOOGLE_CREDS  — full JSON content of the service account key
       GOOGLE_SHEET_ID — the ID from the spreadsheet URL
         (https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit)
"""

import json
import os
from datetime import datetime, timezone
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

COLUMNS = ["username", "submitted_at", "dive_datetime", "clarity_m", "beach", "depth_m", "lat", "lon", "delete_token"]
HEADER_ROW = COLUMNS  # row 1 of the sheet
BEACH_COL = COLUMNS.index("beach") + 1  # 1-based column index for gspread

WEATHER_COLUMNS = [
    "scrape_timestamp", "forecast_datetime",
    "wind_speed", "gust_speed", "wind_dir",
    "swell_height", "swell_period", "swell_dir",
    "station_id", "station_name",
]


@lru_cache(maxsize=1)
def _get_sheet():
    """Authenticate and return the first worksheet. Cached after first call."""
    creds_json = os.environ.get("GOOGLE_CREDS")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")

    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDS env var not set")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID env var not set")

    creds = Credentials.from_service_account_info(
        json.loads(creds_json), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    # Ensure header row exists and contains all expected columns
    existing = worksheet.row_values(1)
    if not existing:
        worksheet.insert_row(HEADER_ROW, index=1)
    else:
        # Add any missing columns to the end (schema migration, safe for existing sheets)
        for col in HEADER_ROW:
            if col not in existing:
                worksheet.update_cell(1, len(existing) + 1, col)
                existing.append(col)

    return worksheet


def get_all_reports() -> list[dict]:
    """Return all reports as a list of dicts."""
    sheet = _get_sheet()
    records = sheet.get_all_records()  # uses row 1 as keys
    return records


def save_report(
    username: str,
    submitted_at: str,
    dive_datetime: str,
    clarity_m: float,
    beach: str,
    depth_m: float,
    lat: float,
    lon: float,
    delete_token: str,
) -> None:
    """Append a new report row to the sheet."""
    sheet = _get_sheet()
    row = [
        username,
        submitted_at,
        dive_datetime,
        clarity_m,
        beach,
        depth_m,
        lat,
        lon,
        delete_token,
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")


def delete_report(submitted_at: str, delete_token: str) -> bool:
    """Delete a report row by submitted_at + delete_token. Returns True if deleted."""
    sheet = _get_sheet()
    rows = sheet.get_all_values()
    if not rows:
        return False
    header = rows[0]
    try:
        sat_i = header.index("submitted_at")
        tok_i = header.index("delete_token")
    except ValueError:
        return False
    for i, row in enumerate(rows[1:], start=2):
        row_sat = row[sat_i] if len(row) > sat_i else ""
        row_tok = row[tok_i] if len(row) > tok_i else ""
        if row_sat == submitted_at and row_tok == delete_token and row_tok != "":
            sheet.delete_rows(i)
            return True
    return False


def _get_weather_sheet():
    """Return (and lazily create) the windguru_forecasts worksheet."""
    from dotenv import load_dotenv
    load_dotenv()
    creds_json = os.environ.get("GOOGLE_CREDS")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")

    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDS env var not set")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID env var not set")

    creds = Credentials.from_service_account_info(
        json.loads(creds_json), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)

    titles = [ws.title for ws in spreadsheet.worksheets()]
    if "windguru_forecasts" not in titles:
        ws = spreadsheet.add_worksheet(title="windguru_forecasts", rows=10000, cols=len(WEATHER_COLUMNS))
        ws.append_row(WEATHER_COLUMNS)
    else:
        ws = spreadsheet.worksheet("windguru_forecasts")

    return ws


def append_weather_rows(rows: list[dict]) -> None:
    """Append weather forecast rows to the windguru_forecasts worksheet (batched)."""
    ws = _get_weather_sheet()
    values = [[row.get(col, "") for col in WEATHER_COLUMNS] for row in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")


def update_rows_beach(updates: list[tuple[int, str]]) -> None:
    """Update the beach column for given rows. updates = [(sheet_row_index, new_name), ...]"""
    sheet = _get_sheet()
    for row_i, name in updates:
        sheet.update_cell(row_i, BEACH_COL, name)


# --- Quick self-test ---
if __name__ == "__main__":
    print("Writing test row...")
    save_report(
        username="test_diver",
        dive_datetime="2024-01-01T10:00:00",
        clarity_m=20,
        beach="Achziv",
        depth_m=15,
        lat=33.05,
        lon=35.085,
    )
    print("Reading back all reports...")
    reports = get_all_reports()
    print(f"Total rows: {len(reports)}")
    print(f"Last row: {reports[-1]}")
