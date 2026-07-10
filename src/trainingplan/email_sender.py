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

import html as html_mod
import os
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from .activity import Activity, for_date_range
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
    # Pace range beats HR zone in the one-liner when both exist — this is a
    # pace-driven block and the watch shows pace, not zone labels.
    if targets.get("pace_range_min_per_km"):
        lo, hi = targets["pace_range_min_per_km"]
        parts.append(f"{lo}-{hi}/km")
    elif targets.get("avg_hr_zone"):
        parts.append(targets["avg_hr_zone"])

    tail = " · " + " · ".join(parts) if parts else ""
    return f"[{tag}] {stype.replace('_', ' ')}{tail}"


_TOD_ORDER = {"morning": 0, None: 1, "evening": 2}


def _tod_tag(session: dict) -> str:
    """'AM' / 'PM' marker for double days; empty for untimed sessions."""
    return {"morning": "AM", "evening": "PM"}.get(session.get("time_of_day"), "")


def _sessions_on(plan: dict, d: date) -> list[dict]:
    s_iso = d.isoformat()
    out = [s for s in plan["sessions"] if s.get("date") == s_iso]
    out.sort(key=lambda s: _TOD_ORDER.get(s.get("time_of_day"), 1))
    return out


def _sessions_between(plan: dict, lo: date, hi: date) -> list[dict]:
    return sorted(
        [s for s in plan["sessions"]
         if lo.isoformat() <= s.get("date", "") <= hi.isoformat()],
        key=lambda s: s["date"],
    )


def _next_a_event(plan: dict, today: date) -> dict | None:
    """The nearest upcoming priority-A event, or None."""
    evs = [
        e for e in plan.get("events", [])
        if e.get("priority", "A") == "A" and e.get("date", "") >= today.isoformat()
    ]
    return min(evs, key=lambda e: e["date"]) if evs else None


def _coaching_note(
    today_sessions: list[dict],
    recent_sessions: list[dict],
    plan: dict,
    dte: int | None,
    activities: list[Activity] | None = None,
) -> list[str]:
    """Generate 3-5 data-driven coaching bullets for today's email.

    Every bullet references real numbers from recent sessions where possible.
    Generic advice is a last resort; specific numbers make it feel personal.
    Positive framing throughout — the goal is to inform and motivate, not alarm.
    """
    bullets: list[str] = []

    # ---- data extraction ---------------------------------------------------
    completed = [s for s in recent_sessions if s.get("status") == "completed"]

    # Orphan activities: done during the recent window but not matched to any
    # plan session. They still contribute to total training load, so include
    # them in volume and HR metrics (but NOT in zone-status counts, which are
    # plan-session-specific).
    recent_lo = date.fromisoformat(recent_sessions[0]["date"]) if recent_sessions else (date.today() - timedelta(days=5))
    recent_hi = date.today() - timedelta(days=1)
    orphans = _orphan_acts(activities or [], plan, recent_lo, recent_hi)

    recent_hrs = [
        (s.get("actual") or {}).get("avg_hr")
        for s in completed
        if (s.get("actual") or {}).get("avg_hr")
    ]
    # Add orphan HRs to the pool used for average calculations.
    for a in orphans:
        if a.avg_hr:
            recent_hrs.append(a.avg_hr)

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
    ) + sum(a.distance_km for a in orphans)
    total_h_recent = (
        sum((s.get("actual") or {}).get("duration_min") or 0 for s in completed)
        + sum(a.duration_min for a in orphans)
    ) / 60

    stype = today_sessions[0].get("type", "") if today_sessions else ""
    sdisc = today_sessions[0].get("discipline", "") if today_sessions else ""
    targets = (today_sessions[0].get("targets") or {}) if today_sessions else {}

    athlete = plan.get("athlete") or {}
    max_hr = athlete.get("max_hr", 168)

    # Use sport-specific zones if the session discipline has its own set.
    # Cycling HR runs ~10 bpm lower than running at equivalent effort, so
    # cycling sessions use hr_zones_cycling when available (Karvonen, max=160).
    if sdisc == "cycling":
        zones = athlete.get("hr_zones_cycling") or athlete.get("hr_zones") or {}
        max_hr = athlete.get("max_hr_cycling", max_hr)
    else:
        zones = athlete.get("hr_zones") or {}
    z2 = zones.get("Z2", [116, 127] if sdisc == "cycling" else [121, 133])

    taper = dte is not None and dte <= 21
    race_week = dte is not None and dte <= 7

    # find next key upcoming session (long ride or race)
    all_sessions = plan.get("sessions", [])
    today_str = today_sessions[0].get("date", "") if today_sessions else date.today().isoformat()

    # Event context — every race-referencing bullet reads from the plan's
    # events list so the text follows whatever the current A-event is.
    ev = _next_a_event(plan, date.fromisoformat(today_str))
    ev_name = (ev or {}).get("name", "your race")
    ev_dist = (ev or {}).get("distance_km")
    ev_label = f"{ev_name} ({ev_dist:g} km)" if ev_dist else ev_name
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
            "Rest day. The parasympathetic nervous system is running the show today — "
            "heart rate variability recovers, glycogen refills, micro-tears repair. "
            "Sleep and food are the active ingredients."
        )
        bullets.append(
            "Restless? Pick ONE, kept genuinely easy: a 30–45 min walk, a "
            "20–30 min very easy spin (HR under 116), or 15–20 min of "
            "mobility work. Movement below Z1 aids recovery (blood flow "
            "without training stress); anything harder steals from tomorrow."
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
        dur_min = int(targets.get("duration_min") or 90)
        dist = targets.get("distance_km")
        what = "run" if sdisc == "running" else "ride"
        dist_txt = f"{dist:g} km " if dist else ""
        ceiling = z2[1]
        bullets.append(
            f"KEY SESSION — {dist_txt}long {what} (~{_fmt_duration_min(dur_min)}) "
            f"in Z2 ({z2[0]}–{ceiling} bpm). Start feeling almost too easy and let "
            f"HR settle; if it creeps above {ceiling + 5}, slow down before you "
            f"speed up — with {ev_label} ahead, pacing discipline is worth more "
            f"than any extra speed today."
        )
        if dur_min >= 90:
            carb = "60–80" if sdisc == "cycling" else "30–60"
            bullets.append(
                f"Fuel it like race day: {carb} g carbohydrate per hour from "
                f"minute 40 (gels or drink mix — whatever you'll use at {ev_name}). "
                f"Your gut needs rehearsal; don't discover GI intolerance on race "
                f"day (Burke & Hawley, 2002)."
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
                f"{ev_label} (Seiler, 2010 — polarised training model). "
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
        base = (
            "Strength today: hips, glutes, calves, core — single-leg work "
            "(RDLs, step-ups, Copenhagen planks) beats machines for endurance "
            "athletes (Rønnestad & Mujika, 2014: concurrent strength training "
            "improves economy and performance). "
        )
        if taper and dte is not None:
            base += (f"With {dte} days to the race: maintenance only — skip "
                     f"anything that creates soreness.")
        else:
            base += ("This far from the race, progressive load is welcome — "
                     "soreness now buys durability for the build weeks.")
        bullets.append(base)
    elif stype == "tempo":
        bullets.append(
            "Tempo: comfortably hard, not all-out. "
            f"Rough HR target: {z2[1] + 5}–{int(max_hr * 0.88)} bpm — short "
            "phrases, not full sentences. If you feel flat after the warmup, "
            "dial back to Z2: a conservative quality day beats a forced one "
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
        rr = targets.get("avg_hr_range")
        hr_txt = f"HR {rr[0]}–{rr[1]}" if rr else f"HR near {z2[1]}"
        if sdisc == "running":
            bullets.append(
                f"Race day — {ev_label}. Go out AT goal pace, never under it: "
                f"time banked early is borrowed from the final kilometers at "
                f"brutal interest. Settle into {hr_txt} and lock in. "
                f"The runners you pass late are the ones who went out hard. "
                f"You've done the work — trust it."
            )
        else:
            bullets.append(
                f"Race day — {ev_label}. Start patient, {hr_txt}, let the fast "
                f"starters go. Fuel every 20–30 min regardless of hunger. "
                f"You've done the work — trust it."
            )

    # ---- bullet 2: aerobic trend from recent data --------------------------
    # For the trend bullet, derive the Z2 reference from the RECENT sessions'
    # dominant discipline — not today's (which might be strength / rest).
    cycling_count = sum(1 for s in completed if s.get("discipline") == "cycling")
    if cycling_count > len(completed) / 2:
        trend_zones = athlete.get("hr_zones_cycling") or athlete.get("hr_zones") or {}
        trend_z2 = trend_zones.get("Z2", [116, 127])
    else:
        trend_z2 = z2

    if completed and stype not in {"race"}:
        if below_zone_count >= 2 and recent_hrs:
            avg_hr = round(sum(recent_hrs) / len(recent_hrs))
            bullets.append(
                f"Aerobic control looks good: {below_zone_count} of your last "
                f"{len(completed)} session(s) held HR below Z2 "
                f"(average {avg_hr} bpm vs. your Z2 floor of {trend_z2[0]}). "
                f"That aerobic headroom is the base you'll race {ev_name} off — "
                f"sustained effort without cardiac drift."
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
                f"Every unnecessary effort now costs you on race day. "
                f"Sleep, hydration, and carbohydrate intake are the performance levers."
            )
        else:
            bullets.append(
                f"{dte} days to {ev_name}. Physiological adaptation from today's "
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
                f"{ev_name} is {days_away} day{'s' if days_away != 1 else ''} away "
                f"({key_d.strftime('%a %b %d')}). "
                f"Everything between now and then is about showing up fresh."
            )
        elif key_dur:
            key_what = "long run" if next_key.get("discipline") == "running" else "long ride"
            bullets.append(
                f"Next key session: {_DOW[key_d.weekday()]} {key_d.strftime('%b %d')} — "
                f"{key_dur} {key_what} ({days_away} day{'s' if days_away != 1 else ''} away). "
                f"Today's job is to arrive at that session with legs ready."
            )

    return bullets


def _consumed_source_ids(plan: dict) -> set[str]:
    """Source IDs already claimed by a matched plan session."""
    out: set[str] = set()
    for s in plan.get("sessions", []):
        sid = (s.get("actual") or {}).get("source_id")
        if sid:
            out.add(str(sid))
    return out


def _orphan_acts(
    activities: list[Activity],
    plan: dict,
    lo: date,
    hi: date,
) -> list[Activity]:
    """Activities in [lo, hi] not claimed by any plan session, oldest-first."""
    if not activities:
        return []
    consumed = _consumed_source_ids(plan)
    return [
        a for a in for_date_range(activities, lo.isoformat(), hi.isoformat())
        if str(a.source_id) not in consumed
    ]


def _day_rows(
    plan: dict,
    recent_sessions: list[dict],
    activities: list[Activity],
    today: date,
) -> list[dict]:
    """Structured rows for the last-5-days section.

    Shared by the plain-text and HTML renderers so both show identical data.
    Each row: {kind: done|missed|pending|orphan, date, title, metrics, verdict}.
    """
    recent_lo = today - timedelta(days=5)
    recent_hi = today - timedelta(days=1)
    orphans_by_date: dict[str, list[Activity]] = {}
    for a in _orphan_acts(activities, plan, recent_lo, recent_hi):
        orphans_by_date.setdefault(a.date, []).append(a)

    rows: list[dict] = []
    all_dates = sorted(set(
        [s["date"] for s in recent_sessions] + list(orphans_by_date)
    ))
    for date_str in all_dates:
        d = date.fromisoformat(date_str)
        for s in (x for x in recent_sessions if x["date"] == date_str):
            status = s.get("status", "planned")
            actual = s.get("actual") or {}
            metrics: list[str] = []
            if status == "completed":
                if (actual.get("distance_km") or 0) > 0:
                    metrics.append(f"{actual['distance_km']:.0f}km")
                if actual.get("duration_min"):
                    metrics.append(_fmt_duration_min(actual["duration_min"]) or "")
                if actual.get("avg_hr"):
                    metrics.append(f"HR {actual['avg_hr']}")
                verdict = (s.get("analysis") or {}).get("verdict", "completed")
            elif status == "missed":
                verdict = "missed"
            else:
                verdict = "not logged yet"
            rows.append({
                "kind": {"completed": "done", "missed": "missed"}.get(status, "pending"),
                "date": d,
                "title": _short_title(s),
                "metrics": " · ".join(m for m in metrics if m),
                "verdict": verdict,
            })
        for a in orphans_by_date.get(date_str, []):
            tag = {"cycling": "Bike", "running": "Run", "walking": "Walk",
                   "strength": "Strength", "swimming": "Swim"}.get(
                       a.sport, a.sport.title()[:6])
            o_metrics = []
            if a.distance_km > 0:
                o_metrics.append(f"{a.distance_km:.0f}km")
            if a.duration_min:
                o_metrics.append(_fmt_duration_min(a.duration_min) or "")
            if a.avg_hr:
                o_metrics.append(f"HR {a.avg_hr}")
            label = (a.name or "unplanned").encode("ascii", "replace").decode("ascii")[:30]
            rows.append({
                "kind": "orphan",
                "date": d,
                "title": f"[{tag}] {label}",
                "metrics": " · ".join(m for m in o_metrics if m),
                "verdict": "outside plan",
            })
    return rows


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
    activities: list[Activity] | None = None,
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
        disc_tag = {"cycling": "Bike", "running": "Run", "strength": "Strength",
                    "walking": "Walk", "swimming": "Swim", "rest": "Rest"}
        subj_inner = " + ".join(
            f"{_tod_tag(s)} {disc_tag.get(s.get('discipline'), '?')}".strip()
            for s in today_sessions
        )
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
            tod = _tod_tag(s)
            lines.append(f"▶ {tod + ' — ' if tod else ''}{_short_title(s)}")
            status = s.get("status", "planned")
            if status != "planned":
                lines.append(f"  status: {status}")
            targets = s.get("targets") or {}
            if targets.get("pace_range_min_per_km"):
                plo, phi = targets["pace_range_min_per_km"]
                lines.append(f"  Pace target: {plo}–{phi} /km")
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
    note_bullets = _coaching_note(today_sessions, recent_sessions, plan, dte,
                                   activities=activities)
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
    rows = _day_rows(plan, recent_sessions, activities or [], today)
    if rows:
        lines.append("Last 5 days:")
        for r in rows:
            icon = {"done": "✓", "missed": "✗", "orphan": "+"}.get(r["kind"], "–")
            d = r["date"]
            metric_str = f" ({r['metrics']})" if r["metrics"] else ""
            lines.append(f"  {icon} {_DOW[d.weekday()]} {d.day}  "
                         f"{r['title']}{metric_str} — {r['verdict']}")
        lines.append("")

    # --- week ahead --------------------------------------------------------
    if week_ahead:
        lines.append("Week ahead:")
        week_ahead_sorted = sorted(
            week_ahead,
            key=lambda s: (s["date"], _TOD_ORDER.get(s.get("time_of_day"), 1)),
        )
        for s in week_ahead_sorted:
            d = date.fromisoformat(s["date"])
            tag = " ⭐ KEY" if (
                s.get("type") == "long_endurance"
                or s.get("type") == "race"
            ) else ""
            tod = _tod_tag(s)
            tod_str = f" {tod}" if tod else "   "
            lines.append(f"  {_DOW[d.weekday()]} {d.day:>2}{tod_str}  {_short_title(s)}{tag}")
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
# HTML rendering
# ---------------------------------------------------------------------------

_DISC_COLORS = {
    "running": "#059669", "cycling": "#2563eb", "strength": "#b45309",
    "walking": "#64748b", "swimming": "#0891b2", "rest": "#94a3b8",
}
_FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_DASHBOARD_URL = "https://mswhitehead-spec.github.io/trainingplan/"


def _e(text: str) -> str:
    return html_mod.escape(str(text))


def _h_label(text: str) -> str:
    return (f'<div style="font-size:11px;font-weight:700;color:#9ca3af;'
            f'text-transform:uppercase;letter-spacing:.08em;'
            f'margin:22px 0 8px;">{_e(text)}</div>')


def _h_chip(text: str, fg: str, bg: str) -> str:
    return (f'<span style="display:inline-block;background:{bg};color:{fg};'
            f'font-size:11px;font-weight:700;border-radius:10px;'
            f'padding:2px 9px;vertical-align:middle;">{_e(text)}</span>')


def render_daily_email_html(
    plan: dict,
    today: date | None = None,
    state: dict | None = None,
    activities: list[Activity] | None = None,
) -> str:
    """HTML twin of render_daily_email — same sections, styled for Gmail.

    Inline styles only (email clients strip <style> blocks unreliably).
    The plain-text version remains the multipart fallback and the format
    of record for tests.
    """
    today = today or date.today()
    state = state or {}

    today_sessions = _sessions_on(plan, today)
    recent_sessions = _sessions_between(
        plan, today - timedelta(days=5), today - timedelta(days=1))
    week_ahead = sorted(
        _sessions_between(plan, today + timedelta(days=1), today + timedelta(days=7)),
        key=lambda s: (s["date"], _TOD_ORDER.get(s.get("time_of_day"), 1)),
    )
    dte = days_to_event(plan, today=today)
    ev = _next_a_event(plan, today)
    ev_name = (ev or {}).get("name", "race")

    out: list[str] = []
    out.append(f'<div style="max-width:600px;margin:0 auto;padding:12px 8px;'
               f'font-family:{_FONT};color:#1f2937;font-size:14.5px;'
               f'line-height:1.55;">')

    # --- header --------------------------------------------------------------
    if dte == 0:
        pill = _h_chip("RACE DAY", "#ffffff", "#7c3aed")
    elif dte is not None and dte > 0:
        pill = _h_chip(f"{dte} days to {ev_name}", "#4338ca", "#eef2ff")
    else:
        pill = ""
    out.append(
        f'<div style="padding-bottom:6px;border-bottom:2px solid #e5e7eb;">'
        f'<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;'
        f'letter-spacing:.08em;">Training</div>'
        f'<div style="font-size:21px;font-weight:800;margin:1px 0 6px;">'
        f'{_DOW[today.weekday()]} {today.strftime("%b %d, %Y")}</div>'
        f'{pill}</div>'
    )

    # --- today's session cards ------------------------------------------------
    if not today_sessions:
        out.append('<p style="color:#6b7280;">Nothing on the plan today.</p>')
    for s in today_sessions:
        color = _DISC_COLORS.get(s.get("discipline"), "#2563eb")
        tod = _tod_tag(s)
        tod_chip = (_h_chip(tod, "#374151", "#e5e7eb") + " ") if tod else ""
        targets = s.get("targets") or {}
        meta: list[str] = []
        if targets.get("pace_range_min_per_km"):
            plo, phi = targets["pace_range_min_per_km"]
            meta.append(f"Pace {plo}–{phi} /km")
        if targets.get("avg_hr_range"):
            lo, hi = targets["avg_hr_range"]
            meta.append(f"HR {lo}–{hi} bpm")
        if targets.get("elevation_gain_m"):
            meta.append(f"{int(targets['elevation_gain_m'])} m elev")
        status = s.get("status", "planned")
        if status != "planned":
            meta.append(status)
        meta_html = (f'<div style="color:#6b7280;font-size:13px;margin-top:2px;">'
                     f'{_e(" · ".join(meta))}</div>') if meta else ""
        notes = (s.get("notes") or "").strip()
        notes_html = (f'<div style="white-space:pre-line;color:#4b5563;'
                      f'font-size:13px;margin-top:8px;border-top:1px solid '
                      f'#e5e7eb;padding-top:8px;">{_e(notes)}</div>') if notes else ""
        out.append(
            f'<div style="background:#f8fafc;border-left:4px solid {color};'
            f'border-radius:8px;padding:12px 14px;margin:12px 0;">'
            f'<div style="font-size:15.5px;font-weight:700;">{tod_chip}'
            f'{_e(_short_title(s))}</div>{meta_html}{notes_html}</div>'
        )

    # --- coach's notes ---------------------------------------------------------
    bullets = _coaching_note(today_sessions, recent_sessions, plan, dte,
                             activities=activities)
    if bullets:
        out.append(_h_label("Coach's notes"))
        out.append('<ul style="margin:0;padding-left:20px;">')
        for b in bullets:
            out.append(f'<li style="margin:0 0 8px;color:#374151;'
                       f'font-size:13.5px;">{_e(b)}</li>')
        out.append('</ul>')

    # --- last 5 days -------------------------------------------------------------
    rows = _day_rows(plan, recent_sessions, activities or [], today)
    if rows:
        out.append(_h_label("Last 5 days"))
        icon_style = {
            "done":   ("✓", "#059669"),
            "missed": ("✗", "#dc2626"),
            "orphan": ("+", "#2563eb"),
            "pending": ("–", "#9ca3af"),
        }
        for r in rows:
            icon, ic = icon_style.get(r["kind"], ("–", "#9ca3af"))
            d = r["date"]
            metrics = (f' <span style="color:#6b7280;">({_e(r["metrics"])})</span>'
                       if r["metrics"] else "")
            out.append(
                f'<div style="margin:3px 0;font-size:13.5px;">'
                f'<span style="color:{ic};font-weight:700;">{icon}</span> '
                f'<span style="color:#9ca3af;">{_DOW[d.weekday()]} {d.day}</span> '
                f'{_e(r["title"])}{metrics} '
                f'<span style="color:#9ca3af;">— {_e(r["verdict"])}</span></div>'
            )

    # --- week ahead ------------------------------------------------------------
    if week_ahead:
        out.append(_h_label("Week ahead"))
        out.append('<table style="border-collapse:collapse;width:100%;'
                   'font-size:13.5px;">')
        for s in week_ahead:
            d = date.fromisoformat(s["date"])
            key = s.get("type") in {"long_endurance", "race"}
            color = _DISC_COLORS.get(s.get("discipline"), "#2563eb")
            tod = _tod_tag(s)
            weight = "700" if key else "400"
            star = " ⭐" if key else ""
            out.append(
                f'<tr>'
                f'<td style="padding:3px 8px 3px 0;color:#9ca3af;'
                f'white-space:nowrap;">{_DOW[d.weekday()]} {d.day}'
                f'{(" · " + tod) if tod else ""}</td>'
                f'<td style="padding:3px 0;font-weight:{weight};">'
                f'<span style="color:{color};">●</span> '
                f'{_e(_short_title(s))}{star}</td></tr>'
            )
        out.append('</table>')

    # --- recent adaptations ------------------------------------------------------
    recent = _recent_adaptations(state, days=3)
    if recent:
        out.append(_h_label("Auto-applied adaptations"))
        for ch in recent:
            out.append(
                f'<div style="margin:3px 0;font-size:13px;color:#4b5563;">'
                f'{_e(ch.get("session_id", "?"))}: {_e(ch.get("field_path", "?"))} '
                f'{_e(ch.get("old_value", "?"))} → {_e(ch.get("new_value", "?"))} '
                f'<span style="color:#9ca3af;">[{_e(ch.get("rule_id", "?"))}]</span></div>'
            )

    # --- footer --------------------------------------------------------------
    out.append(
        f'<div style="margin-top:24px;padding-top:10px;border-top:1px solid '
        f'#e5e7eb;font-size:12px;color:#9ca3af;">'
        f'Auto-sent by trainingplan · '
        f'<a href="{_DASHBOARD_URL}" style="color:#4338ca;">Dashboard</a>'
        f'</div></div>'
    )
    return "\n".join(out)


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
    html_body: str | None = None,
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
    if html_body:
        # multipart/alternative: clients that render HTML use it; the plain
        # text stays as the fallback (and the lock-screen preview source).
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(smtp_user, smtp_password)
        s.send_message(msg)
