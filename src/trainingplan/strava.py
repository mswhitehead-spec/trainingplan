"""Strava API client with on-disk token persistence.

The first time you authenticate, `scripts/auth_strava.py` writes a token bundle
to TOKEN_PATH. From then on, `get_client()` reads the bundle and refreshes the
access token if it's within REFRESH_MARGIN_SEC of expiry — so the rest of the
codebase never has to think about token lifecycle.

Token bundle on disk (JSON):
    {
        "access_token": "...",
        "refresh_token": "...",
        "expires_at": 1717... (unix epoch seconds)
    }
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from stravalib import Client

from trainingplan.activity import Activity, sport_from_strava_type


# Cross-platform: ~/.trainingplan on Linux/Mac, %USERPROFILE%\.trainingplan on Windows.
TOKEN_DIR = Path.home() / ".trainingplan"
TOKEN_PATH = TOKEN_DIR / "strava_tokens.json"

# Refresh access token if it expires within this many seconds.
REFRESH_MARGIN_SEC = 300

# OAuth scope. activity:read_all also covers private activities.
DEFAULT_SCOPES = ["read", "activity:read_all"]


# ----- token persistence -----

def save_tokens(access_token: str, refresh_token: str, expires_at: int | float) -> None:
    """Persist a token bundle to disk with safe permissions."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": int(expires_at),
    }
    TOKEN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Windows ACLs are clunkier than chmod; best-effort tighten with stat.
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except (OSError, NotImplementedError):
        pass


def load_tokens() -> dict | None:
    """Load token bundle from disk if present, else None.

    For cloud runs (GitHub Actions) the disk file usually doesn't exist —
    get_client() then falls back to env-var-only mode.
    """
    if not TOKEN_PATH.exists():
        return None
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def _tokens_from_env() -> dict | None:
    """Build a synthetic token bundle from env vars (cloud / CI runs).

    Returns a bundle with a stale access_token and expires_at=0 so the
    refresh path always fires on the first call. Subsequent calls in the
    same process reuse the live Client's in-memory token.
    """
    rt = os.environ.get("STRAVA_REFRESH_TOKEN")
    if not rt:
        return None
    return {
        "access_token": "stale",
        "refresh_token": rt,
        "expires_at": 0,
    }


# ----- client factory -----

def get_client(client_id: str | None = None, client_secret: str | None = None) -> Client:
    """Return a stravalib Client with a current access token.

    Token source order:
      1. STRAVA_REFRESH_TOKEN env var (cloud / CI) — always triggers refresh.
      2. Disk file ~/.trainingplan/strava_tokens.json (local dev) — refresh
         only if expiring within REFRESH_MARGIN_SEC.

    Reads STRAVA_CLIENT_ID/SECRET from env if not passed.
    """
    tok = _tokens_from_env() or load_tokens()
    if tok is None:
        raise RuntimeError(
            "No Strava tokens. Local dev: run scripts/auth_strava.py. "
            "Cloud: set STRAVA_REFRESH_TOKEN (and CLIENT_ID/SECRET) env vars."
        )

    cid = client_id or os.environ.get("STRAVA_CLIENT_ID")
    csec = client_secret or os.environ.get("STRAVA_CLIENT_SECRET")
    if not cid or not csec:
        raise RuntimeError(
            "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set (see .env)."
        )

    now = time.time()
    if tok["expires_at"] - now < REFRESH_MARGIN_SEC:
        # Refresh.
        client = Client()
        new = client.refresh_access_token(
            client_id=int(cid),
            client_secret=csec,
            refresh_token=tok["refresh_token"],
        )
        # stravalib returns either a dict or a model — normalize.
        access = new.get("access_token") if isinstance(new, dict) else new.access_token
        refresh = new.get("refresh_token") if isinstance(new, dict) else new.refresh_token
        expires = new.get("expires_at") if isinstance(new, dict) else new.expires_at

        if not os.environ.get("STRAVA_REFRESH_TOKEN"):
            # Local dev — persist to disk so next run reuses access_token.
            save_tokens(access, refresh, expires)
            tok = load_tokens()
        else:
            # Cloud run — no writable persistent disk. Notify if Strava rotated
            # the refresh token so the user knows to update the GH Secret.
            # DO NOT print the new token value here — workflow logs are public
            # on public repos, and a rotated token is NOT yet registered as a
            # Secret, so GitHub's log redaction wouldn't catch it.
            if refresh != tok["refresh_token"]:
                print("WARNING: Strava rotated the refresh token. The new "
                      "value is in this process's memory only; the next cron "
                      "run will fail until you locally run scripts/auth_strava.py "
                      "and update the STRAVA_REFRESH_TOKEN GitHub Secret.")
            tok = {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": expires,
            }

    # Set refresh_token too so stravalib's auto-refresh path is happy (and
    # silences the "Please set client.refresh_token" warning on every call).
    return Client(
        access_token=tok["access_token"],
        refresh_token=tok["refresh_token"],
        token_expires=tok["expires_at"],
    )


# ----- fetching -----

def fetch_recent(client: Client, limit: int = 30, after: datetime | None = None) -> list[Activity]:
    """Fetch the most recent activities and convert to our Activity model.

    `limit` caps results regardless of date filter. `after` is a UTC datetime;
    only activities started after it are returned.
    """
    out: list[Activity] = []
    iterator = client.get_activities(after=after, limit=limit)
    for sa in iterator:
        out.append(_strava_to_activity(sa))
    return out


def _enum_to_str(value) -> str:
    """stravalib v2 wraps sport in RelaxedSportType(root='Run') — a pydantic
    RootModel. Get the bare string so sport_from_strava_type's lookup works.

    Handles all shapes seen in the wild:
      - RootModel: value.root            -> "Run"   (stravalib 2.x)
      - Enum with .value:                -> "Run"   (older stravalib)
      - Enum stringified "SportType.RUN" -> strip prefix
      - Plain string:                       pass through
    """
    if value is None:
        return ""
    # stravalib v2: RelaxedSportType / RelaxedActivityType expose .root.
    root = getattr(value, "root", None)
    if isinstance(root, str):
        return root
    # Older shape: pydantic StrEnum with .value.
    v = getattr(value, "value", None)
    if isinstance(v, str):
        return v
    s = str(value)
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    return s


def _qty(value, attr: str = "magnitude") -> float | None:
    """stravalib v2 returns some fields as pint.Quantity. Get the raw number."""
    if value is None:
        return None
    if hasattr(value, attr):
        try:
            return float(getattr(value, attr))
        except Exception:
            pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strava_to_activity(sa) -> Activity:
    """Map a stravalib Activity (or SummaryActivity) to our Activity."""
    # stravalib v2 returns datetime in UTC; we store naive local-ish iso strings.
    start = sa.start_date_local or sa.start_date
    if isinstance(start, datetime):
        start_iso = start.replace(tzinfo=None).isoformat(timespec="seconds")
        date_iso = start.date().isoformat()
    else:
        start_iso = str(start)
        date_iso = start_iso[:10]

    # Distance: meters in the API; convert to km.
    distance_m = _qty(getattr(sa, "distance", None)) or 0.0
    distance_km = distance_m / 1000.0

    elapsed = _qty(getattr(sa, "elapsed_time", None))
    if elapsed is None and getattr(sa, "elapsed_time", None) is not None:
        # may be a timedelta
        try:
            elapsed = float(sa.elapsed_time.total_seconds())
        except AttributeError:
            elapsed = 0.0
    moving = _qty(getattr(sa, "moving_time", None))
    if moving is None and getattr(sa, "moving_time", None) is not None:
        try:
            moving = float(sa.moving_time.total_seconds())
        except AttributeError:
            moving = elapsed
    elapsed = elapsed or 0.0
    moving = moving or elapsed

    sport = sport_from_strava_type(_enum_to_str(
        getattr(sa, "sport_type", None) or getattr(sa, "type", "")
    ))

    avg_speed_mps = _qty(getattr(sa, "average_speed", None))
    avg_pace = (1000.0 / avg_speed_mps) if (avg_speed_mps and avg_speed_mps > 0) else None

    return Activity(
        source="strava_api",
        source_id=str(sa.id),
        start_time_local=start_iso,
        date=date_iso,
        sport=sport,
        name=getattr(sa, "name", "") or "",
        description=getattr(sa, "description", "") or "",
        duration_min=round(moving / 60.0, 2),
        elapsed_min=round(elapsed / 60.0, 2),
        distance_km=round(distance_km, 3),
        avg_hr=int(sa.average_heartrate) if getattr(sa, "average_heartrate", None) else None,
        max_hr=int(sa.max_heartrate) if getattr(sa, "max_heartrate", None) else None,
        elevation_gain_m=_qty(getattr(sa, "total_elevation_gain", None)) or 0.0,
        avg_power_w=_qty(getattr(sa, "average_watts", None)),
        avg_pace_sec_per_km=round(avg_pace, 1) if avg_pace else None,
        perceived_effort=int(sa.perceived_exertion) if getattr(sa, "perceived_exertion", None) else None,
        temp_c=_qty(getattr(sa, "average_temp", None)),
        raw={"sport_type": _enum_to_str(
            getattr(sa, "sport_type", None) or getattr(sa, "type", "")
        )},
    )
