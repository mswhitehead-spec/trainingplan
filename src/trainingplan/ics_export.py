"""Render a training plan to an iCalendar (.ics) file.

Hand-rolled RFC 5545 serializer. We previously used the `ics` PyPI library
but its 0.7 release is broken against current `tatsu`. Our needs here are
small enough that a few dozen lines of escape/format code beats fighting a
dependency.

One VEVENT per session. UID is derived from session.id (stable across
regenerations, so Google Calendar updates rather than duplicates). Sessions
default to a 07:00 local start; rest days are all-day events.

Status mapping:

    plan status     →   VEVENT STATUS
    -------------       -------------
    planned             CONFIRMED
    adjusted            CONFIRMED
    completed           CONFIRMED
    missed              CANCELLED
    skipped             CANCELLED

Title format:

    [Bike]  Long ride · 4h · 80km · Z2
    [Run]   Easy run · 30m · 5km
    [Rest]  Rest day
    [Race]  Vätternrundan · 315km
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_START_TIME = time(7, 0)   # 07:00 local; rest days override to all-day
_UID_SUFFIX = "@trainingplan.local"
_PRODID = "-//trainingplan//en"

_DISCIPLINE_TO_TAG = {
    "cycling":  "Bike",
    "running":  "Run",
    "strength": "Strength",
    "walking":  "Walk",
    "swimming": "Swim",
    "rest":     "Rest",
}

_STATUS_MAP = {
    "planned":   "CONFIRMED",
    "adjusted":  "CONFIRMED",
    "completed": "CONFIRMED",
    "missed":    "CANCELLED",
    "skipped":   "CANCELLED",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_duration_min(mins: float | int | None) -> str | None:
    """45 → '45m'; 240 → '4h'; 75 → '1h15m'."""
    if not mins:
        return None
    m = int(round(mins))
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h" if r == 0 else f"{h}h{r:02d}m"


def _title_for(session: dict) -> str:
    """e.g. '[Bike] Long ride · 4h · 80km · Z2'."""
    disc = session.get("discipline", "?")
    stype = session.get("type", "?")
    targets = session.get("targets") or {}

    tag = _DISCIPLINE_TO_TAG.get(disc, disc[:6].title())

    # Special cases.
    if stype == "race":
        sid = session.get("id", "")
        race_name = sid.rsplit("_", 1)[-1].replace("-", " ").title()
        dist = targets.get("distance_km")
        return f"[Race] {race_name} · {int(dist)}km" if dist else f"[Race] {race_name}"

    if disc == "rest" or stype == "rest":
        return "[Rest] Rest day"

    pretty_type = stype.replace("_", " ")
    parts: list[str] = []
    if (d := _fmt_duration_min(targets.get("duration_min"))):
        parts.append(d)
    if targets.get("distance_km"):
        parts.append(f"{targets['distance_km']:g}km")
    elif targets.get("distance_km_min"):
        parts.append(f"{targets['distance_km_min']:g}km+")
    if targets.get("pace_range_min_per_km"):
        lo, hi = targets["pace_range_min_per_km"]
        parts.append(f"{lo}-{hi}/km")
    elif targets.get("avg_hr_zone"):
        parts.append(targets["avg_hr_zone"])

    if parts:
        return f"[{tag}] {pretty_type} · " + " · ".join(parts)
    return f"[{tag}] {pretty_type}"


def _description_for(session: dict) -> str:
    """Long-form event description: targets, notes, and (if completed) verdict."""
    targets = session.get("targets") or {}
    actual = session.get("actual") or {}
    analysis = session.get("analysis") or {}

    lines: list[str] = []
    lines.append(f"Session: {session.get('id')}")
    lines.append(f"Type: {session.get('type', '?')}  ·  Status: {session.get('status', '?')}")
    lines.append("")

    if targets:
        lines.append("Targets:")
        for k, v in targets.items():
            lines.append(f"  - {k}: {v}")
        lines.append("")

    notes = (session.get("notes") or "").strip()
    if notes:
        lines.append("Notes:")
        lines.append(notes)
        lines.append("")

    if actual:
        lines.append("Actual:")
        for k in ("duration_min", "distance_km", "avg_hr", "max_hr",
                  "elevation_gain_m", "perceived_effort"):
            v = actual.get(k)
            if v is not None:
                lines.append(f"  - {k}: {v}")
        lines.append("")

    if analysis and analysis.get("verdict"):
        lines.append(f"Verdict: {analysis['verdict']}")

    return "\n".join(lines).rstrip()


def _is_rest(session: dict) -> bool:
    return session.get("discipline") == "rest" or session.get("type") == "rest"


# ---------------------------------------------------------------------------
# RFC 5545 serialization
# ---------------------------------------------------------------------------

def _ical_escape(s: str) -> str:
    """Escape per RFC 5545 §3.3.11: backslash, semicolon, comma, newline."""
    return (s.replace("\\", "\\\\")
             .replace(";", "\\;")
             .replace(",", "\\,")
             .replace("\r\n", "\\n")
             .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Fold a content line to ≤75 octets per RFC 5545 §3.1.
    Continuation lines are prefixed with a single space. Operates on
    UTF-8 byte boundaries to avoid splitting a multi-byte character."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    chunks: list[bytes] = []
    pos = 0
    limit = 75   # first line 75 octets; continuations 74 (leading space uses one)
    while pos < len(encoded):
        end = min(pos + limit, len(encoded))
        # If the byte AT the split point is a UTF-8 continuation byte we'd be
        # cutting a multi-byte character in half — walk back to the char start.
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[pos:end])
        pos = end
        limit = 74
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def _fmt_dt_utc_stamp(dt: datetime) -> str:
    """For DTSTAMP we use UTC; suffix Z."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fmt_dt_local(dt: datetime) -> str:
    """Local floating datetime — no TZID, no Z. Calendar apps interpret
    these in the user's local timezone, which is exactly what we want for a
    personal calendar that travels with the athlete."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Build calendar
# ---------------------------------------------------------------------------

def build_calendar(plan: dict, start_time: time = _DEFAULT_START_TIME) -> str:
    """Return the .ics text for the plan."""
    now_utc = datetime.now(timezone.utc)
    dtstamp = _fmt_dt_utc_stamp(now_utc)

    lines: list[str] = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append(f"PRODID:{_PRODID}")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")
    # X-WR-CALNAME is non-standard but every major client honors it.
    lines.append("X-WR-CALNAME:Training plan")
    lines.append("X-WR-CALDESC:Auto-generated training schedule")

    for s in plan["sessions"]:
        uid = f"{s['id']}{_UID_SUFFIX}"
        summary = _title_for(s)
        description = _description_for(s)
        status = _STATUS_MAP.get(s.get("status", "planned"), "CONFIRMED")
        sdate = date.fromisoformat(s["date"])

        lines.append("BEGIN:VEVENT")
        lines.append(_fold(f"UID:{uid}"))
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"STATUS:{status}")
        lines.append(_fold(f"SUMMARY:{_ical_escape(summary)}"))
        if description:
            lines.append(_fold(f"DESCRIPTION:{_ical_escape(description)}"))

        if _is_rest(s):
            # All-day event: DTSTART;VALUE=DATE + DTEND next day (exclusive).
            lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(sdate)}")
            lines.append(f"DTEND;VALUE=DATE:{_fmt_date(sdate + timedelta(days=1))}")
            lines.append("TRANSP:TRANSPARENT")     # don't block the day
        else:
            # Per-session slot: double days carry time_of_day so the two
            # sessions land at 06:00 and 18:00 instead of stacking.
            slot = {"morning": time(6, 0), "evening": time(18, 0)}
            dt_start = datetime.combine(
                sdate, slot.get(s.get("time_of_day"), start_time))
            duration_min = (s.get("targets") or {}).get("duration_min") or 30
            dt_end = dt_start + timedelta(minutes=int(duration_min))
            lines.append(f"DTSTART:{_fmt_dt_local(dt_start)}")
            lines.append(f"DTEND:{_fmt_dt_local(dt_end)}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # RFC 5545 §3.1 — lines separated by CRLF.
    return "\r\n".join(lines) + "\r\n"


def write_ics(plan: dict, out_path: Path, *,
              start_time: time = _DEFAULT_START_TIME) -> int:
    """Build the calendar and write it to out_path. Returns the byte count
    written. Creates parent dirs as needed."""
    text = build_calendar(plan, start_time=start_time)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8", newline="")
    return len(text.encode("utf-8"))
