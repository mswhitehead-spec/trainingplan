"""Tests for src/trainingplan/adapt.py — proposal aggregation, dedup, apply."""

from __future__ import annotations

from datetime import date

from trainingplan.adapt import (
    Proposal,
    _dedup,
    apply_change_to_plan,
    generate_proposal,
)
from trainingplan.heuristics import ProposedChange


def _c(sid: str, field: str, old, new, rule: str = "r", reason: str = "") -> ProposedChange:
    return ProposedChange(session_id=sid, field_path=field, old_value=old,
                          new_value=new, reason=reason, rule_id=rule)


def test_dedup_keeps_lower_duration():
    """Two rules both want to cut duration on the same session; the lower
    target should win (more conservative)."""
    a = _c("s1", "targets.duration_min", 240, 200, rule="cap_at_200")
    b = _c("s1", "targets.duration_min", 240, 150, rule="cap_at_150")
    out = _dedup([a, b])
    assert len(out) == 1
    assert out[0].new_value == 150
    # Reason from the loser is preserved in the merged reason string.
    assert "cap_at_200" in out[0].reason


def test_dedup_keeps_easier_type():
    """Two rules both flip session.type — easier wins."""
    a = _c("s1", "type", "intervals", "tempo", rule="a")
    b = _c("s1", "type", "intervals", "easy_endurance", rule="b")
    out = _dedup([a, b])
    assert len(out) == 1
    assert out[0].new_value == "easy_endurance"


def test_dedup_preserves_unrelated_changes():
    a = _c("s1", "targets.duration_min", 240, 200, rule="a")
    b = _c("s2", "type", "tempo", "easy_endurance", rule="b")
    out = _dedup([a, b])
    assert len(out) == 2


def test_apply_change_to_plan_bumps_status_and_logs():
    plan = {
        "sessions": [{
            "id": "s1", "date": "2026-06-04", "discipline": "cycling",
            "type": "long_endurance", "targets": {"duration_min": 240},
            "status": "planned", "actual": None, "analysis": None, "adaptations": [],
        }],
    }
    change = _c("s1", "targets.duration_min", 240, 180,
                rule="cap", reason="taper window")
    ok = apply_change_to_plan(plan, change)
    assert ok is True
    s = plan["sessions"][0]
    assert s["targets"]["duration_min"] == 180
    assert s["status"] == "adjusted"
    assert len(s["adaptations"]) == 1
    assert s["adaptations"][0]["rule_id"] == "cap"


def test_apply_change_to_plan_missing_session():
    plan = {"sessions": []}
    change = _c("nonexistent", "targets.duration_min", 100, 50)
    assert apply_change_to_plan(plan, change) is False


def test_generate_proposal_no_changes_for_clean_plan():
    """A plan with nothing to act on yields an empty proposal."""
    plan = {
        "athlete": {"name": "Test"},
        "events": [{"name": "Race", "date": "2026-12-01", "priority": "A"}],
        "block": {"name": "test"},
        "sessions": [{
            "id": "s1", "date": "2026-06-01", "discipline": "cycling",
            "type": "easy_endurance", "targets": {"duration_min": 45},
            "status": "planned", "actual": None, "analysis": None,
        }],
    }
    heuristics = {"rules": []}
    proposal = generate_proposal(plan, heuristics, today=date(2026, 5, 25))
    assert isinstance(proposal, Proposal)
    assert proposal.changes == []
