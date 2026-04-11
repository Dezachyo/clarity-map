#!/usr/bin/env python3
"""
Re-snap old reports to the current beach list based on stored lat/lon.

Usage:
  python migrate_beaches.py           # dry run — shows what would change
  python migrate_beaches.py --apply   # writes changes to the sheet
"""

import sys
from dotenv import load_dotenv
load_dotenv()

import geo
import sheets


def main():
    apply = "--apply" in sys.argv
    sheet = sheets._get_sheet()
    rows = sheet.get_all_values()  # row 0 = header, all subsequent = data

    if not rows:
        print("Sheet is empty.")
        return

    header = rows[0]
    try:
        lat_i   = header.index("lat")
        lon_i   = header.index("lon")
        beach_i = header.index("beach")
    except ValueError as e:
        print(f"Missing expected column: {e}")
        sys.exit(1)

    changes = []  # (sheet_row_1based, old_name, new_name)

    for i, row in enumerate(rows[1:], start=2):  # sheet rows are 1-based, data starts at row 2
        try:
            lat = float(row[lat_i])
            lon = float(row[lon_i])
        except (ValueError, IndexError):
            continue
        old_name = row[beach_i] if len(row) > beach_i else ""
        new_name = geo.nearest_beach(lat, lon)["name"]
        if old_name != new_name:
            changes.append((i, old_name, new_name))

    if not changes:
        print("All rows already match current beach list. Nothing to do.")
        return

    print(f"{'Row':<5} {'Old beach':<30} {'New beach':<30}")
    print("-" * 67)
    for row_i, old, new in changes:
        print(f"{row_i:<5} {old:<30} {new:<30}")
    print(f"\n{len(changes)} row(s) would be updated.")

    if apply:
        sheets.update_rows_beach([(row_i, new) for row_i, _, new in changes])
        print("Done — sheet updated.")
    else:
        print("\nRun with --apply to write changes.")


if __name__ == "__main__":
    main()
