"""Tests for src/trainingplan/heuristics.py.

Each rule gets a positive case (fires when it should) and a negative case
(does not fire when it shouldn't), plus the no-data-no-crash edge.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from trainingplan.heuristics import (
    build_context,
    rule_frequent_missed_sessions,
    rule_hr_drift_high,
    rule_missed_long_no_makeup_short_window,
    rule_race_week_cap_intensity,
    rule_race_window_cap_long_duration,
    rule_two_hot_sessions,
)


# Race date for all the synthetic plans below.
RACE_DATE = "2026-06-12"


def _session(sid: str, date_str: str, *, discipline="cycling", type_="endurance_z2",
             status="planned", duration_min=60, distance_km=20,
             avg_hr_range=(121, 133), actual=None, analysis=None) -> dict:
    return {
        "id": sid,
        "date": date_str,
        "discipline": discipline,
        "type": type_,
        "targets": {
            "duration_min": duration_min,
            "distance_km": distance_km,
            "avg_hr_range": list(avg_hr_range),
        },
        "notes": "",
        "status": status,
        "actual": actual,
        "analysis": analysis,
        "adaptations": [],
    }


def _plan(*sessions: dict) -> dict:
    return {
        "athlete": {"name": "Test", "age": 51, "max_hr": 168, "resting_hr": 50},
        "events": [{
            "name": "Vätternrundan",
            "date": RACE_DATE,
            "discipline": "cycling",
            "priority": "A",
        }],
        "block": {"name": "test"},
        "sessions": list(sessions),
    }


# ----- rule_race_week_cap_intensity ----------------------------------------

def test_race_week_cap_intensity_fires_inside_window():
    plan = _plan(
        _session("s_intervals", "2026-06-10", type_="intervals"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 8))   # 4 days to race
    changes = rule_race_week_cap_intensity(ctx, {})
    assert len(changes) == 1
    assert changes[0].session_id == "s_intervals"
    assert changes[0].new_value == "easy_endurance"


def test_race_week_cap_intensity_no_fire_outside_window():
    plan = _plan(
        _session("s_intervals", "2026-06-10", type_="intervals"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 5, 25))   # 18 days to race
    changes = rule_race_week_cap_intensity(ctx, {})
    assert changes == []


def test_race_week_cap_intensity_skips_openers():
    plan = _plan(
        _session("s_openers", "2026-06-10", type_="openers"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 8))
    changes = rule_race_week_cap_intensity(ctx, {})
    assert changes == []   # openers are exempt


# ----- rule_race_window_cap_long_duration ---------------------------------

def test_race_window_cap_long_duration_fires():
    plan = _plan(
        _session("s_long", "2026-06-04", type_="long_endurance", duration_min=240),
        _session("s_race", RACE_DATE, type_="race", duration_min=840),
    )
    ctx = build_context(plan, today=date(2026, 6, 1))   # 11 days to race; inside 14d window
    changes = rule_race_window_cap_long_duration(
        ctx, {"window_days": 14, "max_long_duration_min": 180}
    )
    assert len(changes) == 1
    assert changes[0].session_id == "s_long"
    assert changes[0].new_value == 180
    assert changes[0].old_value == 240


def test_race_window_cap_long_duration_skips_race_itself():
    plan = _plan(_session("s_race", RACE_DATE, type_="race", duration_min=840))
    ctx = build_context(plan, today=date(2026, 6, 1))
    changes = rule_race_window_cap_long_duration(
        ctx, {"window_days": 14, "max_long_duration_min": 180}
    )
    assert changes == []   # race itself is exempt


def test_race_window_cap_long_duration_no_fire_outside_window():
    plan = _plan(
        _session("s_long", "2026-05-30", type_="long_endurance", duration_min=240),
        _session("s_race", RACE_DATE, type_="race", duration_min=840),
    )
    ctx = build_context(plan, today=date(2026, 5, 20))   # 23 days to race
    changes = rule_race_window_cap_long_duration(
        ctx, {"window_days": 14, "max_long_duration_min": 180}
    )
    assert changes == []


# ----- rule_missed_long_no_makeup_short_window ----------------------------

def test_missed_long_triggers_next_long_reduction():
    plan = _plan(
        # Missed last Saturday's long ride.
        _session("s_missed_long", "2026-05-30", type_="long_endurance",
                 duration_min=240, status="missed"),
        # A second long is planned next Saturday.
        _session("s_next_long", "2026-06-06", type_="long_endurance",
                 duration_min=150),
        _session("s_race", RACE_DATE, type_="race", duration_min=840),
    )
    ctx = build_context(plan, today=date(2026, 6, 2))   # 10 days to race
    changes = rule_missed_long_no_makeup_short_window(
        ctx, {"race_window_days": 21, "duration_reduction_pct": 10.0}
    )
    assert len(changes) == 1
    assert changes[0].session_id == "s_next_long"
    assert changes[0].new_value == 135   # 150 * 0.9


def test_missed_long_no_fire_when_no_upcoming_long():
    plan = _plan(
        _session("s_missed_long", "2026-05-30", type_="long_endurance",
                 duration_min=240, status="missed"),
        _session("s_race", RACE_DATE, type_="race", duration_min=840),
    )
    ctx = build_context(plan, today=date(2026, 6, 2))
    changes = rule_missed_long_no_makeup_short_window(
        ctx, {"race_window_days": 21, "duration_reduction_pct": 10.0}
    )
    assert changes == []


# ----- rule_two_hot_sessions ----------------------------------------------

def test_two_hot_sessions_fires_when_both_hot():
    hot_analysis = {"hr_zone_status": "above", "verdict": "hot"}
    plan = _plan(
        _session("s_hot_1", "2026-05-30", type_="long_endurance",
                 status="completed", actual={"avg_hr": 140}, analysis=hot_analysis),
        _session("s_hot_2", "2026-06-02", type_="endurance_z2",
                 status="completed", actual={"avg_hr": 138}, analysis=hot_analysis),
        _session("s_next_tempo", "2026-06-04", type_="tempo", duration_min=60),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 3))
    changes = rule_two_hot_sessions(ctx, {})
    assert len(changes) == 1
    assert changes[0].session_id == "s_next_tempo"
    assert changes[0].new_value == "easy_endurance"


def test_two_hot_sessions_no_fire_when_only_one_hot():
    hot = {"hr_zone_status": "above"}
    cold = {"hr_zone_status": "in_zone"}
    plan = _plan(
        _session("s_hot", "2026-05-30", status="completed",
                 actual={"avg_hr": 140}, analysis=hot),
        _session("s_normal", "2026-06-02", status="completed",
                 actual={"avg_hr": 128}, analysis=cold),
        _session("s_next_tempo", "2026-06-04", type_="tempo"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 3))
    changes = rule_two_hot_sessions(ctx, {})
    assert changes == []


# ----- rule_hr_drift_high --------------------------------------------------

def test_hr_drift_high_fires_when_recent_long_drifted():
    plan = _plan(
        _session("s_long_drifted", "2026-05-30", type_="long_endurance",
                 status="completed",
                 actual={"avg_hr": 132, "duration_min": 240},
                 analysis={"hr_drift_pct": 12.0, "hr_zone_status": "in_zone"}),
        _session("s_next_long", "2026-06-06", type_="long_endurance",
                 duration_min=150),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 2))
    changes = rule_hr_drift_high(
        ctx, {"drift_threshold_pct": 8.0, "duration_reduction_pct": 15.0}
    )
    assert len(changes) == 1
    assert changes[0].session_id == "s_next_long"
    # 150 * 0.85 = 127.5 → 128 rounded.
    assert changes[0].new_value == 128


def test_hr_drift_high_no_fire_when_drift_none():
    """Most current data has hr_drift_pct=None (no stream); rule must not fire."""
    plan = _plan(
        _session("s_long_no_drift", "2026-05-30", type_="long_endurance",
                 status="completed",
                 actual={"avg_hr": 132, "duration_min": 240},
                 analysis={"hr_drift_pct": None, "hr_zone_status": "in_zone"}),
        _session("s_next_long", "2026-06-06", type_="long_endurance",
                 duration_min=150),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 2))
    changes = rule_hr_drift_high(
        ctx, {"drift_threshold_pct": 8.0, "duration_reduction_pct": 15.0}
    )
    assert changes == []



# ----- rule_frequent_missed_sessions --------------------------------------

def test_frequent_missed_fires_when_three_misses_in_window():
    plan = _plan(
        _session("m1", "2026-06-01", status="missed"),
        _session("m2", "2026-06-03", status="missed"),
        _session("m3", "2026-06-05", status="missed"),
        _session("s_tempo", "2026-06-08", type_="tempo", duration_min=60),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 7))
    changes = rule_frequent_missed_sessions(
        ctx, {"missed_threshold": 3, "lookback_days": 7}
    )
    assert len(changes) == 1
    assert changes[0].session_id == "s_tempo"
    assert changes[0].new_value == "easy_endurance"


def test_frequent_missed_no_fire_below_threshold():
    plan = _plan(
        _session("m1", "2026-06-01", status="missed"),
        _session("m2", "2026-06-03", status="missed"),
        _session("s_tempo", "2026-06-08", type_="tempo"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 7))
    changes = rule_frequent_missed_sessions(
        ctx, {"missed_threshold": 3, "lookback_days": 7}
    )
    assert changes == []


def test_frequent_missed_ignores_old_misses_outside_lookback():
    plan = _plan(
        # Three misses but all before the 7-day lookback window.
        _session("m1", "2026-05-20", status="missed"),
        _session("m2", "2026-05-22", status="missed"),
        _session("m3", "2026-05-24", status="missed"),
        _session("s_tempo", "2026-06-08", type_="tempo"),
        _session("s_race", RACE_DATE, type_="race"),
    )
    ctx = build_context(plan, today=date(2026, 6, 5))
    changes = rule_frequent_missed_sessions(
        ctx, {"missed_threshold": 3, "lookback_days": 7}
    )
    assert changes == []
