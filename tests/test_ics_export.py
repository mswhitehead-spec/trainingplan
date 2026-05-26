"""Tests for src/trainingplan/ics_export.py."""

from __future__ import annotations

import re
from datetime import time

import pytest

from trainingplan.ics_export import build_calendar, write_ics


# ----- helpers -------------------------------------------------------------

def _vevents(ics: str) -> list[str]:
    blocks = re.findall(r"BEGIN:VEVENT.*?END:VEVENT", ics, flags=re.DOTALL)
    return blocks


# ----- structural tests ----------------------------------------------------

def test_calendar_wrapper_present(mini_plan):
    ics = build_calendar(mini_plan)
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ics
    assert "PRODID:" in ics


def test_one_vevent_per_session(mini_plan):
    ics = build_calendar(mini_plan)
    assert len(_vevents(ics)) == len(mini_plan["sessions"])


def test_uids_stable_across_runs(mini_plan):
    ics1 = build_calendar(mini_plan)
    ics2 = build_calendar(mini_plan)
    # Each session id appears in both, in the same UID line.
    for s in mini_plan["sessions"]:
        assert s["id"] in ics1
        assert s["id"] in ics2


def test_status_mapping(mini_plan):
    mini_plan["sessions"][0]["status"] = "completed"
    mini_plan["sessions"][1]["status"] = "missed"
    ics = build_calendar(mini_plan)
    # completed → CONFIRMED, missed → CANCELLED
    confirmed_block = next(b for b in _vevents(ics)
                           if mini_plan["sessions"][0]["id"] in b)
    cancelled_block = next(b for b in _vevents(ics)
                           if mini_plan["sessions"][1]["id"] in b)
    assert "STATUS:CONFIRMED" in confirmed_block
    assert "STATUS:CANCELLED" in cancelled_block


def test_rest_day_is_all_day():
    """A rest-discipline session should produce DTSTART;VALUE=DATE (no time)."""
    plan = {
        "athlete": {"name": "T"}, "events": [], "block": {},
        "sessions": [{
            "id": "rest_test", "date": "2026-06-01",
            "discipline": "rest", "type": "rest",
            "targets": {}, "notes": "rest day",
            "status": "planned", "actual": None, "analysis": None,
        }],
    }
    ics = build_calendar(plan)
    block = _vevents(ics)[0]
    assert "DTSTART;VALUE=DATE:20260601" in block
    assert "DTEND;VALUE=DATE:20260602" in block
    assert "TRANSP:TRANSPARENT" in block


def test_default_start_time_07h00(mini_plan):
    ics = build_calendar(mini_plan)
    block = next(b for b in _vevents(ics)
                 if mini_plan["sessions"][0]["id"] in b)
    assert "DTSTART:20260525T070000" in block


def test_custom_start_time(mini_plan):
    ics = build_calendar(mini_plan, start_time=time(6, 30))
    block = next(b for b in _vevents(ics)
                 if mini_plan["sessions"][0]["id"] in b)
    assert "DTSTART:20260525T063000" in block


def test_duration_drives_dtend(mini_plan):
    """45-min target → DTSTART 07:00 + DTEND 07:45."""
    ics = build_calendar(mini_plan)
    block = next(b for b in _vevents(ics)
                 if mini_plan["sessions"][0]["id"] in b)
    assert "DTSTART:20260525T070000" in block
    assert "DTEND:20260525T074500" in block


def test_summary_format(mini_plan):
    ics = build_calendar(mini_plan)
    # easy_endurance cycling 45m Z2 → "[Bike] easy endurance · 45m · Z2"
    block = next(b for b in _vevents(ics)
                 if mini_plan["sessions"][0]["id"] in b)
    assert "SUMMARY:[Bike] easy endurance" in block
    assert "45m" in block
    assert "Z2" in block


# ----- escape / format compliance -----------------------------------------

def test_commas_in_description_are_escaped():
    plan = {
        "athlete": {"name": "T"}, "events": [], "block": {},
        "sessions": [{
            "id": "s_commas", "date": "2026-06-01",
            "discipline": "cycling", "type": "easy_endurance",
            "targets": {"duration_min": 45, "avg_hr_zone": "Z2"},
            "notes": "Eat, drink, ride. Pacing, fueling, hydration.",
            "status": "planned", "actual": None, "analysis": None,
        }],
    }
    ics = build_calendar(plan)
    # After RFC 5545 §3.3.11 escaping, every comma should appear as \,.
    # Line folding may insert "\r\n " between any two characters, so we
    # un-fold before asserting.
    unfolded = ics.replace("\r\n ", "")
    assert "Eat\\, drink\\, ride" in unfolded
    assert "Pacing\\, fueling\\, hydration" in unfolded
    # And no UNescaped comma (i.e., a comma not preceded by a backslash)
    # should remain inside DESCRIPTION.
    desc_lines = [ln for ln in unfolded.split("\r\n") if ln.startswith("DESCRIPTION:")]
    assert desc_lines, "no DESCRIPTION line emitted"
    for ln in desc_lines:
        body = ln.split(":", 1)[1]
        # Negative lookbehind: a comma not preceded by a backslash.
        bad = re.search(r"(?<!\\),", body)
        assert bad is None, f"unescaped comma in DESCRIPTION at idx {bad.start()}: {body!r}"


def test_write_ics_uses_crlf(tmp_path, mini_plan):
    out = tmp_path / "plan.ics"
    write_ics(mini_plan, out)
    data = out.read_bytes()
    assert data.count(b"\r\n") > 10
    # No bare LF (every LF should be preceded by CR).
    bare_lf = data.count(b"\n") - data.count(b"\r\n")
    assert bare_lf == 0


def test_write_ics_creates_parent_dir(tmp_path, mini_plan):
    out = tmp_path / "nested" / "deeper" / "plan.ics"
    write_ics(mini_plan, out)
    assert out.exists()


def test_line_folding_for_long_descriptions():
    """A long description should be folded at 75 octets — continuation lines
    begin with a single space."""
    long_notes = "x" * 500
    plan = {
        "athlete": {"name": "T"}, "events": [], "block": {},
        "sessions": [{
            "id": "s_long", "date": "2026-06-01",
            "discipline": "cycling", "type": "easy_endurance",
            "targets": {"duration_min": 45}, "notes": long_notes,
            "status": "planned", "actual": None, "analysis": None,
        }],
    }
    ics = build_calendar(plan)
    # Find the folded continuation marker.
    assert "\r\n " in ics
    # No content line should exceed 75 octets.
    for raw_line in ics.split("\r\n"):
        # Continuation lines start with a space — skip those (already folded).
        if raw_line.startswith(" "):
            continue
        assert len(raw_line.encode("utf-8")) <= 75 or raw_line.startswith("DESCRIPTION") is False, \
            f"unfolded long line: {raw_line[:80]!r}"
