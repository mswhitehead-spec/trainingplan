"""Pipeline state — a small JSON file at `<artifacts_dir>/state.json`.

Holds whatever's not in plan.yaml or activities.jsonl but is still useful
to remember between runs:

    - last_sync_at          : ISO timestamp of the last successful sync.py
    - last_proposal_id      : id of the most recent adaptation proposal
    - applied_adaptations[] : log of accepted proposals (id, accepted_at, summary)

Stored as JSON, not YAML, because it's machine-written-mostly and we want
straight `json.dump` indentation. Hand-edit is fine but uncommon.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def empty_state() -> dict:
    return {
        "last_sync_at": None,
        "last_proposal_id": None,
        "last_email_date": None,   # YYYY-MM-DD of the last successfully sent email
        "applied_adaptations": [],
    }


def load(path: Path) -> dict:
    """Load state.json. If it doesn't exist, return an empty state dict."""
    if not path.exists():
        return empty_state()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Don't blow up the pipeline over a corrupt state file. Caller can
        # decide whether to overwrite. We return an empty state so reads work.
        return empty_state()


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def stamp_sync(state: dict, now: datetime | None = None) -> dict:
    """Update `last_sync_at` to `now` (UTC by default). Returns the dict for chaining."""
    now = now or datetime.now()
    state["last_sync_at"] = now.isoformat(timespec="seconds")
    return state


def stamp_email(state: dict, sent_date: str) -> dict:
    """Record that today's email was sent. `sent_date` is YYYY-MM-DD."""
    state["last_email_date"] = sent_date
    return state


def email_already_sent_today(state: dict, today: str) -> bool:
    """Return True if `last_email_date` matches today (YYYY-MM-DD)."""
    return state.get("last_email_date") == today
