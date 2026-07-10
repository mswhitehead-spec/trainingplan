"""Tests for src/trainingplan/analyze.py."""

from __future__ import annotations

import pytest

from trainingplan.analyze import (
    HR_DRIFT_HIGH,
    analyze_session,
    hr_drift_pct,
    hr_zone_status,
)
from trainingplan.match import actual_from_activity


# ----- hr_zone_status ------------------------------------------------------

def test_hr_zone_in_zone():
    assert hr_zone_status(130, [121, 133]) == "in_zone"


def test_hr_zone_above():
    assert hr_zone_status(140, [121, 133]) == "above"


def test_hr_zone_below():
    assert hr_zone_status(118, [121, 133]) == "below"


def test_hr_zone_unknown_when_missing():
    assert hr_zone_status(None, [121, 133]) == "unknown"
    assert hr_zone_status(130, None) == "unknown"


# ----- hr_drift_pct --------------------------------------------------------

def test_hr_drift_none_for_no_stream():
    assert hr_drift_pct(None) is None
    assert hr_drift_pct([]) is None


def test_hr_drift_none_for_too_short():
    # 30 samples is below the 60-sample floor.
    assert hr_drift_pct([(i, 130) for i in range(30)]) is None


def test_hr_drift_clean_for_steady():
    """A flat 130-bpm signal should have ~0% drift."""
    stream = [(i, 130) for i in range(600)]   # 10 min @ 1 Hz
    assert abs(hr_drift_pct(stream) or 0.0) < 0.5


def test_hr_drift_detects_climb():
    """A steep ramp from 115 → 150 over 10 min produces a clearly high drift."""
    n = 600
    stream = [(i, int(115 + 35 * i / n)) for i in range(n)]
    drift = hr_drift_pct(stream)
    assert drift is not None
    # 2nd quartile mean ~125, 4th quartile mean ~146  →  ~16% drift, well above 8.
    assert drift > HR_DRIFT_HIGH


# ----- analyze_session, end to end -----------------------------------------

def test_analyze_easy_spin_on_target(mini_plan, act_ride_may25):
    s = mini_plan["sessions"][0]
    s["actual"] = actual_from_activity(act_ride_may25)
    a = analyze_session(s)

    assert a["hr_zone_status"] == "in_zone"
    assert a["duration_pct"] is not None
    assert 95 < a["duration_pct"] < 110
    assert "duration_short" not in a["flags"]
    assert "hr_above" not in a["flags"]
    assert a["verdict"] == "on target."


def test_analyze_long_ride_hot(mini_plan, act_ride_may30):
    s = mini_plan["sessions"][2]
    s["actual"] = actual_from_activity(act_ride_may30)
    a = analyze_session(s)

    assert a["hr_zone_status"] == "in_zone"   # 132 ∈ [121, 133]
    # Duration 245 vs target 240 → ~102%, on target.
    assert "duration_short" not in a["flags"]
    assert "duration_long" not in a["flags"]


def test_analyze_session_cut_short_flag():
    """Force a 50% duration outcome and see the flag/verdict."""
    s = {
        "id": "test_cut",
        "date": "2026-05-30",
        "discipline": "cycling",
        "type": "long_endurance",
        "targets": {"duration_min": 240, "avg_hr_range": [121, 133]},
        "actual": {
            "duration_min": 120,
            "distance_km": 40,
            "avg_hr": 130,
            "elevation_gain_m": 300,
        },
    }
    a = analyze_session(s)
    assert "duration_short" in a["flags"]
    assert a["verdict"].startswith("session cut short")


def test_analyze_session_high_drift_flag():
    s = {
        "id": "test_drift",
        "date": "2026-05-30",
        "discipline": "cycling",
        "type": "long_endurance",
        "targets": {"duration_min": 240, "avg_hr_range": [121, 133]},
        "actual": {"duration_min": 240, "distance_km": 80, "avg_hr": 130,
                   "elevation_gain_m": 600},
    }
    # Manufacture a steep drift stream: rises from 115 → 150 → ~16% drift.
    n = 600
    stream = [(i, int(115 + 35 * i / n)) for i in range(n)]
    a = analyze_session(s, hr_stream=stream)
    assert "drift_high" in a["flags"]
    assert "fatigue" in a["verdict"]


def test_analyze_no_actual_data():
    s = {"id": "x", "date": "2026-05-25", "discipline": "cycling", "type": "easy_endurance",
         "targets": {"duration_min": 45}, "actual": None}
    a = analyze_session(s)
    assert "no_actual" in a["flags"]


def test_analyze_no_targets_flag():
    """A session with empty targets (like rest day) should not crash and
    should produce a 'completed (no quantitative targets)' verdict."""
    s = {
        "id": "rest_walk",
        "date": "2026-05-31",
        "discipline": "walking",
        "type": "recovery",
        "targets": {},
        "actual": {"duration_min": 45, "distance_km": 4.0, "avg_hr": 95,
                   "elevation_gain_m": 10},
    }
    a = analyze_session(s)
    assert "no_target" in a["flags"]
    assert "no quantitative" in a["verdict"]


# ----- pace vs target range --------------------------------------------------

def test_pace_status_classification():
    from trainingplan.analyze import pace_status
    rng = ["5:40", "6:10"]  # fast bound first
    assert pace_status(330.0, rng, "easy_run") == "faster"    # 5:30
    assert pace_status(350.0, rng, "easy_run") == "in_range"  # 5:50
    assert pace_status(380.0, rng, "easy_run") == "slower"    # 6:20
    assert pace_status(None, rng, "easy_run") == "unknown"
    # Work-pace types are never judged on session average.
    assert pace_status(330.0, rng, "tempo") == "unknown"
    assert pace_status(330.0, rng, "intervals") == "unknown"


def test_easy_run_too_fast_verdict():
    from trainingplan.analyze import analyze_session
    session = {
        "type": "easy_run", "discipline": "running",
        "targets": {"duration_min": 35, "distance_km": 6,
                    "pace_range_min_per_km": ["5:40", "6:10"]},
        "actual": {"sport": "running", "duration_min": 33.0,
                   "distance_km": 6.0, "avg_hr": 138,
                   "avg_pace_sec_per_km": 315.0},   # 5:15 — too fast
    }
    analysis = analyze_session(session)
    assert "pace_fast" in analysis["flags"]
    assert "easy days" in analysis["verdict"]
    assert analysis["pace_avg_actual"] == "5:15"
