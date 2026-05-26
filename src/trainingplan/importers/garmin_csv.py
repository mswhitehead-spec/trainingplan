"""Read a Garmin Connect activities CSV export.

Garmin's website lets you export an "Activities" table from Garmin Connect
(Activities → Activities → Export CSV). The schema is narrower than Strava's
but covers the essentials. Missing values appear as "--".

There is no stable activity ID in the export, so we synthesize one from
(date, start_time, activity_type, distance) — stable enough to dedup across
imports, since Garmin doesn't re-edit past activities.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path

from trainingplan.activity import Activity, sport_from_garmin_type


def _clean(s: str | None) -> str:
    return "" if s is None or s == "--" else s.strip()


def _to_float(s: str | None) -> float | None:
    s = _clean(s)
    if not s:
        return None
    try:
        # Garmin uses comma-separated thousands in some locales ("3,702").
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_int(s: str | None) -> int | None:
    v = _to_float(s)
    return int(v) if v is not None else None


def _hms_to_minutes(s: str | None) -> float:
    """Convert 'HH:MM:SS' or 'MM:SS' or 'HH:MM:SS.s' to minutes."""
    s = _clean(s)
    if not s:
        return 0.0
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 60 + int(m) + float(sec) / 60.0
        if len(parts) == 2:
            m, sec = parts
            return int(m) + float(sec) / 60.0
    except ValueError:
        return 0.0
    return 0.0


def _pace_to_sec_per_km(s: str | None) -> float | None:
    """Convert 'M:SS' or 'MM:SS' pace string to seconds per km."""
    s = _clean(s)
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None
    return None


def load_activities(csv_path: Path) -> list[Activity]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Garmin CSV not found at {csv_path}")

    out: list[Activity] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        # utf-8-sig strips the BOM that Garmin's exports sometimes include.
        reader = csv.DictReader(f)
        for row in reader:
            try:
                a = _row_to_activity(row)
            except Exception as e:
                print(f"  [garmin] skipping row: {e}")
                continue
            if a is not None:
                out.append(a)
    return out


def _row_to_activity(row: dict) -> Activity | None:
    raw_type = _clean(row.get("Activity Type"))
    sport = sport_from_garmin_type(raw_type)

    raw_date = _clean(row.get("Date"))
    if not raw_date:
        return None
    try:
        dt = datetime.fromisoformat(raw_date)
    except ValueError:
        return None

    distance_km = _to_float(row.get("Distance")) or 0.0
    duration_min = _hms_to_minutes(row.get("Time"))
    moving_min = _hms_to_minutes(row.get("Moving Time")) or duration_min

    # Synthesize a stable id: hash of (date_iso, type, distance) to 12 hex chars.
    seed = f"{dt.isoformat()}|{raw_type}|{distance_km:.3f}"
    source_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

    a = Activity(
        source="garmin_csv",
        source_id=source_id,
        start_time_local=dt.isoformat(timespec="seconds"),
        date=dt.date().isoformat(),
        sport=sport,
        name=_clean(row.get("Title")),
        description="",
        duration_min=round(moving_min, 2),
        elapsed_min=round(duration_min, 2),
        distance_km=round(distance_km, 3),
        avg_hr=_to_int(row.get("Avg HR")),
        max_hr=_to_int(row.get("Max HR")),
        elevation_gain_m=_to_float(row.get("Total Ascent")) or 0.0,
        avg_power_w=_to_float(row.get("Avg Power")),
        avg_pace_sec_per_km=_pace_to_sec_per_km(row.get("Avg Pace")),
        perceived_effort=None,  # not in Garmin export
        temp_c=_to_float(row.get("Max Temp")),  # closest we have
        raw={"activity_type": raw_type},
    )
    return a
