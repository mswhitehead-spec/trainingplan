"""Per-session analysis — actual vs planned deltas, HR drift, plain verdict.

Inputs
------
  - session: a plan session dict (with `targets` and now-filled `actual`)
  - hr_stream (optional): list of (elapsed_sec, hr_bpm) tuples from the Strava
    API `streams` endpoint. CSV imports don't supply this, so most calls will
    pass None and drift will be reported as unavailable.

Output
------
  An `analysis` dict suitable to drop into `session["analysis"]`. Includes:
    - duration_delta_min / duration_pct
    - distance_delta_km / distance_pct
    - hr_zone_status: in_zone | above | below | unknown
    - hr_avg_actual, hr_avg_target
    - elevation_delta_m
    - hr_drift_pct (or None)
    - verdict (single sentence, human)
    - flags (list of short tags useful to the adaptation layer)

Design rule: this module surfaces data; it does not propose plan changes.
That's the adaptation layer's job (STEP 5).
"""

from __future__ import annotations

from datetime import datetime
from statistics import fmean
from typing import Iterable


# Tolerances — used by verdict logic.
DURATION_OK_BAND = 0.10        # within ±10% of target duration is "on target"
DURATION_SHORT_THRESH = 0.80   # below 80% → "cut short"
DURATION_LONG_THRESH = 1.20    # above 120% → "exceeded target"

HR_DRIFT_CLEAN = 5.0           # ≤5% drift = clean aerobic
HR_DRIFT_HIGH = 8.0            # >8% = fatigue signal

# Session types where comparing the SESSION-AVERAGE pace against the target
# range is meaningful. Tempo/intervals/openers carry the WORK-rep pace in
# their target, which the session average never matches (warmup/cooldown),
# so they're excluded — check the laps in Strava instead.
PACE_CHECK_TYPES = {"easy_run", "easy_endurance", "endurance_z2",
                    "long_endurance", "recovery", "race"}


def _pace_to_sec(p: str) -> int | None:
    """'5:40' -> 340 seconds. None on anything malformed."""
    try:
        m, s = str(p).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def _sec_to_pace(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def pace_status(avg_pace_sec: float | None, target_range: list | None,
                session_type: str) -> str:
    """Classify session-avg pace vs the target [fast, slow] range.

    Returns 'faster' | 'in_range' | 'slower' | 'unknown'. Note the range is
    stored fast-bound first ('5:40', '6:10'); lower seconds = faster.
    """
    if session_type not in PACE_CHECK_TYPES:
        return "unknown"
    if avg_pace_sec is None or not target_range or len(target_range) != 2:
        return "unknown"
    fast = _pace_to_sec(target_range[0])
    slow = _pace_to_sec(target_range[1])
    if fast is None or slow is None:
        return "unknown"
    if avg_pace_sec < fast:
        return "faster"
    if avg_pace_sec > slow:
        return "slower"
    return "in_range"


def _pct(numer: float, denom: float) -> float | None:
    if denom in (0, None):
        return None
    return round(100.0 * numer / denom, 1)


def hr_zone_status(avg_hr: int | None, target_range: list[int] | None) -> str:
    """Classify the session avg HR against the target [low, high] range."""
    if avg_hr is None or not target_range or len(target_range) != 2:
        return "unknown"
    lo, hi = target_range
    if avg_hr < lo:
        return "below"
    if avg_hr > hi:
        return "above"
    return "in_zone"


def hr_drift_pct(stream: Iterable[tuple[float, int]] | None) -> float | None:
    """Aerobic-decoupling proxy from a HR time series.

    Convention used widely in endurance coaching (Friel, Maffetone):

        drift = (mean HR of 2nd half) / (mean HR of 1st half) − 1

    in percent. A "clean" steady-state ride is <5%; >8% is a fatigue signal.

    Slightly more discriminating variant we use: compare the *2nd quartile*
    (after warm-up) to the *4th quartile* (final). This skips the warm-up,
    which otherwise depresses the 1st-half mean and inflates drift.

    Returns None if the stream is too short or missing.
    """
    if not stream:
        return None
    samples = [hr for _, hr in stream if hr]
    if len(samples) < 60:   # less than a minute of data → can't say anything
        return None

    n = len(samples)
    q = n // 4
    if q < 10:
        return None
    second_quartile = samples[q : 2 * q]
    fourth_quartile = samples[3 * q :]
    a = fmean(second_quartile)
    b = fmean(fourth_quartile)
    if a == 0:
        return None
    return round(100.0 * (b / a - 1.0), 1)


def _verdict(analysis: dict, session_type: str) -> str:
    """One-sentence summary based on the computed deltas."""
    flags = analysis.get("flags", [])

    if "substitute" in flags:
        sub_sport = analysis.get("substitute_sport", "different sport")
        planned = analysis.get("planned_discipline", "planned discipline")
        return (f"substituted {sub_sport} for {planned} — counts as training, "
                f"but not the planned stimulus.")

    if "no_target" in flags:
        return "completed (no quantitative targets to compare against)."

    if "duration_short" in flags:
        return "session cut short of target duration."
    if "duration_long" in flags:
        return "exceeded target duration."

    # Easy days run too fast is the classic masters mistake — call it out
    # even when everything else looks fine.
    if "pace_fast" in flags and session_type in {
        "easy_run", "easy_endurance", "recovery", "long_endurance",
        "endurance_z2",
    }:
        return ("faster than the target pace range — easy days protect the "
                "quality days; save it for Tuesday.")
    if "pace_slow" in flags and session_type == "race":
        return "slower than the target pace range."

    if "drift_high" in flags:
        return "HR drift high — fatigue signal; consider lighter next session."
    if "hr_above" in flags:
        return "avg HR above target zone — worked harder than planned."
    if "hr_below" in flags:
        # below-target HR is good for taper/recovery, possibly concerning otherwise
        if session_type in {"recovery", "easy_endurance", "easy_run", "openers"}:
            return "easy and controlled — exactly right."
        return "avg HR below target zone — may have run easy when a stimulus was planned."

    return "on target."


def analyze_session(
    session: dict,
    hr_stream: Iterable[tuple[float, int]] | None = None,
    now: datetime | None = None,
) -> dict:
    """Compute an analysis dict for a single completed session.

    Assumes session['actual'] is filled in. If it isn't, returns a minimal
    analysis with a flag.
    """
    now = now or datetime.now()
    actual = session.get("actual")
    if not actual:
        return {
            "computed_at": now.isoformat(timespec="seconds"),
            "verdict": "no actual data — can't analyze.",
            "flags": ["no_actual"],
        }

    targets = session.get("targets") or {}
    flags: list[str] = []

    # Detect substitute: actual sport disagrees with planned discipline.
    # Import locally — match.py doesn't depend on analyze, so no cycle.
    from .match import is_substitute as _is_substitute
    is_sub = _is_substitute(session)
    actual_sport = actual.get("sport")
    planned_disc = session.get("discipline")
    if is_sub:
        flags.append("substitute")

    # Duration deltas (None target → no deltas).
    target_dur = targets.get("duration_min")
    actual_dur = actual.get("duration_min", 0.0)
    if target_dur:
        dur_delta = round(actual_dur - target_dur, 1)
        dur_pct = _pct(actual_dur, target_dur)
        if dur_pct is not None:
            if dur_pct < DURATION_SHORT_THRESH * 100:
                flags.append("duration_short")
            elif dur_pct > DURATION_LONG_THRESH * 100:
                flags.append("duration_long")
    else:
        dur_delta = None
        dur_pct = None

    # Distance deltas. Some session targets use distance_km, some use a min.
    target_dist = targets.get("distance_km") or targets.get("distance_km_min")
    actual_dist = actual.get("distance_km", 0.0)
    if target_dist:
        dist_delta = round(actual_dist - target_dist, 2)
        dist_pct = _pct(actual_dist, target_dist)
    else:
        dist_delta = None
        dist_pct = None

    # HR vs target zone.
    hr_target = targets.get("avg_hr_range")
    hr_actual = actual.get("avg_hr")
    hr_status = hr_zone_status(hr_actual, hr_target)
    if hr_status == "above":
        flags.append("hr_above")
    elif hr_status == "below":
        flags.append("hr_below")

    # Pace vs target range (running; steady session types only).
    pace_target = targets.get("pace_range_min_per_km")
    pace_actual_sec = actual.get("avg_pace_sec_per_km")
    p_status = pace_status(pace_actual_sec, pace_target,
                           session.get("type", ""))
    if p_status == "faster":
        flags.append("pace_fast")
    elif p_status == "slower":
        flags.append("pace_slow")

    # Elevation.
    target_elev = targets.get("elevation_gain_m")
    actual_elev = actual.get("elevation_gain_m")
    if target_elev and actual_elev is not None:
        elev_delta = round(actual_elev - target_elev, 0)
    else:
        elev_delta = None

    # HR drift.
    drift = hr_drift_pct(hr_stream) if hr_stream else None
    if drift is not None and drift > HR_DRIFT_HIGH:
        flags.append("drift_high")
    elif drift is not None and drift <= HR_DRIFT_CLEAN:
        flags.append("drift_clean")

    # No targets at all → mark it; verdict logic uses this.
    if not targets:
        flags.append("no_target")

    analysis = {
        "computed_at": now.isoformat(timespec="seconds"),
        "duration_delta_min": dur_delta,
        "duration_pct": dur_pct,
        "distance_delta_km": dist_delta,
        "distance_pct": dist_pct,
        "hr_zone_status": hr_status,
        "hr_avg_actual": hr_actual,
        "hr_avg_target": list(hr_target) if hr_target else None,
        "pace_status": p_status,
        "pace_avg_actual": (_sec_to_pace(pace_actual_sec)
                            if pace_actual_sec else None),
        "pace_target": list(pace_target) if pace_target else None,
        "elevation_delta_m": elev_delta,
        "hr_drift_pct": drift,
        "flags": flags,
    }
    if is_sub:
        analysis["substitute_sport"] = actual_sport
        analysis["planned_discipline"] = planned_disc
    analysis["verdict"] = _verdict(analysis, session.get("type", ""))
    return analysis
