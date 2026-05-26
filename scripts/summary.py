"""Quick summary of the activity store: totals, sport mix, last-N-weeks load.

Usage:
  venv\\Scripts\\python scripts\\summary.py
  venv\\Scripts\\python scripts\\summary.py --weeks 12
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.activity import load_all  # noqa: E402


@click.command()
@click.option("--weeks", default=12, show_default=True,
              help="Window for the recent-load summary, in weeks.")
def main(weeks: int) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    store = Path(cfg["artifacts_dir"]) / "activities.jsonl"
    acts = load_all(store)
    if not acts:
        click.echo("no activities — run import_export.py first")
        return

    click.echo(f"Total: {len(acts)} activities")
    click.echo(f"Range: {min(a.date for a in acts)} → {max(a.date for a in acts)}")
    click.echo("")
    click.echo("All-time sport mix:")
    for sport, n in Counter(a.sport for a in acts).most_common():
        click.echo(f"  {sport:10s} {n}")

    # Recent window — prefer strava_export over garmin_csv when both exist
    # for the same date+sport, to avoid double-counting.
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()
    recent = [a for a in acts if a.date >= cutoff]
    preferred: dict[tuple[str, str], "object"] = {}
    for a in recent:
        key = (a.date, a.sport)
        if key not in preferred or a.source == "strava_export":
            preferred[key] = a
    deduped = list(preferred.values())

    click.echo("")
    click.echo(f"Last {weeks} weeks (deduped, prefer Strava): {len(deduped)} sessions")
    by_sport = Counter(a.sport for a in deduped)
    for sport, n in by_sport.most_common():
        rows = [a for a in deduped if a.sport == sport]
        km = sum(a.distance_km for a in rows)
        hr_min = sum(a.duration_min for a in rows)
        per_week_km = km / weeks if weeks else 0
        per_week_h = (hr_min / 60.0) / weeks if weeks else 0
        click.echo(f"  {sport:10s} {n:3d} sessions  "
                   f"{km:6.1f} km  ({per_week_km:4.1f} km/wk)   "
                   f"{hr_min/60:5.1f} h  ({per_week_h:4.1f} h/wk)")

    # Longest single sessions per sport — useful sanity check for plan generation.
    click.echo("")
    click.echo("Longest single session by sport (all-time):")
    for sport in ("cycling", "running"):
        rows = [a for a in acts if a.sport == sport and a.distance_km > 0]
        if not rows:
            continue
        longest = max(rows, key=lambda a: a.distance_km)
        click.echo(f"  {sport:10s} {longest.distance_km:5.1f} km on {longest.date}  ({longest.name})")


if __name__ == "__main__":
    main()
