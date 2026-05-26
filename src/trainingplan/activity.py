"""Normalized Activity model.

Both the Strava bulk export and the Garmin CSV are parsed into Activity
instances. The Strava API client (STEP 2b) will emit the same type. Downstream
code (sync, analyze, adapt) only ever sees Activity — never raw rows.

Persistence: a JSONL file (one Activity per line) at
`<artifacts_dir>/activities.jsonl`. Append-friendly; trivial to read.
Dedup key is (source, source_id) — re-running an import won't double-write.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


# Sport categories — kept deliberately small. Anything we can't classify is "other".
SPORT_CYCLING = "cycling"
SPORT_RUNNING = "running"
SPORT_STRENGTH = "strength"
SPORT_SWIMMING = "swimming"
SPORT_WALKING = "walking"
SPORT_OTHER = "other"


@dataclass
class Activity:
    # Where the record came from. Used for dedup and source-preference logic.
    source: str            # "strava_export" | "strava_api" | "garmin_csv"
    source_id: str         # Strava activity id, or a stable hash for Garmin rows

    # When it happened. start_time_local is what the watch recorded;
    # we don't always have tz info, so treat it as naive local time.
    start_time_local: str  # ISO 8601 string, naive (e.g. "2026-05-21T09:12:53")
    date: str              # YYYY-MM-DD, the date the activity started

    # What it was.
    sport: str             # one of SPORT_* constants above
    name: str = ""
    description: str = ""

    # Duration & distance — units are uniform here regardless of source format.
    duration_min: float = 0.0            # moving time in minutes
    elapsed_min: float = 0.0             # elapsed (clock) time in minutes
    distance_km: float = 0.0

    # Cardio.
    avg_hr: int | None = None
    max_hr: int | None = None

    # Climb. (m)
    elevation_gain_m: float = 0.0

    # Sport-specific.
    avg_power_w: float | None = None     # cycling
    avg_pace_sec_per_km: float | None = None   # running (sec per km, easier math than mm:ss)

    # Subjective.
    perceived_effort: int | None = None  # Strava RPE, 1-10

    # Environment.
    temp_c: float | None = None

    # Optional pass-through fields for debugging; not used by downstream code.
    raw: dict = field(default_factory=dict)

    # ----- serialization helpers -----

    def to_json(self) -> str:
        d = asdict(self)
        # raw is a debug-only blob; keep it but it can be large. Leave as-is.
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Activity":
        d = json.loads(line)
        return cls(**d)


# ----- file I/O over a JSONL store -----

def load_all(jsonl_path: Path) -> list[Activity]:
    """Load every activity from the store. Empty list if the file doesn't exist."""
    if not jsonl_path.exists():
        return []
    out: list[Activity] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(Activity.from_json(line))
    return out


def save_all(jsonl_path: Path, activities: Iterable[Activity]) -> int:
    """Overwrite the store with the given activities. Returns count written.

    The caller is responsible for dedup. Order is preserved.
    """
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with jsonl_path.open("w", encoding="utf-8") as f:
        for a in activities:
            f.write(a.to_json())
            f.write("\n")
            n += 1
    return n


def merge_into(
    existing: list[Activity],
    new: Iterable[Activity],
) -> tuple[list[Activity], int, int]:
    """Merge `new` into `existing`, keyed by (source, source_id).

    Returns (combined_list, added_count, replaced_count). Order: existing first
    (in original order, possibly with replacements), then any new records whose
    key didn't exist.
    """
    index = {(a.source, a.source_id): i for i, a in enumerate(existing)}
    combined: list[Activity] = list(existing)
    added = 0
    replaced = 0
    for a in new:
        key = (a.source, a.source_id)
        if key in index:
            combined[index[key]] = a
            replaced += 1
        else:
            index[key] = len(combined)
            combined.append(a)
            added += 1
    # Sort newest-first by start_time_local — keeps the JSONL human-scannable.
    combined.sort(key=lambda a: a.start_time_local, reverse=True)
    return combined, added, replaced


def sport_from_strava_type(activity_type: str) -> str:
    """Map a Strava 'Activity Type' string to our sport category.

    The bulk export uses both compact and spaced variants
    ("WeightTraining" via API, "Weight Training" in CSV exports).

    Anything not explicitly mapped falls through to SPORT_OTHER. The
    substitute-matching logic still works for SPORT_OTHER — it just means
    summaries will label the actual sport as "other" instead of something
    more specific. Extend the buckets here when a new activity type starts
    appearing regularly.
    """
    t = (activity_type or "").lower().replace(" ", "")
    if t in {
        "ride", "virtualride", "ebikeride", "gravelride", "mountainbikeride",
        "handcycle", "velomobile",
    }:
        return SPORT_CYCLING
    if t in {"run", "virtualrun", "trailrun"}:
        return SPORT_RUNNING
    if t in {
        "weighttraining", "workout", "strength", "crossfit", "yoga",
        "pilates", "hiit", "tabata", "calisthenics",
    }:
        return SPORT_STRENGTH
    if t in {"swim"}:
        return SPORT_SWIMMING
    if t in {"walk", "hike", "snowshoe"}:
        return SPORT_WALKING
    return SPORT_OTHER


def sport_from_garmin_type(activity_type: str) -> str:
    """Map a Garmin Connect 'Activity Type' string to our sport category."""
    t = (activity_type or "").lower()
    if "cycling" in t or "biking" in t or t in {"ebike"}:
        return SPORT_CYCLING
    if "running" in t or t == "treadmill running":
        return SPORT_RUNNING
    if "strength" in t:
        return SPORT_STRENGTH
    if "swim" in t:
        return SPORT_SWIMMING
    if "walk" in t or "hike" in t:
        return SPORT_WALKING
    return SPORT_OTHER
