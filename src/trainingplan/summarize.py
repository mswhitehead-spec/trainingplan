"""Render a per-session summary as Markdown.

These files live in `<artifacts_dir>/summaries/` — one per completed session.
The format prioritizes terminal-readable plain text first, with a small
metric table second. Verdict goes at the top so a quick `head` shows it.
"""

from __future__ import annotations


def _fmt(v, suffix: str = "", default: str = "—") -> str:
    if v is None:
        return default
    if isinstance(v, float):
        # 1 dp by default, but drop trailing .0 for tidiness.
        s = f"{v:.1f}".rstrip("0").rstrip(".")
        return s + suffix
    return f"{v}{suffix}"


def render_summary_markdown(session: dict) -> str:
    """Render a completed (or analyzed) session into markdown text."""
    analysis = session.get("analysis") or {}
    actual = session.get("actual") or {}
    targets = session.get("targets") or {}

    sid = session["id"]
    sdate = session["date"]
    sdisc = session.get("discipline", "?")
    stype = session.get("type", "?")
    sstatus = session.get("status", "?")

    verdict = analysis.get("verdict", "—")

    is_sub = "substitute" in (analysis.get("flags") or [])

    lines: list[str] = []
    title_suffix = " (substitute)" if is_sub else ""
    lines.append(f"# {sdate} — {stype.replace('_', ' ')}{title_suffix}")
    lines.append("")
    lines.append(f"**Verdict:** {verdict}")
    lines.append("")
    lines.append(f"- **Session id:** `{sid}`")
    if is_sub:
        lines.append(
            f"- **Discipline / type:** planned {sdisc} → actual "
            f"**{actual.get('sport', '?')}** · {stype}"
        )
    else:
        lines.append(f"- **Discipline / type:** {sdisc} · {stype}")
    lines.append(f"- **Status:** {sstatus}")
    if actual.get("source"):
        src_line = f"- **Source:** {actual['source']} · {actual.get('source_id', '?')}"
        if actual.get("name"):
            src_line += f" · _{actual['name']}_"
        lines.append(src_line)
    lines.append("")

    # Metric comparison table — only rows with at least one of target/actual set.
    rows: list[tuple[str, str, str, str]] = []   # (label, target, actual, delta)

    target_dur = targets.get("duration_min")
    actual_dur = actual.get("duration_min")
    if target_dur or actual_dur:
        delta = analysis.get("duration_delta_min")
        pct = analysis.get("duration_pct")
        delta_str = (f"{delta:+.0f} min ({pct:.0f}%)"
                     if delta is not None and pct is not None else "—")
        rows.append((
            "Duration",
            _fmt(target_dur, " min"),
            _fmt(actual_dur, " min"),
            delta_str,
        ))

    target_dist = targets.get("distance_km") or targets.get("distance_km_min")
    actual_dist = actual.get("distance_km")
    if target_dist or actual_dist:
        delta = analysis.get("distance_delta_km")
        pct = analysis.get("distance_pct")
        delta_str = (f"{delta:+.1f} km ({pct:.0f}%)"
                     if delta is not None and pct is not None else "—")
        rows.append((
            "Distance",
            _fmt(target_dist, " km"),
            _fmt(actual_dist, " km"),
            delta_str,
        ))

    target_hr = targets.get("avg_hr_range")
    actual_hr = actual.get("avg_hr")
    if target_hr or actual_hr:
        target_str = f"Z2 [{target_hr[0]}–{target_hr[1]}]" if target_hr else "—"
        actual_str = _fmt(actual_hr, " bpm")
        zone_str = {
            "in_zone": "in zone ✓",
            "above":   "above zone",
            "below":   "below zone",
            "unknown": "—",
        }.get(analysis.get("hr_zone_status", "unknown"), "—")
        rows.append(("Avg HR", target_str, actual_str, zone_str))

    target_elev = targets.get("elevation_gain_m")
    actual_elev = actual.get("elevation_gain_m")
    if target_elev or actual_elev:
        delta = analysis.get("elevation_delta_m")
        delta_str = f"{delta:+.0f} m" if delta is not None else "—"
        rows.append((
            "Elev gain",
            _fmt(target_elev, " m"),
            _fmt(actual_elev, " m"),
            delta_str,
        ))

    drift = analysis.get("hr_drift_pct")
    if drift is not None:
        if drift > 8:
            tag = "fatigue signal"
        elif drift <= 5:
            tag = "clean"
        else:
            tag = "moderate"
        rows.append(("HR drift", "—", f"{drift:+.1f}%", tag))

    if rows:
        lines.append("| Metric | Target | Actual | Delta |")
        lines.append("|---|---|---|---|")
        for label, t, a, d in rows:
            lines.append(f"| {label} | {t} | {a} | {d} |")
        lines.append("")

    if actual.get("perceived_effort") is not None:
        lines.append(f"**RPE:** {actual['perceived_effort']}/10")
        lines.append("")

    # Original planned notes — keep context next to the result.
    notes = (session.get("notes") or "").strip()
    if notes:
        lines.append("## Plan notes")
        lines.append("")
        for ln in notes.splitlines():
            lines.append("> " + ln if ln else ">")
        lines.append("")

    flags = analysis.get("flags") or []
    if flags:
        lines.append("**Flags:** " + ", ".join(f"`{f}`" for f in flags))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def summary_filename(session: dict) -> str:
    """Filename convention for `<artifacts_dir>/summaries/`."""
    return f"{session['date']}_{session['id'].split('_', 1)[-1]}.md"
