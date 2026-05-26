"""Fetch recent activities from the Strava API.

By default just prints a summary table. Pass --import to merge them into the
local activities.jsonl store (the same store import_export.py writes to).

Usage:
  venv\\Scripts\\python scripts\\fetch.py
  venv\\Scripts\\python scripts\\fetch.py --last 20
  venv\\Scripts\\python scripts\\fetch.py --last 50 --import
  venv\\Scripts\\python scripts\\fetch.py --since 2026-05-01 --import
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.activity import load_all, merge_into, save_all  # noqa: E402
from trainingplan import strava as strava_mod  # noqa: E402


@click.command()
@click.option("--last", default=10, show_default=True, help="Max activities to fetch.")
@click.option("--since", default=None, help="Only fetch activities after this YYYY-MM-DD.")
@click.option("--import", "do_import", is_flag=True, default=False,
              help="Merge fetched activities into activities.jsonl.")
def main(last: int, since: str | None, do_import: bool) -> None:
    load_dotenv(ROOT / ".env")
    client = strava_mod.get_client()

    after = None
    if since:
        after = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)

    click.echo(f"Fetching up to {last} activities"
               f"{f' since {since}' if since else ''}...")
    activities = strava_mod.fetch_recent(client, limit=last, after=after)

    if not activities:
        click.echo("No activities returned.")
        return

    # Pretty-print.
    click.echo("")
    click.echo(f"{'Date':12s} {'Sport':10s} {'Dist (km)':>9s} {'Dur (m)':>8s} "
               f"{'Avg HR':>6s}  Name")
    click.echo("-" * 80)
    for a in activities:
        hr = f"{a.avg_hr:>6d}" if a.avg_hr else "     -"
        dist = f"{a.distance_km:>9.2f}" if a.distance_km else "        -"
        dur = f"{a.duration_min:>8.1f}" if a.duration_min else "       -"
        click.echo(f"{a.date:12s} {a.sport:10s} {dist} {dur} {hr}  {a.name}")

    if do_import:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        store = Path(cfg["artifacts_dir"]) / "activities.jsonl"
        existing = load_all(store)
        combined, added, replaced = merge_into(existing, activities)
        save_all(store, combined)
        click.echo("")
        click.echo(f"Merged into {store}")
        click.echo(f"  added:    {added}")
        click.echo(f"  replaced: {replaced}")
        click.echo(f"  total:    {len(combined)}")


if __name__ == "__main__":
    main()
