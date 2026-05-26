"""Read a Strava bulk export `activities.csv`.

The bulk export schema is wide (~90 columns) and has duplicate column names
("Distance", "Elapsed Time", "Max Heart Rate" appear twice — the first set is
the summary view, the second set is computed from the FIT file). We use
csv.DictReader and prefer the *last* value when duplicates exist (DictReader
behaviour: later columns overwrite earlier ones with the same name).

Distance in the second set is in METERS; the first is in km. We use the
second (meters) and convert. This is documented but not obvious from the file.

Reference: https://www.strava.com/athlete/delete_your_account → bulk export
yields a folder; `activities.csv` is the index.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterator

from trainingplan.activity import Activity, sport_from_strava_type


# Strava's "Activity Date" format in the export, e.g. "May 21, 2026, 1:12:53 PM"
_DATE_FMT = "%b %d, %Y, %I:%M:%S %p"


def _to_float(s: str | None) -> float | None:
    if s is None or s == "" or s == "--":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _to_int(s: str | None) -> int | None:
    v = _to_float(s)
    return int(v) if v is not None else None


def load_activities(csv_path: Path) -> list[Activity]:
    """Load all activities from a Strava bulk-export CSV.

    Returns a list of Activity records sourced as `strava_export`. The
    Strava Activity ID is the stable dedup key.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Strava export not found at {csv_path}")

    out: list[Activity] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                a = _row_to_activity(row)
            except Exception as e:
                # Don't let one bad row kill the whole import; just skip with a note.
                print(f"  [strava] skipping row: {e}")
                continue
            if a is not None:
                out.append(a)
    return out


def _row_to_activity(row: dict) -> Activity | None:
    activity_id = (row.get("Activity ID") or "").strip()
    if not activity_id:
        return None

    raw_date = row.get("Activity Date", "")
    try:
        dt = datetime.strptime(raw_date, _DATE_FMT)
    except ValueError:
        # Some exports include UTC offset suffixes; try a couple of fallbacks.
        try:
            dt = datetime.fromisoformat(raw_date)
        except Exception:
            return None

    activity_type = row.get("Activity Type", "")
    sport = sport_from_strava_type(activity_type)

    # Distance: when the column appears twice, DictReader returns the LAST value
    # only (later same-named columns overwrite earlier ones). The last "Distance"
    # in the bulk export is meters; convert to km.
    dist_m = _to_float(row.get("Distance"))
    distance_km = (dist_m or 0.0) / 1000.0 if (dist_m and dist_m > 100) else (dist_m or 0.0)
    # Heuristic: if the value is <100, it was already in km (some exports differ);
    # otherwise treat as meters. Walking/short rides rarely exceed 100 km, never
    # 100 m, so this disambiguates cleanly.

    elapsed_sec = _to_float(row.get("Elapsed Time")) or 0.0
    moving_sec = _to_float(row.get("Moving Time")) or elapsed_sec

    a = Activity(
        source="strava_export",
        source_id=activity_id,
        start_time_local=dt.isoformat(timespec="seconds"),
        date=dt.date().isoformat(),
        sport=sport,
        name=(row.get("Activity Name") or "").strip(),
        description=(row.get("Activity Description") or "").strip(),
        duration_min=round(moving_sec / 60.0, 2),
        elapsed_min=round(elapsed_sec / 60.0, 2),
        distance_km=round(distance_km, 3),
        avg_hr=_to_int(row.get("Average Heart Rate")),
        max_hr=_to_int(row.get("Max Heart Rate")),
        elevation_gain_m=_to_float(row.get("Elevation Gain")) or 0.0,
        avg_power_w=_to_float(row.get("Average Watts")),
        avg_pace_sec_per_km=_pace_from_speed_mps(_to_float(row.get("Average Speed"))),
        perceived_effort=_to_int(row.get("Perceived Exertion")),
        temp_c=_to_float(row.get("Weather Temperature")) or _to_float(row.get("Average Temperature")),
        raw={"activity_type": activity_type, "filename": row.get("Filename")},
    )
    return a


def _pace_from_speed_mps(speed: float | None) -> float | None:
    """Average Speed is in m/s in the Strava export. Convert to sec/km for running."""
    if not speed or speed <= 0:
        return None
    return round(1000.0 / speed, 1)
