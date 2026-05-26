"""End-to-end sync: fetch from Strava, match activities to plan sessions,
analyze, write summaries, save plan + state.

What it does (in order)
-----------------------
  1. Load config.yaml → resolve artifacts_dir
  2. Fetch recent activities from Strava API → merge into activities.jsonl
  3. Load plan.yaml and activities.jsonl
  4. Match activities to sessions (greedy, ±1 day window, sport must agree)
  5. For each newly-matched session:
       - fill session.actual from the activity
       - set status = completed
       - run analyze_session() → fill session.analysis
       - render markdown to summaries/<date>_<short-id>.md
  6. Flip any past planned/adjusted sessions with no actual → status=missed
  7. Save plan.yaml back
  8. Stamp state.json with the current time

Idempotent: running twice is safe; sessions already `completed` are skipped.

Usage
-----
    venv\\Scripts\\python scripts\\sync.py
    venv\\Scripts\\python scripts\\sync.py --dry-run       # don't write anything
    venv\\Scripts\\python scripts\\sync.py --no-fetch      # skip Strava pull
    venv\\Scripts\\python scripts\\sync.py --quiet
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Make `import trainingplan` work when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Force UTF-8 stdout on Windows so emoji-free non-ASCII still renders.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml
from dotenv import load_dotenv

from trainingplan import activity as activity_mod
from trainingplan import plan as plan_mod
from trainingplan import state as state_mod
from trainingplan import strava as strava_mod
from trainingplan.analyze import analyze_session
from trainingplan.match import (
    actual_from_activity,
    mark_missed_past_sessions,
    match_activities_to_sessions,
)
from trainingplan.summarize import render_summary_markdown, summary_filename


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
# How many recent Strava activities to pull on each sync.
STRAVA_FETCH_LIMIT = 30


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _fetch_and_merge(acts_path: Path, quiet: bool) -> tuple[int, int]:
    """Pull recent activities from Strava and merge into activities.jsonl.

    Returns (added, replaced) counts.
    """
    load_dotenv(ROOT / ".env")
    client = strava_mod.get_client()
    fetched = strava_mod.fetch_recent(client, limit=STRAVA_FETCH_LIMIT)
    existing = activity_mod.load_all(acts_path) if acts_path.exists() else []
    combined, added, replaced = activity_mod.merge_into(existing, fetched)
    activity_mod.save_all(acts_path, combined)
    if not quiet and (added or replaced):
        click.echo(f"  strava pull:  +{added} new, {replaced} updated")
    return added, replaced


@click.command()
@click.option("--dry-run", is_flag=True, help="Don't write plan.yaml, state.json, or summaries.")
@click.option("--no-fetch", is_flag=True, help="Skip the Strava pull; use activities.jsonl as-is.")
@click.option("--quiet", is_flag=True, help="Suppress per-session output.")
@click.option("--today", default=None, help="Override 'today' (YYYY-MM-DD) for testing.")
def main(dry_run: bool, no_fetch: bool, quiet: bool, today: str | None) -> None:
    cfg = _load_config()
    art_dir = Path(cfg["artifacts_dir"])
    plan_path = art_dir / "plan.yaml"
    acts_path = art_dir / "activities.jsonl"
    state_path = art_dir / "state.json"
    summaries_dir = art_dir / "summaries"

    if not plan_path.exists():
        raise SystemExit(f"plan.yaml not found at {plan_path}")

    # --- Step 1: pull fresh activities from Strava ---
    if not no_fetch:
        _fetch_and_merge(acts_path, quiet)

    if not acts_path.exists():
        raise SystemExit(f"activities.jsonl not found at {acts_path} — "
                         f"run with Strava tokens set up (see docs/strava_setup.md).")

    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)
    activities = activity_mod.load_all(acts_path)

    today_d = date.fromisoformat(today) if today else date.today()

    matches = match_activities_to_sessions(
        plan["sessions"], activities, today=today_d
    )

    # Build a {session_id: session} index so we can patch in place.
    sessions_by_id = {s["id"]: s for s in plan["sessions"]}

    newly_completed = 0
    no_match = 0

    for m in matches:
        s = sessions_by_id[m.session_id]
        if m.activity is None:
            no_match += 1
            continue

        # Fill actual + analysis.
        s["actual"] = actual_from_activity(m.activity)
        # hr_stream isn't available for CSV imports yet — pass None.
        s["analysis"] = analyze_session(s, hr_stream=None)
        s["status"] = "completed"

        # Write markdown summary.
        if not dry_run:
            summaries_dir.mkdir(parents=True, exist_ok=True)
            md = render_summary_markdown(s)
            (summaries_dir / summary_filename(s)).write_text(md, encoding="utf-8")

        newly_completed += 1
        if not quiet:
            verdict = s["analysis"].get("verdict", "")
            click.echo(f"  ✓ {s['date']} {s['id'][:40]:<40}  {verdict}")

    # Mark past unmatched sessions as missed.
    flipped = mark_missed_past_sessions(plan["sessions"], today=today_d)

    # Persist.
    if not dry_run:
        plan_mod.save(plan_path, plan)
        state = state_mod.load(state_path)
        state_mod.stamp_sync(state, datetime.now())
        state_mod.save(state_path, state)

    # Report.
    click.echo("")
    click.echo(f"sync complete  ({today_d})")
    click.echo(f"  matched:      {newly_completed}")
    click.echo(f"  no match:     {no_match}")
    click.echo(f"  newly missed: {flipped}")
    if dry_run:
        click.echo("  (dry run — nothing written)")


if __name__ == "__main__":
    main()
