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


def _coaching_note(
    today_sessions: list[dict],
    recent_sessions: list[dict],
    plan: dict,
    dte: int | None,
) -> list[str]:
    """Generate 3-5 data-driven coaching bullets for today's email.

    Every bullet references real numbers from recent sessions where possible.
    Generic advice is a last resort; specific numbers make it feel personal.
    Positive framing throughout — the goal is to inform and motivate, not alarm.
    """
    bullets: list[str] = []

    # ---- data extraction ---------------------------------------------------
    completed = [s for s in recent_sessions if s.get("status") == "completed"]
    recent_hrs = [
        (s.get("actual") or {}).get("avg_hr")
        for s in completed
        if (s.get("actual") or {}).get("avg_hr")
    ]
    recent_drifts = [
        (s.get("analysis") or {}).get("hr_drift_pct")
        for s in completed
        if (s.get("analysis") or {}).get("hr_drift_pct") is not None
    ]
    below_zone_count = sum(
        1 for s in completed
        if (s.get("analysis") or {}).get("hr_zone_status") == "below"
    )
    total_km_recent = sum(
        (s.get("actual") or {}).get("distance_km") or 0
        for s in completed
    )
    total_h_recent = sum(
        (s.get("actual") or {}).get("duration_min") or 0
        for s in completed
    ) / 60

    athlete = plan.get("athlete") or {}
    max_hr = athlete.get("max_hr", 168)
    zones = athlete.get("zones") or {}
    z2 = zones.get("Z2", [123, 138])

    stype = today_sessions[0].get("type", "") if today_sessions else ""
    sdisc = today_sessions[0].get("discipline", "") if today_sessions else ""
    targets = (today_sessions[0].get("targets") or {}) if today_sessions else {}

    taper = dte is not None and dte <= 21
    race_week = dte is not None and dte <= 7

    # find next key upcoming session (long ride or race)
    all_sessions = plan.get("sessions", [])
    today_str = today_sessions[0].get("date", "") if today_sessions else date.today().isoformat()
    next_key = next(
        (s for s in all_sessions
         if s.get("date", "") > today_str
         and s.get("type") in {"long_endurance", "race"}
         and s.get("status") in {"planned", "adjusted"}),
        None,
    )

    # ---- bullet 1: session-specific execution advice -----------------------
    if stype in {"rest"}:
        bullets.append(
            "Full rest day. The parasympathetic nervous system is running the show today — "
            "heart rate variability recovers, glycogen refills, micro-tears repair. "
            "Sleep and food are the active ingredients; there's nothing to do but let them work."
        )
    elif stype == "recovery":
        if recent_hrs:
            last_hr = recent_hrs[-1]
            bullets.append(
                f"Recovery session — keep HR well below {z2[0]} bpm (your last session "
                f"averaged {last_hr} bpm; aim noticeably lower today). "
                f"Supercompensation peaks 24–48 h after a stimulus (Friel, CTB Ch. 6) "
                f"and elevated HR on recovery days blunts that window. Easy spin or walk only."
            )
        else:
            bullets.append(
                "Keep today genuinely easy — HR well below Z2, no efforts. "
                "Supercompensation (the fitness gain from training) peaks in the 24–48 h "
                "after a hard session (Friel, CTB Ch. 6). Easy days protect that window."
            )
    elif stype == "long_endurance":
        dur_h = int((targets.get("duration_min") or 180) // 60)
        dist = targets.get("distance_km", 80)
        ceiling = z2[1]
        bullets.append(
            f"KEY SESSION — {dur_h}h Z2 endurance. Start the first 30 min feeling "
            f"almost too easy; HR should settle into {z2[0]}–{ceiling} bpm on flat "
            f"terrain. If it creeps above {ceiling + 5} on a climb, back off cadence "
            f"before speed — at 315 km race distance, pacing discipline is worth more "
            f"than any single extra watt today."
        )
        bullets.append(
            f"Practice race fueling: 60–80 g carbohydrate per hour starting at minute 20 "
            f"(gels, bars, or liquid — whatever you'll use on June 12). "
            f"Your gut needs rehearsal; don't discover GI intolerance on race day. "
            f"At ~{int(dur_h * 65)} g/hr that's {dur_h * 65} g total — roughly "
            f"{dur_h * 65 // 25} standard gels (Burke & Hawley, 2002)."
        )
    elif stype in {"easy_endurance", "endurance_z2"}:
        if recent_hrs:
            avg_hr = round(sum(recent_hrs) / len(recent_hrs))
            bullets.append(
                f"Aerobic base work — target {z2[0]}–{z2[1]} bpm. "
                f"Your recent sessions have averaged {avg_hr} bpm, "
                f"which is {'well inside' if avg_hr < z2[0] else 'right in'} the aerobic zone. "
                f"Talk-test pace: you should be able to speak in full sentences. "
                f"If you can't, you're over zone."
            )
        else:
            bullets.append(
                f"Z2 target: {z2[0]}–{z2[1]} bpm. This builds mitochondrial density and "
                f"fat oxidation without accumulating lactate — the aerobic foundation for "
                f"a 315 km effort (Seiler, 2010 — polarised training model). "
                f"Talk-test pace throughout."
            )
    elif stype == "easy_run":
        bullets.append(
            "Easy run — aerobic maintenance. The cardiovascular adaptations (cardiac output, "
            "mitochondrial density) carry across disciplines: running Z2 primes the same "
            "central engine as cycling Z2. Focus on HR, not pace. "
            f"Target: conversational, well below {z2[1]} bpm."
        )
    elif stype == "strength":
        bullets.append(
            "Strength focus today: hip stability and core, not load. "
            "Glute bridges, single-leg Romanian deadlifts, Copenhagen planks — "
            "these directly improve power transfer on the bike and reduce lower-back "
            "fatigue at 4+ hour efforts (Rønnestad & Mujika, 2014). "
            "Skip anything that creates DOMS; with 15 days to the race you don't have "
            "time to absorb new muscle damage."
        )
    elif stype == "tempo":
        bullets.append(
            "Tempo: upper Z3 / lower Z4 — comfortably hard, not all-out. "
            f"Rough HR target: {z2[1] + 5}–{int(max_hr * 0.88)} bpm. "
            "If you feel flat after the warmup, dial back to Z2 — pre-race taper "
            "responses are individual, and a conservative tempo day beats a forced one "
            "that generates lingering fatigue."
        )
    elif stype == "openers":
        bullets.append(
            "Openers: 2–3 short hard efforts (30–60 s at Z4–Z5) with full recovery between. "
            "The goal is neuromuscular activation, not fitness — you should finish feeling "
            "springy, not tired. These clear metabolic waste and prime fast-twitch recruitment "
            "for race day (Mujika & Padilla, 2003 — peaking protocols)."
        )
    elif stype == "race":
        bullets.append(
            f"Race day — Vätternrundan 315 km. First 2 hours: stay patient, "
            f"HR ≤ {z2[1]} bpm, let the fast starters go. "
            f"Fuel every 20–30 min regardless of hunger. "
            f"The riders you'll pass at km 200 are the ones going hard now. "
            f"You've done the work — trust it."
        )

    # ---- bullet 2: aerobic trend from recent data --------------------------
    if completed and stype not in {"race"}:
        if below_zone_count >= 2 and recent_hrs:
            avg_hr = round(sum(recent_hrs) / len(recent_hrs))
            bullets.append(
                f"Aerobic control looks good: {below_zone_count} of your last "
                f"{len(completed)} session(s) held HR below Z2 "
                f"(average {avg_hr} bpm vs. your Z2 floor of {z2[0]}). "
                f"That level of aerobic headroom is exactly right for a 315 km event — "
                f"you can sustain output for hours without cardiac drift."
            )
        elif recent_drifts:
            avg_drift = sum(recent_drifts) / len(recent_drifts)
            if avg_drift < 5:
                bullets.append(
                    f"HR drift on recent sessions: {avg_drift:+.1f}% — below the 5% "
                    f"decoupling threshold (Maffetone). Your cardiovascular system is "
                    f"coupling effort to output efficiently, which is a good sign for "
                    f"sustained pacing over a long race."
                )
            else:
                bullets.append(
                    f"HR drift has been {avg_drift:+.1f}% on recent sessions "
                    f"(>5% indicates aerobic decoupling — Maffetone). "
                    f"Today's easy work helps clear it: low-HR sessions restore "
                    f"parasympathetic tone and cardiac efficiency."
                )
        elif total_km_recent > 0 and total_h_recent > 0:
            bullets.append(
                f"Training load this week: {total_km_recent:.0f} km / {total_h_recent:.1f} h "
                f"across {len(completed)} session(s). "
                f"Volume is in the right range for the taper window — enough stimulus to "
                f"maintain adaptation without accumulating fatigue that eats into race-day freshness."
            )

    # ---- bullet 3: taper / race countdown context --------------------------
    if taper and dte is not None and stype not in {"race"}:
        if race_week:
            bullets.append(
                f"Race week — {dte} day{'s' if dte != 1 else ''} out. "
                f"Fitness is fixed; the only remaining variable is freshness. "
                f"Every unnecessary effort now costs race-day watts. "
                f"Sleep, hydration, and carbohydrate intake are the performance levers."
            )
        else:
            bullets.append(
                f"{dte} days to Vätternrundan. Physiological adaptation from today's "
                f"training won't arrive in time — full adaptation takes 10–14 days "
                f"(Bosquet et al., 2007). The job now is to arrive at the start line "
                f"feeling fresh, not fitter."
            )

    # ---- bullet 4: next key event callout ----------------------------------
    if next_key and stype not in {"long_endurance", "race"}:
        key_d = date.fromisoformat(next_key["date"])
        days_away = (key_d - date.today()).days
        key_targets = next_key.get("targets") or {}
        key_dur = _fmt_duration_min(key_targets.get("duration_min"))
        if next_key.get("type") == "race":
            bullets.append(
                f"Vätternrundan is {days_away} day{'s' if days_away != 1 else ''} away "
                f"({key_d.strftime('%a %b %d')}). "
                f"Everything between now and then is about showing up fresh."
            )
        elif key_dur:
            bullets.append(
                f"Next key session: {_DOW[key_d.weekday()]} {key_d.strftime('%b %d')} — "
                f"{key_dur} long ride ({days_away} day{'s' if days_away != 1 else ''} away). "
                f"Today's job is to arrive at that session with legs ready."
            )

    return bullets


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

    # --- coaching note -----------------------------------------------------
    note_bullets = _coaching_note(today_sessions, recent_sessions, plan, dte)
    if note_bullets:
        lines.append("Today's note:")
        for b in note_bullets:
            # Wrap long bullets at ~72 chars for readability in plain-text clients
            words = b.split()
            line_buf = "  •"
            for word in words:
                if len(line_buf) + len(word) + 1 > 74:
                    lines.append(line_buf)
                    line_buf = "    " + word
                else:
                    line_buf += " " + word
            lines.append(line_buf)
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
