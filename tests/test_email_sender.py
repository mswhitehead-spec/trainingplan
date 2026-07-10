"""Tests for src/trainingplan/email_sender.py (rendering only — no real SMTP)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from trainingplan.email_sender import (
    _latest_pending_proposal,
    render_daily_email,
    send_email,
)


# ----- subject / body shape -----------------------------------------------

def test_subject_includes_date_and_title(mini_plan):
    subject, _ = render_daily_email(mini_plan, today=date(2026, 5, 25))
    assert "2026-05-25" in subject
    assert "easy endurance" in subject
    assert subject.startswith("[Training]")


def test_no_session_today_shows_placeholder(mini_plan):
    """A date with no plan session should emit a 'nothing today' line."""
    subject, body = render_daily_email(mini_plan, today=date(2026, 5, 24))   # day before block
    assert "no session" in subject
    assert "Nothing on the plan today" in body


def test_today_section_includes_notes_and_hr_range(mini_plan):
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 25))
    assert "[Bike] easy endurance" in body
    assert "HR target: 121–133 bpm" in body
    # Notes from the fixture include the word "easy"
    assert "easy" in body


def test_long_ride_session_includes_elevation(mini_plan):
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 30))
    assert "Elevation: 600 m" in body


def test_week_ahead_lists_seven_days(mini_plan):
    """After May 25, the next 7 days should appear in the week ahead block —
    even if there's only one or two sessions in the mini fixture, the block
    header should be present."""
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 25))
    assert "Week ahead:" in body
    # The next session in mini_plan after 25 is 2026-05-26.
    assert "Tue 26" in body
    # And the Saturday long ride should appear with the KEY tag.
    assert "Sat 30" in body
    assert "KEY" in body


def test_days_to_event_in_header(mini_plan):
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 25))
    # June 12 - May 25 = 18 days
    assert "18 day" in body


def test_race_day_header(mini_plan):
    # Inject a race session on the A-event date and update event.
    race_session = {
        "id": "2026-06-12_fri_vatternrundan",
        "date": "2026-06-12",
        "discipline": "cycling",
        "type": "race",
        "targets": {"duration_min": 840, "distance_km": 315,
                    "avg_hr_range": [121, 133]},
        "notes": "*** RACE ***",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    }
    mini_plan["sessions"].append(race_session)
    subject, body = render_daily_email(mini_plan, today=date(2026, 6, 12))
    assert "RACE DAY" in body
    assert "[Race] Vatternrundan" in subject or "[Race] Vatternrundan" in body
    assert "315km" in subject


def test_recent_completed_verdict_appears(mini_plan):
    """Mark yesterday completed; the Last-5-days section surfaces the verdict."""
    yest = mini_plan["sessions"][0]
    yest["status"] = "completed"
    yest["analysis"] = {"verdict": "on target."}
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 26))
    assert "Last 5 days:" in body
    assert "on target" in body


def test_missed_yesterday_noted(mini_plan):
    yest = mini_plan["sessions"][0]
    yest["status"] = "missed"
    _, body = render_daily_email(mini_plan, today=date(2026, 5, 26))
    assert "missed" in body.lower()


def test_pending_proposal_param_is_ignored(mini_plan, tmp_path):
    """Proposals auto-apply now; the pending_proposal arg is accepted for
    call-site compatibility but produces no callout."""
    fake = tmp_path / "2026-06-02T07-14.md"
    fake.write_text("dummy")
    _, body = render_daily_email(
        mini_plan, today=date(2026, 5, 25),
        pending_proposal=fake,
    )
    assert "Pending adaptation proposal" not in body
    assert "apply_proposal.py" not in body


# ----- pending-proposal discovery (stubbed since auto-apply) ---------------

def test_latest_pending_proposal_always_none(tmp_path):
    """Auto-apply made pending proposals obsolete — the helper is a stub."""
    art = tmp_path
    (art / "proposals").mkdir()
    (art / "proposals" / "2026-06-02T07-14.md").write_text("new")
    assert _latest_pending_proposal(art, {}) is None


# ----- send_email — mocked SMTP --------------------------------------------

def test_send_email_uses_starttls_and_login(monkeypatch):
    """Confirm we wire SMTP correctly. Mock smtplib.SMTP entirely."""
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"] = host
            sent["port"] = port
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ehlo(self): sent["ehlo"] = sent.get("ehlo", 0) + 1
        def starttls(self): sent["starttls"] = True
        def login(self, u, p): sent["user"], sent["pw"] = u, p
        def send_message(self, msg): sent["msg"] = msg

    monkeypatch.setattr("trainingplan.email_sender.smtplib.SMTP", FakeSMTP)
    send_email(
        "Subject",
        "Body",
        from_addr="a@example.com",
        to_addr="b@example.com",
        smtp_password="secret",
    )
    assert sent["host"] == "smtp.gmail.com"
    assert sent["port"] == 587
    assert sent["starttls"] is True
    assert sent["user"] == "a@example.com"
    assert sent["pw"] == "secret"
    assert sent["msg"]["Subject"] == "Subject"
    assert sent["msg"]["From"] == "a@example.com"
    assert sent["msg"]["To"] == "b@example.com"


def test_send_email_raises_without_password(monkeypatch):
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="No SMTP password set"):
        send_email("S", "B", from_addr="a@x", to_addr="b@x")


# ----- HTML rendering --------------------------------------------------------

def test_html_email_renders_sections(mini_plan):
    from trainingplan.email_sender import render_daily_email_html
    html = render_daily_email_html(mini_plan, today=date(2026, 5, 25))
    assert "max-width:600px" in html
    assert "Week ahead" in html
    # session title escaped into the card
    assert "easy" in html.lower()


def test_html_email_escapes_notes(mini_plan):
    from trainingplan.email_sender import render_daily_email_html
    mini_plan["sessions"][0]["notes"] = "watch out for <script>alert(1)</script>"
    html = render_daily_email_html(mini_plan, today=date(2026, 5, 25))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_double_day_subject_and_order(mini_plan):
    """Two sessions on one day: AM sorts before PM, subject names both."""
    d = mini_plan["sessions"][0]["date"]
    mini_plan["sessions"][0]["time_of_day"] = "evening"
    mini_plan["sessions"].append({
        "id": f"{d}_am-spin", "date": d, "discipline": "cycling",
        "type": "easy_endurance", "targets": {"duration_min": 40},
        "notes": "", "status": "planned", "actual": None, "analysis": None,
        "adaptations": [], "time_of_day": "morning",
    })
    subject, body = render_daily_email(mini_plan, today=date.fromisoformat(d))
    assert "AM Bike + PM Bike" in subject
    assert body.index("AM —") < body.index("PM —")
