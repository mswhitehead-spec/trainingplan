"""Daily training email: render & send.

Two concerns kept separate:

  - `render_daily_email(plan, today, ...)` builds a (subject, body) tuple.
    Pure function, easy to test, no I/O.

  - `send_email(...)` opens an SMTP connection to a server (Gmail by default)
    and sends. Reads credentials from environment vars set in `.env`.

Content priorities (today's email):

  1. Today's session(s) — type, targets, full plan notes.
  2. Yesterday's verdict (if any).
  3. The week ahead (next 7 days, one line each).
  4. Recent auto-applied adaptations (last 3 days), if any.
  5. Days to A-event.

Plain text only. Calendar apps + Gmail render plain text fine and we want
to keep this readable on a phone lock-screen preview.
"""

from __future__ import annotations

import os
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from .plan import days_to_event


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _fmt_duration_min(m: float | int | None) -> str | None:
    if not m:
        return None
    m = int(round(m))
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h" if r == 0 else f"{h}h{r:02d}m"


def _short_title(session: dict) -> str:
    """Inline title for one session line."""
    disc = session.get("discipline", "?")
    stype = session.get("type", "?")
    targets = session.get("targets") or {}
    tag = {
        "cycling": "Bike", "running": "Run", "strength": "Strength",
        "walking": "Walk", "swimming": "Swim", "rest": "Rest",
    }.get(disc, disc.title()[:6])

    if stype == "rest" or disc == "rest":
        return "[Rest] Rest day"
    if stype == "race":
        # Pull the race name out of the session id (last underscore-segment).
        sid = session.get("id", "")
        race_name = sid.rsplit("_", 1)[-1].replace("-", " ").title() or "Race"
        dist = targets.get("distance_km")
        return f"[Race] {race_name}" + (f" · {int(dist)}km" if dist else "")

    parts: list[str] = []
    if (d := _fmt_duration_min(targets.get("duration_min"))):
        parts.append(d)
    if targets.get("distance_km"):
        parts.append(f"{targets['distance_km']:g}km")
    elif targets.get("distance_km_min"):
        parts.append(f"{targets['distance_km_min']:g}km+")
    if targets.get("avg_hr_zone"):
        parts.append(targets["avg_hr_zone"])

    tail = " · " + " · ".join(parts) if parts else ""
    return f"[{tag}] {stype.replace('_', ' ')}{tail}"


def _sessions_on(plan: dict, d: date) -> list[dict]:
    s_iso = d.isoformat()
    return [s for s in plan["sessions"] if s.get("date") == s_iso]


def _sessions_between(plan: dict, lo: date, hi: date) -> list[dict]:
    return sorted(
        [s for s in plan["sessions"]
         if lo.isoformat() <= s.get("date", "") <= hi.isoformat()],
        key=lambda s: s["date"],
    )


def _latest_pending_proposal(art_dir: Path, state: dict) -> Path | None:
    """Kept for import compatibility. Returns None — proposals are now auto-applied."""
    return None


def _recent_adaptations(state: dict, days: int = 3) -> list[dict]:
    """Return auto-applied adaptation changes from the last `days` calendar days.

    Deduplicated by (session_id, field_path) — if the same field was changed
    more than once (e.g. during a fix-it loop) only the most-recent change is
    shown. Newest-first order.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for a in reversed(state.get("applied_adaptations") or []):
        if (a.get("accepted_at") or "") < cutoff:
            break
        for ch in a.get("changes") or []:
            key = (ch.get("session_id", ""), ch.get("field_path", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append({**ch, "accepted_at": a.get("accepted_at", "")})
    return out


def render_daily_email(
    plan: dict,
    today: date | None = None,
    state: dict | None = None,
    pending_proposal: Path | None = None,   # kept for call-site compat; ignored
) -> tuple[str, str]:
    """Render (subject, body) for today's email. Pure; no I/O."""
    today = today or date.today()
    state = state or {}

    today_sessions = _sessions_on(plan, today)
    recent_sessions = _sessions_between(plan, today - timedelta(days=5), today - timedelta(days=1))
    week_ahead = _sessions_between(
        plan, today + timedelta(days=1), today + timedelta(days=7)
    )

    dte = days_to_event(plan, today=today)

    # --- subject -----------------------------------------------------------
    if not today_sessions:
        subj_inner = "no session"
    elif len(today_sessions) == 1:
        subj_inner = _short_title(today_sessions[0])
    else:
        subj_inner = f"{len(today_sessions)} sessions"
    subject = f"[Training] {today.isoformat()} — {subj_inner}"

    # --- body --------------------------------------------------------------
    lines: list[str] = []
    header = f"Today: {_DOW[today.weekday()]} {today.strftime('%b %d, %Y')}"
    if dte is not None:
        if dte == 0:
            header += " — RACE DAY"
        elif dte > 0:
            header += f" — {dte} day{'s' if dte != 1 else ''} to A-event"
    lines.append(header)
    lines.append("")

    if not today_sessions:
        lines.append("Nothing on the plan today.")
        lines.append("")
    else:
        for s in today_sessions:
            lines.append(f"▶ {_short_title(s)}")
            status = s.get("status", "planned")
            if status != "planned":
                lines.append(f"  status: {status}")
            targets = s.get("targets") or {}
            if targets.get("avg_hr_range"):
                lo, hi = targets["avg_hr_range"]
                lines.append(f"  HR target: {lo}–{hi} bpm")
            elev = targets.get("elevation_gain_m")
            if elev:
                lines.append(f"  Elevation: {int(elev)} m")
            notes = (s.get("notes") or "").strip()
            if notes:
                lines.append("")
                for ln in notes.splitlines():
                    lines.append(f"  {ln}")
            lines.append("")

    # --- last 5 days -------------------------------------------------------
    if recent_sessions:
        lines.append("Last 5 days:")
        for s in sorted(recent_sessions, key=lambda x: x["date"]):
            d = date.fromisoformat(s["date"])
            dow = _DOW[d.weekday()]
            status = s.get("status", "planned")
            actual = s.get("actual") or {}
            analysis = s.get("analysis") or {}

            if status == "completed":
                icon = "✓"
                dur = actual.get("duration_min")
                dist = actual.get("distance_km")
                hr = actual.get("avg_hr")
                verdict = analysis.get("verdict", "completed")
                # Build a compact metrics string
                metrics: list[str] = []
                if dist and dist > 0:
                    metrics.append(f"{dist:.0f}km")
                if dur:
                    metrics.append(_fmt_duration_min(dur) or "")
                if hr:
                    metrics.append(f"HR {hr}")
                metric_str = " · ".join(m for m in metrics if m)
                suffix = f" ({metric_str})" if metric_str else ""
                lines.append(f"  {icon} {dow} {d.day}  {_short_title(s)}{suffix} — {verdict}")
            elif status == "missed":
                lines.append(f"  ✗ {dow} {d.day}  {_short_title(s)} — missed")
            elif status in {"planned", "adjusted"}:
                lines.append(f"  – {dow} {d.day}  {_short_title(s)} — not logged yet")
            else:
                lines.append(f"  – {dow} {d.day}  {_short_title(s)} — {status}")
        lines.append("")

    # --- week ahead --------------------------------------------------------
    if week_ahead:
        lines.append("Week ahead:")
        for s in week_ahead:
            d = date.fromisoformat(s["date"])
            tag = " ⭐ KEY" if (
                s.get("type") == "long_endurance"
                or s.get("type") == "race"
            ) else ""
            lines.append(f"  {_DOW[d.weekday()]} {d.day:>2}  {_short_title(s)}{tag}")
        lines.append("")

    # --- recent auto-applied adaptations -----------------------------------
    recent = _recent_adaptations(state, days=3)
    if recent:
        lines.append("Auto-applied adaptations (last 3 days):")
        for ch in recent:
            sid = ch.get("session_id", "?")
            field = ch.get("field_path", "?")
            old = ch.get("old_value", "?")
            new = ch.get("new_value", "?")
            rule = ch.get("rule_id", "?")
            lines.append(f"  • {sid}: {field} {old} → {new}  [{rule}]")
        lines.append("")

    lines.append("—")
    lines.append("Auto-sent by trainingplan.")
    body = "\n".join(lines)

    return subject, body


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def send_email(
    subject: str,
    body: str,
    *,
    from_addr: str,
    to_addr: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> None:
    """Send a plain-text email via SMTP+STARTTLS.

    Auth: provided smtp_user/password OR falls back to from_addr +
    EMAIL_PASSWORD env var. For Gmail, EMAIL_PASSWORD must be an App Password
    (regular passwords don't work). See docs/email_setup.md.

    Raises whatever smtplib raises on failure; the caller decides whether to
    swallow it.
    """
    if smtp_user is None:
        smtp_user = from_addr
    if smtp_password is None:
        smtp_password = os.environ.get("EMAIL_PASSWORD")
    if not smtp_password:
        raise RuntimeError(
            "No SMTP password set. Put EMAIL_PASSWORD in .env (Gmail App "
            "Password — see docs/email_setup.md)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(smtp_user, smtp_password)
        s.send_message(msg)
