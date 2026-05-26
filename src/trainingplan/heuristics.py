"""Adaptation rules.

Each rule is a function with the signature

    def rule_xxx(ctx: RuleContext) -> list[ProposedChange]: ...

`heuristics.yaml` lists which rules are enabled, their parameters, and the
citations. This module:

  - loads & validates heuristics.yaml,
  - exposes RULE_REGISTRY: dict[name -> callable],
  - runs all enabled rules, gathering their proposed changes.

Adding a new rule = (1) write the function below, (2) register it in
RULE_REGISTRY, (3) add an entry to heuristics.yaml. The plan and tests
won't change.

Design rules (per user preference):
  - All proposals reduce volume/intensity, never increase. When in doubt,
    rest. This is hard-coded into each rule.
  - Rules only act on FUTURE sessions (date >= today). Never mutate the past.
  - Sessions already `completed` or `skipped` are off-limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProposedChange:
    """One concrete edit to a single session."""

    session_id: str
    field_path: str       # dotted path inside the session dict, e.g. "targets.duration_min"
    old_value: object
    new_value: object
    reason: str           # human-readable, surfaced in the proposal markdown
    rule_id: str          # which heuristic produced this change

    def apply(self, session: dict) -> None:
        """Mutate session in place to set field_path = new_value."""
        parts = self.field_path.split(".")
        node = session
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                node[p] = {}
            node = node[p]
        node[parts[-1]] = self.new_value


@dataclass
class RuleContext:
    """Inputs every rule sees. Pre-filtered for convenience."""

    plan: dict
    today: date
    days_to_event: int | None         # to nearest priority-A event, None if none
    sessions: list[dict]              # full plan.sessions list
    upcoming: list[dict]              # sessions with date >= today AND status in {planned, adjusted}
    completed_recent: list[dict]      # completed sessions in last 14 days, newest first
    missed_recent: list[dict]         # missed sessions in last 14 days


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _hr_above_zone(session: dict) -> bool:
    """Was this completed session's avg HR above its target zone?"""
    analysis = session.get("analysis") or {}
    return analysis.get("hr_zone_status") == "above"


def _is_long_endurance(session: dict) -> bool:
    return session.get("type") == "long_endurance"


def _is_high_intensity(session: dict) -> bool:
    return session.get("type") in {"intervals", "tempo"}


def _next_session_of_type(upcoming: list[dict], stype: str) -> dict | None:
    for s in upcoming:
        if s.get("type") == stype:
            return s
    return None


def _scale_duration_change(
    session: dict, factor: float, *, rule_id: str, reason: str
) -> ProposedChange | None:
    """Build a ProposedChange that scales targets.duration_min by `factor`.
    Returns None if the session has no duration target."""
    targets = session.get("targets") or {}
    cur = targets.get("duration_min")
    if not cur:
        return None
    new = int(round(cur * factor))
    if new == cur:
        return None
    return ProposedChange(
        session_id=session["id"],
        field_path="targets.duration_min",
        old_value=cur,
        new_value=new,
        reason=reason,
        rule_id=rule_id,
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_hr_drift_high(ctx: RuleContext, params: dict) -> list[ProposedChange]:
    """If the most recent completed long_endurance had HR drift above the
    threshold, reduce the next planned long_endurance's duration.

    Note: until per-second HR streams are wired in (post-STEP 2b API path),
    `hr_drift_pct` is None for CSV-imported sessions and this rule never
    fires. That's intentional — better to wait for real data than guess.
    """
    threshold = float(params.get("drift_threshold_pct", 8.0))
    reduction = float(params.get("duration_reduction_pct", 15.0))

    recent_long = next(
        (s for s in ctx.completed_recent if _is_long_endurance(s)),
        None,
    )
    if not recent_long:
        return []
    drift = (recent_long.get("analysis") or {}).get("hr_drift_pct")
    if drift is None or drift <= threshold:
        return []

    next_long = _next_session_of_type(ctx.upcoming, "long_endurance")
    if not next_long:
        return []

    factor = 1.0 - reduction / 100.0
    change = _scale_duration_change(
        next_long,
        factor,
        rule_id="hr_drift_high",
        reason=f"HR drift on {recent_long['date']} long ride was {drift:+.1f}% "
               f"(>{threshold}%) — aerobic decoupling.",
    )
    return [change] if change else []


def rule_race_week_cap_intensity(ctx: RuleContext, params: dict) -> list[ProposedChange]:
    """In the last 7 days before the A-event, demote any tempo/intervals
    session to easy_endurance. Openers are exempt."""
    if ctx.days_to_event is None or ctx.days_to_event > 7:
        return []

    changes: list[ProposedChange] = []
    for s in ctx.upcoming:
        if not _is_high_intensity(s):
            continue
        sdate = date.fromisoformat(s["date"])
        if (sdate - ctx.today).days < 0 or (sdate - ctx.today).days > 7:
            continue
        changes.append(ProposedChange(
            session_id=s["id"],
            field_path="type",
            old_value=s["type"],
            new_value="easy_endurance",
            reason=f"race in {ctx.days_to_event} days — no intensity in race week.",
            rule_id="race_week_cap_intensity",
        ))
    return changes


def rule_race_window_cap_long_duration(
    ctx: RuleContext, params: dict
) -> list[ProposedChange]:
    """Within `window_days` of the A-event, cap any long_endurance session at
    `max_long_duration_min`."""
    window = int(params.get("window_days", 14))
    max_dur = int(params.get("max_long_duration_min", 180))

    if ctx.days_to_event is None or ctx.days_to_event > window:
        return []

    changes: list[ProposedChange] = []
    for s in ctx.upcoming:
        if not _is_long_endurance(s):
            continue
        if s.get("type") == "race":   # don't shorten the actual race
            continue
        cur = (s.get("targets") or {}).get("duration_min")
        if not cur or cur <= max_dur:
            continue
        changes.append(ProposedChange(
            session_id=s["id"],
            field_path="targets.duration_min",
            old_value=cur,
            new_value=max_dur,
            reason=f"within {window}d of A-event — cap long duration at {max_dur} min.",
            rule_id="race_window_cap_long_duration",
        ))
    return changes


def rule_missed_long_no_makeup_short_window(
    ctx: RuleContext, params: dict
) -> list[ProposedChange]:
    """If a long_endurance was missed and the A-event is ≤ race_window_days,
    do NOT add a makeup — instead reduce the NEXT long_endurance by
    duration_reduction_pct. Trying to chase the missed stimulus this close
    to the event creates fatigue, not fitness."""
    race_window = int(params.get("race_window_days", 21))
    reduction = float(params.get("duration_reduction_pct", 10.0))

    if ctx.days_to_event is None or ctx.days_to_event > race_window:
        return []

    if not any(_is_long_endurance(s) for s in ctx.missed_recent):
        return []
    next_long = _next_session_of_type(ctx.upcoming, "long_endurance")
    if not next_long:
        return []

    factor = 1.0 - reduction / 100.0
    change = _scale_duration_change(
        next_long,
        factor,
        rule_id="missed_long_no_makeup_short_window",
        reason=f"missed a long endurance and race in {ctx.days_to_event}d — "
               f"don't chase; trim next long instead.",
    )
    return [change] if change else []


def rule_two_hot_sessions(ctx: RuleContext, params: dict) -> list[ProposedChange]:
    """If the two most recent completed sessions both had HR above target zone,
    flip the next quality (tempo/intervals/long_endurance) session to
    easy_endurance for one cycle."""
    last_two = ctx.completed_recent[:2]
    if len(last_two) < 2:
        return []
    if not all(_hr_above_zone(s) for s in last_two):
        return []

    next_quality = next(
        (s for s in ctx.upcoming
         if s.get("type") in {"tempo", "intervals", "long_endurance"}),
        None,
    )
    if not next_quality:
        return []

    return [ProposedChange(
        session_id=next_quality["id"],
        field_path="type",
        old_value=next_quality["type"],
        new_value="easy_endurance",
        reason="last two sessions both ran hot — back off one cycle.",
        rule_id="two_hot_sessions",
    )]


def rule_frequent_missed_sessions(ctx: RuleContext, params: dict) -> list[ProposedChange]:
    """If the athlete has missed ≥ missed_threshold sessions in the last
    lookback_days, demote the next high-intensity session to easy_endurance.

    Reasoning: repeated skipped sessions usually mean illness, life stress,
    travel, or under-recovery. Adding intensity into that context risks
    injury / illness escalation. The conservative move is to keep volume
    accessible but drop intensity until consistency returns.

    Substituted sessions (status=completed with cross-sport actual) do NOT
    count toward the missed total — those represent training that did happen,
    just not the planned discipline.

    Sources: Foster 1998 (monotony / strain); Friel CTB Ch. 9 (consistency
    as the foundation of progress); common coaching practice on illness/
    travel returns.
    """
    threshold = int(params.get("missed_threshold", 3))
    lookback = int(params.get("lookback_days", 7))

    # Count only true misses in the lookback window.
    cutoff = ctx.today.toordinal() - lookback
    recent_misses = [
        s for s in ctx.missed_recent
        if date.fromisoformat(s["date"]).toordinal() >= cutoff
    ]
    if len(recent_misses) < threshold:
        return []

    next_quality = next(
        (s for s in ctx.upcoming if _is_high_intensity(s)),
        None,
    )
    if not next_quality:
        return []

    return [ProposedChange(
        session_id=next_quality["id"],
        field_path="type",
        old_value=next_quality["type"],
        new_value="easy_endurance",
        reason=(
            f"{len(recent_misses)} sessions missed in the last {lookback} days — "
            f"prioritize consistency over intensity until rhythm returns "
            f"(Friel CTB Ch. 9)."
        ),
        rule_id="frequent_missed_sessions",
    )]


def rule_duration_overreach(ctx: RuleContext, params: dict) -> list[ProposedChange]:
    """If the most recent completed session's actual duration exceeded the
    planned target by `overreach_ratio`x or more, propose two changes:
      1. Flip the immediately next upcoming session to 'recovery' (rest and let
         the stimulus land — Friel CTB Ch. 6, supercompensation window).
      2. Reduce the following long_endurance duration by `long_reduction_pct`
         (the big stimulus already happened; no need to stack another long soon).

    Only fires within `race_window_days` of the A-event, where fatigue
    management matters most.

    Sources: Friel *Cyclist's Training Bible* Ch. 6 (supercompensation);
             Bosquet et al. 2007 taper meta-analysis (fatigue management).
    """
    ratio = float(params.get("overreach_ratio", 2.0))
    long_reduction = float(params.get("long_reduction_pct", 25.0))
    race_window = int(params.get("race_window_days", 21))

    if ctx.days_to_event is None or ctx.days_to_event > race_window:
        return []

    if not ctx.completed_recent:
        return []

    last = ctx.completed_recent[0]
    targets = last.get("targets") or {}
    actual = last.get("actual") or {}
    planned_dur = targets.get("duration_min")
    actual_dur = actual.get("duration_min")

    if not planned_dur or not actual_dur:
        return []
    if actual_dur < planned_dur * ratio:
        return []

    overreach_pct = int(round((actual_dur / planned_dur - 1) * 100))
    changes: list[ProposedChange] = []

    # Change 1: promote first upcoming non-race session to recovery.
    next_up = next(
        (s for s in ctx.upcoming if s.get("type") not in {"race", "recovery"}),
        None,
    )
    if next_up:
        changes.append(ProposedChange(
            session_id=next_up["id"],
            field_path="type",
            old_value=next_up["type"],
            new_value="recovery",
            reason=(
                f"last session ({last['date']}) overreached planned duration by "
                f"{overreach_pct}% — supercompensation needs a recovery day "
                f"(Friel CTB Ch. 6)."
            ),
            rule_id="duration_overreach",
        ))

    # Change 2: trim next long_endurance — the big stimulus already happened.
    next_long = _next_session_of_type(ctx.upcoming, "long_endurance")
    if next_long and (not next_up or next_long["id"] != next_up["id"]):
        change = _scale_duration_change(
            next_long,
            1.0 - long_reduction / 100.0,
            rule_id="duration_overreach",
            reason=(
                f"overreached by {overreach_pct}% on {last['date']} — "
                f"long ride stimulus already absorbed; trim next long "
                f"by {int(long_reduction)}% to avoid stacking fatigue."
            ),
        )
        if change:
            changes.append(change)

    return changes


# ---------------------------------------------------------------------------
# Registry & driver
# ---------------------------------------------------------------------------


RuleFn = Callable[[RuleContext, dict], list[ProposedChange]]

RULE_REGISTRY: dict[str, RuleFn] = {
    "hr_drift_high": rule_hr_drift_high,
    "race_week_cap_intensity": rule_race_week_cap_intensity,
    "race_window_cap_long_duration": rule_race_window_cap_long_duration,
    "missed_long_no_makeup_short_window": rule_missed_long_no_makeup_short_window,
    "two_hot_sessions": rule_two_hot_sessions,
    "duration_overreach": rule_duration_overreach,
    "frequent_missed_sessions": rule_frequent_missed_sessions,
}


def load_heuristics(path: Path) -> dict:
    """Load heuristics.yaml. Raises ValueError on structural issues."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "rules" not in raw:
        raise ValueError(f"{path}: missing top-level 'rules' key")
    for r in raw["rules"]:
        if "id" not in r or "function" not in r:
            raise ValueError(f"rule missing id/function: {r!r}")
        if r["function"] not in RULE_REGISTRY:
            raise ValueError(
                f"rule '{r['id']}' references unknown function "
                f"'{r['function']}' — known: {sorted(RULE_REGISTRY)}"
            )
    return raw


def build_context(plan: dict, today: date | None = None,
                  recent_days: int = 14) -> RuleContext:
    """Slice the plan into the views every rule wants."""
    from .plan import days_to_event   # local import to avoid cycle

    today = today or date.today()

    sessions = plan["sessions"]
    upcoming = [
        s for s in sessions
        if date.fromisoformat(s["date"]) >= today
        and s.get("status", "planned") in {"planned", "adjusted"}
    ]
    upcoming.sort(key=lambda s: s["date"])

    cutoff = today.toordinal() - recent_days
    completed_recent = [
        s for s in sessions
        if s.get("status") == "completed"
        and date.fromisoformat(s["date"]).toordinal() >= cutoff
    ]
    completed_recent.sort(key=lambda s: s["date"], reverse=True)

    missed_recent = [
        s for s in sessions
        if s.get("status") == "missed"
        and date.fromisoformat(s["date"]).toordinal() >= cutoff
    ]
    missed_recent.sort(key=lambda s: s["date"], reverse=True)

    return RuleContext(
        plan=plan,
        today=today,
        days_to_event=days_to_event(plan, today=today),
        sessions=sessions,
        upcoming=upcoming,
        completed_recent=completed_recent,
        missed_recent=missed_recent,
    )


def run_all(heuristics: dict, ctx: RuleContext) -> list[ProposedChange]:
    """Run every enabled rule. Returns the combined ProposedChange list,
    in rule-declaration order. Dedup is the caller's job (see adapt.py)."""
    out: list[ProposedChange] = []
    for r in heuristics["rules"]:
        if not r.get("enabled", True):
            continue
        fn = RULE_REGISTRY[r["function"]]
        params = r.get("params") or {}
        out.extend(fn(ctx, params))
    return out
