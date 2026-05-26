"""Proposal generator.

Given a plan, recent completed/missed sessions, and the heuristics, build a
Proposal: a structured list of suggested changes, plus a markdown rendering.

Dedup rule
----------
If two rules want to modify the same (session_id, field_path), the more
conservative one wins:
  - duration changes: the LOWER new_value wins (keep volume down)
  - type demotions: easy_endurance > everything else (always keep the easier)
  - other fields: first rule wins (declaration order in heuristics.yaml)

The proposal carries every change and every reason — even if two rules both
fired for the same session, both reasons are surfaced so the user understands
the consensus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .heuristics import (
    ProposedChange,
    RuleContext,
    build_context,
    load_heuristics,
    run_all,
)
from .plan import days_to_event


# Demotion order: lower index = easier session. Used by dedup when two rules
# both want to flip a session's `type`.
_TYPE_EASE_ORDER = [
    "rest", "recovery", "easy_endurance", "easy_run",
    "endurance_z2", "tempo", "intervals", "long_endurance", "openers", "race",
]


def _ease_index(t: str) -> int:
    try:
        return _TYPE_EASE_ORDER.index(t)
    except ValueError:
        return len(_TYPE_EASE_ORDER)   # unknown → least easy (defensive)


@dataclass
class Proposal:
    id: str                                    # e.g. "2026-06-02T07-14"
    generated_at: str                          # ISO timestamp
    today: str                                 # the "today" used to compute
    days_to_event: int | None
    changes: list[ProposedChange] = field(default_factory=list)
    # Snapshot of what fed the rules — useful when reading old proposals.
    based_on_completed: list[str] = field(default_factory=list)
    based_on_missed: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


def _dedup(changes: list[ProposedChange]) -> list[ProposedChange]:
    """Collapse duplicate (session_id, field_path) into the more conservative one.
    Reasons of all merged-away changes are appended to the surviving one's reason."""
    by_key: dict[tuple[str, str], ProposedChange] = {}
    extra_reasons: dict[tuple[str, str], list[str]] = {}

    for c in changes:
        key = (c.session_id, c.field_path)
        if key not in by_key:
            by_key[key] = c
            extra_reasons[key] = []
            continue

        cur = by_key[key]
        # Prefer the more conservative new_value.
        if c.field_path == "targets.duration_min":
            keep = c if (c.new_value or 0) < (cur.new_value or 0) else cur
        elif c.field_path == "type":
            keep = c if _ease_index(str(c.new_value)) < _ease_index(str(cur.new_value)) else cur
        else:
            keep = cur   # first wins for unknown fields

        loser = c if keep is cur else cur
        by_key[key] = keep
        extra_reasons[key].append(f"[{loser.rule_id}] {loser.reason}")

    # Merge extra reasons into surviving change.
    out: list[ProposedChange] = []
    for key, c in by_key.items():
        extras = extra_reasons[key]
        if extras:
            c.reason = c.reason + "  (also: " + "; ".join(extras) + ")"
        out.append(c)

    # Stable order — by session date implicit in id prefix, then by field.
    out.sort(key=lambda c: (c.session_id, c.field_path))
    return out


def generate_proposal(
    plan: dict,
    heuristics: dict,
    today: date | None = None,
) -> Proposal:
    """Run all enabled rules and assemble a Proposal."""
    today = today or date.today()
    ctx = build_context(plan, today=today)

    raw_changes = run_all(heuristics, ctx)
    changes = _dedup(raw_changes)

    # Gather citations from rules that actually fired.
    fired_rule_ids = {c.rule_id for c in changes}
    citations: list[str] = []
    for r in heuristics["rules"]:
        if r["id"] in fired_rule_ids:
            for cite in r.get("citations", []):
                citations.append(f"[{r['id']}] {cite}")

    now = datetime.now()
    return Proposal(
        id=now.strftime("%Y-%m-%dT%H-%M"),
        generated_at=now.isoformat(timespec="seconds"),
        today=today.isoformat(),
        days_to_event=days_to_event(plan, today=today),
        changes=changes,
        based_on_completed=[s["id"] for s in ctx.completed_recent],
        based_on_missed=[s["id"] for s in ctx.missed_recent],
        citations=citations,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_proposal_markdown(proposal: Proposal, plan: dict) -> str:
    """Render the proposal to a markdown document for the proposals/ folder."""
    sessions_by_id = {s["id"]: s for s in plan["sessions"]}

    lines: list[str] = []
    lines.append(f"# Proposal {proposal.id}")
    lines.append("")
    lines.append(f"- Generated: {proposal.generated_at}")
    lines.append(f"- Today: {proposal.today}")
    if proposal.days_to_event is not None:
        lines.append(f"- Days to A-event: {proposal.days_to_event}")
    if proposal.based_on_completed:
        lines.append(f"- Completed (last 14d): {len(proposal.based_on_completed)} "
                     f"sessions")
    if proposal.based_on_missed:
        lines.append(f"- Missed (last 14d): {len(proposal.based_on_missed)} "
                     f"sessions")
    lines.append("")

    if not proposal.changes:
        lines.append("## No changes proposed")
        lines.append("")
        lines.append("Every applicable rule looked at the plan and the recent "
                     "results and proposed nothing. The plan stands as-is.")
        return "\n".join(lines) + "\n"

    lines.append(f"## {len(proposal.changes)} proposed change(s)")
    lines.append("")
    for i, c in enumerate(proposal.changes, 1):
        s = sessions_by_id.get(c.session_id, {})
        sdate = s.get("date", "?")
        stype = s.get("type", "?")
        lines.append(f"### [{i}] `{c.session_id}`  ({sdate} · {stype})")
        lines.append("")
        lines.append(f"- **Field:** `{c.field_path}`")
        lines.append(f"- **From:** `{c.old_value}`")
        lines.append(f"- **To:** `{c.new_value}`")
        lines.append(f"- **Rule:** `{c.rule_id}`")
        lines.append(f"- **Reason:** {c.reason}")
        lines.append("")

    if proposal.citations:
        lines.append("## Citations")
        lines.append("")
        for cite in proposal.citations:
            lines.append(f"- {cite}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("To apply interactively:")
    lines.append("")
    lines.append("    venv\\Scripts\\python scripts\\apply_proposal.py")
    lines.append("")
    return "\n".join(lines)


def proposal_filename(proposal: Proposal) -> str:
    return f"{proposal.id}.md"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_change_to_plan(plan: dict, change: ProposedChange) -> bool:
    """Apply a single change to the matching session and bump its status to
    'adjusted'. Returns True if applied, False if the session can't be found."""
    for s in plan["sessions"]:
        if s["id"] == change.session_id:
            change.apply(s)
            # Track that this session was adjusted so future syncs / proposals
            # know it's no longer pristine.
            if s.get("status", "planned") == "planned":
                s["status"] = "adjusted"
            s.setdefault("adaptations", []).append({
                "rule_id": change.rule_id,
                "field": change.field_path,
                "from": change.old_value,
                "to": change.new_value,
                "reason": change.reason,
            })
            return True
    return False
