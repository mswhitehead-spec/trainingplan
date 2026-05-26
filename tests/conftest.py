"""Shared pytest fixtures + sys.path shim so `import trainingplan` works."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Add src/ to the import path so tests don't need an editable install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.activity import Activity   # noqa: E402  (after sys.path tweak)


# ----- Activity fixtures ---------------------------------------------------

def _activity(
    *,
    sid: str,
    sport: str,
    iso_dt: str,
    duration_min: float = 60.0,
    distance_km: float = 20.0,
    avg_hr: int | None = 130,
    max_hr: int | None = 150,
    elevation_gain_m: float = 100.0,
    source: str = "strava_export",
) -> Activity:
    return Activity(
        source=source,
        source_id=sid,
        start_time_local=iso_dt,
        date=iso_dt[:10],
        sport=sport,
        duration_min=duration_min,
        elapsed_min=duration_min,
        distance_km=distance_km,
        avg_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
    )


@pytest.fixture
def act_ride_may25() -> Activity:
    return _activity(sid="A1", sport="cycling", iso_dt="2026-05-25T09:00:00",
                     duration_min=47.0, distance_km=18.0, avg_hr=128)


@pytest.fixture
def act_ride_may30() -> Activity:
    """The big planned long ride day — 240 min target, here we do 245."""
    return _activity(sid="A2", sport="cycling", iso_dt="2026-05-30T08:30:00",
                     duration_min=245.0, distance_km=82.0, avg_hr=132,
                     elevation_gain_m=650.0)


@pytest.fixture
def act_run_may26_actual_on_may27() -> Activity:
    """Run for Tue 2026-05-26 that actually happened Wed early morning — ±1d match."""
    return _activity(sid="A3", sport="running", iso_dt="2026-05-27T06:15:00",
                     duration_min=32.0, distance_km=5.2, avg_hr=140)


# ----- Plan fixture (minimal, 3-session) -----------------------------------

@pytest.fixture
def mini_plan() -> dict:
    return {
        "athlete": {"name": "Test", "age": 51, "max_hr": 168, "resting_hr": 50},
        "events": [{"name": "Race", "date": "2026-06-12", "priority": "A"}],
        "block": {"name": "test"},
        "sessions": [
            {
                "id": "2026-05-25_mon_easy-spin",
                "date": "2026-05-25",
                "discipline": "cycling",
                "type": "easy_endurance",
                "targets": {
                    "duration_min": 45,
                    "avg_hr_zone": "Z2",
                    "avg_hr_range": [121, 133],
                },
                "notes": "easy",
                "status": "planned",
                "actual": None,
                "analysis": None,
                "adaptations": [],
            },
            {
                "id": "2026-05-26_tue_easy-run",
                "date": "2026-05-26",
                "discipline": "running",
                "type": "easy_run",
                "targets": {
                    "duration_min": 30,
                    "distance_km": 5,
                    "avg_hr_zone": "Z2",
                    "avg_hr_range": [121, 133],
                },
                "notes": "easy",
                "status": "planned",
                "actual": None,
                "analysis": None,
                "adaptations": [],
            },
            {
                "id": "2026-05-30_sat_long-ride",
                "date": "2026-05-30",
                "discipline": "cycling",
                "type": "long_endurance",
                "targets": {
                    "duration_min": 240,
                    "distance_km": 80,
                    "avg_hr_zone": "Z2",
                    "avg_hr_range": [121, 133],
                    "elevation_gain_m": 600,
                },
                "notes": "key session",
                "status": "planned",
                "actual": None,
                "analysis": None,
                "adaptations": [],
            },
        ],
    }


@pytest.fixture
def today_jun01() -> date:
    """A 'today' value that puts all three mini_plan sessions in the past."""
    return date(2026, 6, 1)
