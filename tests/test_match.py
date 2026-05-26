"""Tests for src/trainingplan/match.py."""

from __future__ import annotations

from datetime import date

import pytest

from trainingplan.match import (
    actual_from_activity,
    is_substitute,
    mark_missed_past_sessions,
    match_activities_to_sessions,
)


def test_exact_date_match(mini_plan, act_ride_may25, today_jun01):
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [act_ride_may25], today=today_jun01
    )
    # 3 sessions, 1 activity — the cycling one on 2026-05-25 should match the spin.
    by_id = {m.session_id: m for m in matches}
    spin = by_id["2026-05-25_mon_easy-spin"]
    assert spin.activity is act_ride_may25
    assert spin.date_diff_days == 0


def test_one_day_window(mini_plan, act_run_may26_actual_on_may27, today_jun01):
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [act_run_may26_actual_on_may27], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    run = by_id["2026-05-26_tue_easy-run"]
    assert run.activity is act_run_may26_actual_on_may27
    assert run.date_diff_days == 1   # activity is one day after the session


def test_sport_mismatch_becomes_substitute(mini_plan, act_ride_may25, today_jun01):
    """When a same-date activity is a different sport, it matches as a substitute
    (status stays completed, but actual.sport disagrees with planned discipline)."""
    plan = mini_plan
    plan["sessions"][0]["discipline"] = "running"   # was cycling
    matches = match_activities_to_sessions(
        plan["sessions"], [act_ride_may25], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    m = by_id["2026-05-25_mon_easy-spin"]
    assert m.activity is act_ride_may25
    assert "substitute" in m.notes
    # And the is_substitute helper agrees once actual is filled in.
    session = plan["sessions"][0]
    session["actual"] = actual_from_activity(act_ride_may25)
    assert is_substitute(session) is True


def test_substitute_requires_minimum_duration(mini_plan, today_jun01):
    """A way-too-short cross-sport activity does NOT count as a substitute."""
    from tests.conftest import _activity   # type: ignore
    plan = mini_plan
    plan["sessions"][0]["discipline"] = "running"   # was cycling, target 45 min
    tiny = _activity(sid="TINY", sport="cycling",
                     iso_dt="2026-05-25T09:00:00",
                     duration_min=5.0, distance_km=1.0)
    matches = match_activities_to_sessions(
        plan["sessions"], [tiny], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    # 5 min < 50% of 45 min planned → not a substitute.
    assert by_id["2026-05-25_mon_easy-spin"].activity is None


@pytest.mark.parametrize("planned_disc,actual_sport", [
    # Each row: planned discipline (a) doesn't equal actual sport (b),
    # so the substitute pass should match across any sport pairing.
    ("cycling", "running"),
    ("cycling", "swimming"),
    ("cycling", "strength"),
    ("cycling", "walking"),
    ("cycling", "other"),       # kayaking, rowing, climbing, …
    ("running", "cycling"),
    ("running", "swimming"),
    ("running", "strength"),
    ("running", "other"),
    ("swimming", "cycling"),
    ("strength", "running"),
])
def test_any_sport_substitutes_for_any_other_sport(
    today_jun01, planned_disc, actual_sport
):
    """The substitute pass triggers regardless of which sport was logged —
    swimming, weights, kayaking ('other'), hiking, anything. As long as it's
    not the planned discipline and meets the duration floor, it matches.

    Uses a minimal single-session plan to avoid the strict pass consuming the
    activity for a different session that happens to match the actual sport.
    """
    from tests.conftest import _activity   # type: ignore
    plan = {
        "athlete": {"name": "T", "age": 51, "max_hr": 168, "resting_hr": 50},
        "events": [{"name": "R", "date": "2026-06-12", "priority": "A"}],
        "block": {"name": "t"},
        "sessions": [{
            "id": "2026-05-25_subtest",
            "date": "2026-05-25",
            "discipline": planned_disc,
            "type": "easy_endurance",
            "targets": {"duration_min": 45},
            "notes": "",
            "status": "planned",
            "actual": None,
            "analysis": None,
            "adaptations": [],
        }],
    }
    act = _activity(sid="X", sport=actual_sport,
                    iso_dt="2026-05-25T09:00:00",
                    duration_min=45.0, distance_km=10.0)
    matches = match_activities_to_sessions(
        plan["sessions"], [act], today=today_jun01
    )
    m = matches[0]
    assert m.activity is act, f"{actual_sport} should substitute for {planned_disc}"
    assert "substitute" in m.notes


def test_substitute_does_not_steal_from_strict_match(mini_plan, today_jun01):
    """If the strict-sport match exists, it wins; substitutes are pass-2 only."""
    from tests.conftest import _activity   # type: ignore
    plan = mini_plan
    # Plan session 0 is cycling; supply BOTH a strict cycling match and a
    # cross-sport activity on the same date.
    ride = _activity(sid="RIDE", sport="cycling",
                     iso_dt="2026-05-25T09:00:00",
                     duration_min=45.0, distance_km=15.0)
    swim = _activity(sid="SWIM", sport="swimming",
                     iso_dt="2026-05-25T11:00:00",
                     duration_min=60.0, distance_km=2.0)
    matches = match_activities_to_sessions(
        plan["sessions"], [ride, swim], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    m = by_id["2026-05-25_mon_easy-spin"]
    # Strict match wins; substitute pass is skipped for this session.
    assert m.activity is ride
    assert "substitute" not in m.notes


def test_activity_consumed_only_once(mini_plan, act_ride_may25, today_jun01):
    """Two cycling sessions, one activity — only the closer one should win."""
    plan = mini_plan
    # Duplicate the long-ride into 2026-05-26 so two cycling sessions exist
    # within range of act_ride_may25.
    extra = dict(plan["sessions"][0])
    extra["id"] = "2026-05-26_wed_extra-cycling"
    extra["date"] = "2026-05-26"
    plan["sessions"].insert(1, extra)

    matches = match_activities_to_sessions(
        plan["sessions"], [act_ride_may25], today=today_jun01
    )
    matched = [m for m in matches if m.activity is not None]
    assert len(matched) == 1
    assert matched[0].session_id == "2026-05-25_mon_easy-spin"   # the same-day session wins


def test_two_candidates_same_day_pick_closer_duration(mini_plan, today_jun01):
    """Two cycling activities on 2026-05-30 — one is way longer than target,
    the other is closer to the 240-min target. Closer-to-target wins."""
    from tests.conftest import _activity   # type: ignore
    too_short = _activity(sid="S", sport="cycling",
                          iso_dt="2026-05-30T06:00:00",
                          duration_min=60.0, distance_km=20.0)
    close = _activity(sid="C", sport="cycling",
                      iso_dt="2026-05-30T08:00:00",
                      duration_min=235.0, distance_km=80.0)
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [too_short, close], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    long_ride = by_id["2026-05-30_sat_long-ride"]
    assert long_ride.activity is close
    spin = by_id["2026-05-25_mon_easy-spin"]
    # The 60-min ride is within ±1 day of nothing else cycling.
    # It's not within ±1 day of 05-25 either (05-30 vs 05-25 = 5 days).
    assert spin.activity is None


def test_missed_session_flagged_for_past_dates(mini_plan):
    """Run match with no activities; then mark past sessions missed."""
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [], today=date(2026, 6, 1)
    )
    assert all(m.activity is None for m in matches)
    flipped = mark_missed_past_sessions(mini_plan["sessions"], today=date(2026, 6, 1))
    assert flipped == 3
    assert all(s["status"] == "missed" for s in mini_plan["sessions"])


def test_completed_sessions_skipped(mini_plan, act_ride_may25, today_jun01):
    """A session already `completed` should not be re-matched."""
    mini_plan["sessions"][0]["status"] = "completed"
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [act_ride_may25], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    assert "2026-05-25_mon_easy-spin" not in by_id   # not in matchable set


def test_rest_session_never_matches(mini_plan, today_jun01):
    """A rest-discipline session is not eligible for matching."""
    mini_plan["sessions"][0]["discipline"] = "rest"
    mini_plan["sessions"][0]["type"] = "rest"
    matches = match_activities_to_sessions(
        mini_plan["sessions"], [], today=today_jun01
    )
    by_id = {m.session_id: m for m in matches}
    assert "2026-05-25_mon_easy-spin" not in by_id


def test_actual_from_activity_shape(act_ride_may30):
    actual = actual_from_activity(act_ride_may30)
    # The keys downstream code reads must all be present.
    for k in ("source", "source_id", "duration_min", "distance_km",
              "avg_hr", "max_hr", "elevation_gain_m"):
        assert k in actual
    assert actual["duration_min"] == 245.0
    assert actual["distance_km"] == 82.0
