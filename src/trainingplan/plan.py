"""Training plan: schema, validation, helpers.

The plan is a YAML file (`<artifacts>/plan.yaml`). It is the human-editable
source of truth — open it in any editor, change session targets, notes, dates,
or status. The scripts read it, mutate it, and emit derivatives (.ics, summaries).

This module provides:
  - karvonen_zones()         : compute HR zones from max + resting HR
  - load(path) / save(path)  : YAML round-trip preserving key order
  - validate(plan)           : raise ValueError on structural problems
  - small navigation helpers (next session, days-to-event, etc.)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml


# Recognized values — used by validate() to catch typos.

KNOWN_DISCIPLINES: set[str] = {
    "cycling", "running", "strength", "walking", "swimming", "rest",
}

KNOWN_SESSION_TYPES: set[str] = {
    "easy_endurance",  # any discipline, easy aerobic
    "endurance_z2",    # mid-length steady Z2 ride/run
    "long_endurance",  # the long session of the week
    "tempo",           # Z3 steady
    "intervals",       # Z4-Z5 work
    "recovery",        # very easy
    "easy_run",        # synonym for running easy_endurance
    "rest",            # planned rest day
    "brick",           # bike-then-run combo
    "strength",        # gym/core
    "openers",         # short pre-race priming
    "race",            # the event itself
}

KNOWN_STATUSES: set[str] = {
    "planned", "completed", "missed", "skipped", "adjusted",
}


# --- HR zones via the Karvonen heart-rate-reserve method --------------------

def karvonen_zones(max_hr: int, resting_hr: int) -> dict[str, list[int]]:
    """Compute HR zone ranges using the Karvonen HRR method.

    Karvonen target HR = resting + pct * (max - resting). More individualized
    than %max-HR zones, which assume everyone has the same resting HR.

    Returns {zone_name: [low_bpm, high_bpm]}.
    """
    hrr = max_hr - resting_hr
    bands = {
        "Z1": (0.50, 0.60),
        "Z2": (0.60, 0.70),
        "Z3": (0.70, 0.80),
        "Z4": (0.80, 0.90),
        "Z5": (0.90, 1.00),
    }
    return {
        name: [int(round(resting_hr + lo * hrr)),
               int(round(resting_hr + hi * hrr))]
        for name, (lo, hi) in bands.items()
    }


# --- file I/O ---------------------------------------------------------------

def load(path: Path) -> dict:
    """Load a plan YAML file. Returns the raw dict; use validate() to check it."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save(path: Path, plan: dict) -> None:
    """Write the plan back as YAML, preserving key order and unicode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text, encoding="utf-8")


# --- validation -------------------------------------------------------------

def validate(plan: dict) -> None:
    """Raise ValueError if the plan is malformed.

    Checks: required top-level keys, session id uniqueness, session date format,
    discipline/type/status enum membership.
    """
    for key in ("athlete", "events", "block", "sessions"):
        if key not in plan:
            raise ValueError(f"missing top-level key: {key!r}")

    if not isinstance(plan["sessions"], list):
        raise ValueError("'sessions' must be a list")

    seen_ids: set[str] = set()
    for s in plan["sessions"]:
        sid = s.get("id")
        if not sid:
            raise ValueError("session missing 'id'")
        if sid in seen_ids:
            raise ValueError(f"duplicate session id: {sid!r}")
        seen_ids.add(sid)

        disc = s.get("discipline")
        if disc not in KNOWN_DISCIPLINES:
            raise ValueError(f"{sid}: unknown discipline {disc!r}; "
                             f"known: {sorted(KNOWN_DISCIPLINES)}")

        stype = s.get("type")
        if stype not in KNOWN_SESSION_TYPES:
            raise ValueError(f"{sid}: unknown type {stype!r}; "
                             f"known: {sorted(KNOWN_SESSION_TYPES)}")

        status = s.get("status", "planned")
        if status not in KNOWN_STATUSES:
            raise ValueError(f"{sid}: unknown status {status!r}")

        d = s.get("date")
        try:
            date.fromisoformat(d)
        except (TypeError, ValueError):
            raise ValueError(f"{sid}: invalid date {d!r} (want YYYY-MM-DD)")


# --- helpers ----------------------------------------------------------------

def sessions_by_status(plan: dict, status: str) -> list[dict]:
    return [s for s in plan["sessions"] if s.get("status", "planned") == status]


def next_planned_session(plan: dict, today: date | None = None) -> dict | None:
    """The earliest upcoming session whose status is 'planned' or 'adjusted'."""
    today = today or date.today()
    candidates = [
        s for s in plan["sessions"]
        if s.get("status", "planned") in {"planned", "adjusted"}
        and date.fromisoformat(s["date"]) >= today
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s["date"])


def get_zone_range(plan: dict, zone_label: str,
                   discipline: str = "running") -> list[int] | None:
    """Return [lo, hi] bpm for `zone_label` (e.g. 'Z2'), choosing the
    discipline-specific zone table when available.

    Cycling HR is physiologically ~10 bpm lower than running at equivalent
    effort, so 'hr_zones_cycling' is stored separately and consulted first
    for cycling sessions.

    Returns None if the zone isn't defined.
    """
    athlete = plan.get("athlete") or {}
    if discipline == "cycling":
        zones = athlete.get("hr_zones_cycling") or athlete.get("hr_zones") or {}
    else:
        zones = athlete.get("hr_zones") or {}
    r = zones.get(zone_label)
    return list(r) if r else None


def days_to_event(plan: dict, today: date | None = None,
                  priority: str = "A") -> int | None:
    """Days until the next event of the given priority. None if no such event."""
    today = today or date.today()
    events = [e for e in plan["events"] if e.get("priority", "A") == priority]
    if not events:
        return None
    nearest = min(events, key=lambda e: e["date"])
    return (date.fromisoformat(nearest["date"]) - today).days
