"""Generate a plan-adaptation proposal and print it.

What it does
------------
  1. Load plan.yaml + heuristics.yaml.
  2. Run every enabled heuristic.
  3. Dedup changes (more conservative wins).
  4. Print a summary to stdout AND write a markdown file to
     `<artifacts_dir>/proposals/<proposal-id>.md`.

Nothing is applied to plan.yaml. Use `apply_proposal.py` for that.

Usage
-----
    venv\\Scripts\\python scripts\\propose.py
    venv\\Scripts\\python scripts\\propose.py --today 2026-06-05    # what-if
    venv\\Scripts\\python scripts\\propose.py --dry-run              # don't write file
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Make `import trainingplan` work when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

from trainingplan import activity as activity_mod
from trainingplan import plan as plan_mod
from trainingplan.adapt import (
    generate_proposal,
    proposal_filename,
    render_proposal_markdown,
)
from trainingplan.heuristics import load_heuristics


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@click.command()
@click.option("--today", default=None, help="Override 'today' (YYYY-MM-DD).")
@click.option("--dry-run", is_flag=True,
              help="Print only; don't write the proposal markdown file.")
def main(today: str | None, dry_run: bool) -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    art_dir = Path(cfg["artifacts_dir"])

    plan_path = art_dir / "plan.yaml"
    heur_path = art_dir / "heuristics.yaml"
    if not plan_path.exists():
        raise SystemExit(f"plan.yaml not found at {plan_path}")
    if not heur_path.exists():
        raise SystemExit(f"heuristics.yaml not found at {heur_path}")

    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)
    heuristics = load_heuristics(heur_path)
    acts_path = art_dir / "activities.jsonl"
    activities = activity_mod.load_all(acts_path) if acts_path.exists() else []

    today_d = date.fromisoformat(today) if today else date.today()
    proposal = generate_proposal(plan, heuristics, today=today_d, activities=activities)

    md = render_proposal_markdown(proposal, plan)
    click.echo(md)

    if dry_run:
        click.echo("(dry run — no file written)")
        return

    # Always write the proposal file — even when there are no changes.
    # apply_proposal.py reads the LATEST file; if we skipped writing on
    # "no changes" it would re-read an older file that may still have
    # pending items. Writing an empty-changes proposal makes apply a no-op.
    proposals_dir = art_dir / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    out_path = proposals_dir / proposal_filename(proposal)
    out_path.write_text(md, encoding="utf-8")
    if proposal.changes:
        click.echo(f"Proposal saved to: {out_path}")
    else:
        click.echo(f"No-change proposal saved to: {out_path}")


if __name__ == "__main__":
    main()
