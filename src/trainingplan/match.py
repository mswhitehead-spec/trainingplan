"""Match completed activities to planned sessions.

Algorithm (deliberately simple, greedy, deterministic):

  1. Walk sessions in (date asc, id asc) order.
  2. For each session with status in {planned, adjusted, missed} that has no
     `actual` yet, find activities of the matching sport whose date is
     within ±1 day of the session date.
  3. Among candidates, pick the best by:
        a) same-day beats ±1 day
        b) closer absolute date diff
        c) closer to the planned duration_min (if planned)
        d) longest activity (tie-break)
  4. Mark that activity as consumed so it can't match another session.
  5. SUBSTITUTE PASS: any past session still without a match that has an
     orphan activity on the same date (different sport, ≥50% of planned
     duration) is matched as a *substitute*. status stays `completed` but
     the actual.sport will differ from session.discipline — downstream code
     (analyze/summarize/email) checks for this and renders accordingly.
  6. Any session whose date is in the past and STILL has no match becomes
     status=missed.

Unmatched activities (truly orphan — no plan session anywhere within the
window) stay silent; inspect them via fetch.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .activity import Activity


# Map a plan discipline → set of allowed Activity.sport values.
# `rest` never matches an activity.
_DISCIPLINE_TO_SPORT: dict[str, set[str]] = {
    "cycling": {"cycling"},
    "running": {"running"},
    "strength": {"strength"},
    "walking": {"walking"},
    "swimming": {"swimming"},
    "rest": set(),
}

# Session statuses we'll attempt to match (re)against activities.
# `completed` is skipped — already done, leave alone.
_MATCHABLE_STATUSES = {"planned", "adjusted", "missed"}


@dataclass
class Match:
    session_id: str
    activity: Activity | None   # None means no match found
    date_diff_days: int         # 0 = same day; +1 = activity one day after session
    notes: str = ""             # human-readable reason / debug note


def _sport_matches(discipline: str, sport: str) -> bool:
    return sport in _DISCIPLINE_TO_SPORT.get(discipline, set())


def _candidate_score(
    session: dict,
    activity: Activity,
    session_dt: date,
    activity_dt: date,
) -> tuple:
    """Sort key — lower is better. (date diff, |duration delta|, -duration)."""
    diff = abs((activity_dt - session_dt).days)

    target = session.get("targets") or {}
    target_dur = target.get("duration_min")
    if target_dur:
        dur_delta = abs(activity.duration_min - target_dur)
    else:
        dur_delta = 0.0   # no target → don't prefer one duration over another

    # Negative duration → ties go to the longer activity (more substantive).
    return (diff, dur_delta, -activity.duration_min)


def match_activities_to_sessions(
    sessions: Iterable[dict],
    activities: Iterable[Activity],
    today: date | None = None,
    window_days: int = 1,
    substitute_min_ratio: float = 0.5,
) -> list[Match]:
    """Greedy match. Each activity matches at most one session.

    Pass 1: strict sport+date matching (within ±window_days).
    Pass 2: substitute matching — for past unmatched sessions, look for orphan
            activities on the same date (any sport) with duration ≥
            substitute_min_ratio * planned. This catches the case where the
            athlete trains, but with a different discipline than planned
            (e.g. swim instead of run on a rest-flexible easy day).

    Returns one Match per matchable session, in session-date order. Sessions
    that are already `completed` or that are rest days are skipped.
    """
    today = today or date.today()

    # Materialise the iterable once so we can walk it twice below.
    all_sessions = list(sessions)

    # Stable ordering — sessions earliest first, ties by id.
    sessions_sorted = sorted(
        (s for s in all_sessions if s.get("status", "planned") in _MATCHABLE_STATUSES
         and s.get("discipline") != "rest"),
        key=lambda s: (s["date"], s["id"]),
    )

    # Pre-consume activities already referenced by completed sessions.
    # Without this, a completed session's activity stays in the available
    # pool and can accidentally re-match a nearby session on the next cron run
    # (the ±1 day window means yesterday's activity is still a candidate today).
    pre_consumed: set[tuple[str, str]] = set()
    for s in all_sessions:
        if s.get("status") == "completed":
            act = s.get("actual") or {}
            src = act.get("source", "strava_api")
            src_id = act.get("source_id")
            if src_id:
                pre_consumed.add((src, str(src_id)))

    # Activities are indexed by (source, source_id) for quick consume.
    available: dict[tuple[str, str], Activity] = {
        (a.source, a.source_id): a for a in activities
        if (a.source, a.source_id) not in pre_consumed
    }

    matches: list[Match] = []
    for s in sessions_sorted:
        session_dt = date.fromisoformat(s["date"])
        disc = s.get("discipline", "")

        candidates: list[Activity] = []
        for a in available.values():
            if not _sport_matches(disc, a.sport):
                continue
            activity_dt = date.fromisoformat(a.date)
            if abs((activity_dt - session_dt).days) > window_days:
                continue
            candidates.append(a)

        if not candidates:
            # No strict match — leave for pass 2 / missed.
            matches.append(Match(
                session_id=s["id"],
                activity=None,
                date_diff_days=0,
                notes="no candidate activity within window",
            ))
            continue

        # Pick the best candidate.
        best = min(
            candidates,
            key=lambda a: _candidate_score(s, a, session_dt, date.fromisoformat(a.date)),
        )
        diff_days = (date.fromisoformat(best.date) - session_dt).days
        matches.append(Match(
            session_id=s["id"],
            activity=best,
            date_diff_days=diff_days,
            notes="matched" + (f" (±{abs(diff_days)}d)" if diff_days != 0 else ""),
        ))

        # Consume the activity so it can't match another session.
        del available[(best.source, best.source_id)]

    # ----- Pass 2: substitute matching ------------------------------------
    # For each past-or-today unmatched session, look for an orphan activity on
    # the SAME date (regardless of sport) with reasonable duration.
    sessions_by_id = {s["id"]: s for s in sessions_sorted}
    for m in matches:
        if m.activity is not None:
            continue
        s = sessions_by_id[m.session_id]
        session_dt = date.fromisoformat(s["date"])
        if session_dt > today:
            continue   # don't substitute for future sessions

        target_dur = (s.get("targets") or {}).get("duration_min") or 0.0
        min_dur = target_dur * substitute_min_ratio if target_dur else 0.0

        same_day = [
            a for a in available.values()
            if a.date == s["date"]
            and (not min_dur or a.duration_min >= min_dur)
            and not _sport_matches(s.get("discipline", ""), a.sport)  # only true cross-sport subs
        ]
        if not same_day:
            continue

        # Prefer the longest same-day activity (likely the main workout).
        best = max(same_day, key=lambda a: a.duration_min)
        m.activity = best
        m.date_diff_days = 0
        m.notes = f"substitute ({best.sport} for {s.get('discipline', '?')})"
        del available[(best.source, best.source_id)]

    return matches


def actual_from_activity(activity: Activity) -> dict:
    """Project the Activity into the `session.actual` dict shape.

    Only the fields downstream code (analyze, summarize) consumes — keep this
    list tight; if you find yourself reaching for `raw`, lift the field here.
    """
    return {
        "source": activity.source,
        "source_id": activity.source_id,
        "name": activity.name,
        "start_time_local": activity.start_time_local,
        "date": activity.date,
        "sport": activity.sport,
        "duration_min": round(activity.duration_min, 1),
        "distance_km": round(activity.distance_km, 2),
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "avg_pace_sec_per_km": (round(activity.avg_pace_sec_per_km, 1)
                                if activity.avg_pace_sec_per_km else None),
        "elevation_gain_m": round(activity.elevation_gain_m, 0) if activity.elevation_gain_m else 0,
        "avg_power_w": activity.avg_power_w,
        "perceived_effort": activity.perceived_effort,
    }


def is_substitute(session: dict) -> bool:
    """A completed session is a substitute if the actual sport disagrees with
    the planned discipline. Returns False for any unfilled / non-completed session."""
    actual = session.get("actual") or {}
    actual_sport = actual.get("sport")
    planned_disc = session.get("discipline")
    if not actual_sport or not planned_disc:
        return False
    return actual_sport not in _DISCIPLINE_TO_SPORT.get(planned_disc, set())


def mark_missed_past_sessions(sessions: list[dict], today: date | None = None) -> int:
    """For sessions whose date is < today and still `planned`/`adjusted` with no
    actual, flip status to `missed`. Returns the count flipped."""
    today = today or date.today()
    flipped = 0
    for s in sessions:
        if s.get("actual"):
            continue
        if s.get("status", "planned") not in {"planned", "adjusted"}:
            continue
        if date.fromisoformat(s["date"]) >= today:
            continue
        s["status"] = "missed"
        flipped += 1
    return flipped
