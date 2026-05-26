"""Import historical activities from local CSV exports.

Looks in `<artifacts_dir>` for:
  - `export_<id>_strava/activities.csv`   (Strava bulk export)
  - `Activities_garmin.csv`               (Garmin Connect export)

Loads everything found, merges with `<artifacts_dir>/activities.jsonl` keyed
by (source, source_id), and writes the merged store back.

Usage:
  venv\\Scripts\\python scripts\\import_export.py
  venv\\Scripts\\python scripts\\import_export.py --strava path\\to\\activities.csv
  venv\\Scripts\\python scripts\\import_export.py --garmin path\\to\\garmin.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp1252 — emoji in activity names (e.g. "🥵") would
# crash echo(). Force the stdout encoding to UTF-8 early.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

# Make 'trainingplan' importable when running as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.activity import Activity, load_all, merge_into, save_all  # noqa: E402
from trainingplan.importers import garmin_csv, strava_export  # noqa: E402


def _path_from_config(cfg: dict, key: str) -> Path | None:
    """Resolve `sources.<key>` from config into a Path, if set and nonempty."""
    raw = (cfg.get("sources") or {}).get(key)
    if not raw:
        return None
    p = Path(raw)
    return p if p.exists() else None


@click.command()
@click.option("--strava", "strava_arg", type=click.Path(exists=True, path_type=Path),
              default=None, help="Override path to Strava activities.csv.")
@click.option("--garmin", "garmin_arg", type=click.Path(exists=True, path_type=Path),
              default=None, help="Override path to Garmin Connect Activities CSV.")
def main(strava_arg: Path | None, garmin_arg: Path | None) -> None:
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        click.echo("No config.yaml — copy config.yaml.example first.", err=True)
        sys.exit(1)
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    artifacts_dir = Path(cfg["artifacts_dir"])
    if not artifacts_dir.exists():
        click.echo(f"artifacts_dir does not exist: {artifacts_dir}", err=True)
        sys.exit(2)

    store = artifacts_dir / "activities.jsonl"
    existing = load_all(store)
    click.echo(f"Existing activities in store: {len(existing)}")

    strava_path = strava_arg or _path_from_config(cfg, "strava_export_csv")
    garmin_path = garmin_arg or _path_from_config(cfg, "garmin_csv")

    new: list[Activity] = []

    if strava_path:
        click.echo(f"Strava bulk export: {strava_path}")
        s = strava_export.load_activities(strava_path)
        click.echo(f"  loaded {len(s)} activities")
        new.extend(s)
    else:
        click.echo("No Strava bulk export found.")

    if garmin_path:
        click.echo(f"Garmin CSV: {garmin_path}")
        g = garmin_csv.load_activities(garmin_path)
        click.echo(f"  loaded {len(g)} activities")
        new.extend(g)
    else:
        click.echo("No Garmin CSV found.")

    if not new:
        click.echo("Nothing to import.")
        return

    combined, added, replaced = merge_into(existing, new)
    written = save_all(store, combined)

    click.echo("")
    click.echo(f"Store: {store}")
    click.echo(f"  added:    {added}")
    click.echo(f"  replaced: {replaced}")
    click.echo(f"  total:    {written}")

    # Show a tiny preview of the most recent few.
    click.echo("")
    click.echo("Most recent 5:")
    for a in combined[:5]:
        hr = f" HR {a.avg_hr}" if a.avg_hr else ""
        dist = f" {a.distance_km:.1f}km" if a.distance_km else ""
        click.echo(f"  {a.date}  {a.sport:8s} {a.source:14s}{dist}{hr}  {a.name}")


if __name__ == "__main__":
    main()
