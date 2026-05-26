"""Regenerate plan.ics from plan.yaml and optionally mirror it to a second
location (typically the Google Drive folder so Google Calendar can subscribe
to the shared link).

What it does
------------
  1. Load config.yaml + plan.yaml.
  2. Build the calendar with `ics_export.build_calendar`.
  3. Write to `<artifacts_dir>/plan.ics` (primary copy).
  4. If `calendar.drive_mirror_path` is set in config, also copy the .ics to
     that path. This is the file you share via Drive's anyone-with-the-link
     and subscribe to in Google Calendar (see docs/calendar_subscribe.md).

Usage
-----
    venv\\Scripts\\python scripts\\publish_calendar.py
    venv\\Scripts\\python scripts\\publish_calendar.py --no-mirror   # skip Drive copy
    venv\\Scripts\\python scripts\\publish_calendar.py --start 06:30  # override default start time
"""

from __future__ import annotations

import shutil
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

from trainingplan import plan as plan_mod
from trainingplan.ics_export import write_ics


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _parse_start(s: str) -> time:
    """Parse 'HH:MM' into a time. Click's `type` doesn't include time, so we
    do it by hand."""
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


@click.command()
@click.option("--no-mirror", is_flag=True,
              help="Don't copy plan.ics to calendar.drive_mirror_path even if set.")
@click.option("--start", default="07:00",
              help="Default event start time in HH:MM (default 07:00).")
def main(no_mirror: bool, start: str) -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    art_dir = Path(cfg["artifacts_dir"])

    plan_path = art_dir / "plan.yaml"
    if not plan_path.exists():
        raise SystemExit(f"plan.yaml not found at {plan_path}")

    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)

    ics_path = art_dir / "plan.ics"
    n_bytes = write_ics(plan, ics_path, start_time=_parse_start(start))
    click.echo(f"wrote {n_bytes} bytes → {ics_path}")
    click.echo(f"sessions in calendar: {len(plan['sessions'])}")

    # Optional Drive (or anywhere) mirror — driven by config.
    cal_cfg = cfg.get("calendar") or {}
    mirror = cal_cfg.get("drive_mirror_path")
    if mirror and not no_mirror:
        mirror_path = Path(mirror)
        try:
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ics_path, mirror_path)
            click.echo(f"mirrored to: {mirror_path}")
        except OSError as e:
            click.echo(f"WARNING: mirror failed ({mirror_path}): {e}", err=True)
    elif mirror and no_mirror:
        click.echo("(mirror skipped by --no-mirror)")
    else:
        click.echo("(no calendar.drive_mirror_path in config — skipping mirror)")


if __name__ == "__main__":
    main()
