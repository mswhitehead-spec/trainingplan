"""Interactively walk through the most recent proposal and accept/reject changes.

For each pending change in the latest proposal:

    [1/5] 2026-06-04_thu_easy-run · targets.duration_min: 30 → 25
          reason: race in 8 days — back off non-essentials  (rule: race_window_cap_long_duration)
          [y]es / [n]o / [a]ll-remaining-yes / [q]uit ▸ y

Accepted changes:
  - mutate plan.yaml (status becomes 'adjusted')
  - append to session.adaptations[]
  - log to state.json applied_adaptations[]

After applying, prints a one-line summary and bumps state.last_proposal_id.

Usage
-----
    venv\\Scripts\\python scripts\\apply_proposal.py            # latest proposal
    venv\\Scripts\\python scripts\\apply_proposal.py --file 2026-06-02T07-14.md
    venv\\Scripts\\python scripts\\apply_proposal.py --yes      # accept everything
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

from trainingplan import plan as plan_mod
from trainingplan import state as state_mod
from trainingplan.adapt import (
    apply_change_to_plan,
    generate_proposal,
    proposal_filename,
)
from trainingplan.heuristics import ProposedChange, load_heuristics


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _latest_proposal_file(proposals_dir: Path) -> Path | None:
    files = sorted(proposals_dir.glob("*.md"))
    return files[-1] if files else None


def _parse_changes_from_md(md_text: str) -> list[dict]:
    """Pull (session_id, field_path, old, new, rule_id, reason) tuples out of
    a proposal markdown file. We use this to drive the apply UI without
    needing to re-run the heuristics (which might give different output if
    plan/state has changed since)."""
    blocks = re.split(r"^### \[\d+\] `", md_text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for blk in blocks:
        sid = blk.split("`", 1)[0]
        field_path = _grab(blk, r"\*\*Field:\*\* `([^`]+)`")
        old = _grab(blk, r"\*\*From:\*\* `([^`]+)`")
        new = _grab(blk, r"\*\*To:\*\* `([^`]+)`")
        rule_id = _grab(blk, r"\*\*Rule:\*\* `([^`]+)`")
        reason = _grab(blk, r"\*\*Reason:\*\* (.+)")
        out.append({
            "session_id": sid,
            "field_path": field_path,
            "old_value": _coerce(old),
            "new_value": _coerce(new),
            "rule_id": rule_id,
            "reason": (reason or "").strip(),
        })
    return out


def _grab(text: str, pat: str) -> str | None:
    m = re.search(pat, text)
    return m.group(1) if m else None


def _coerce(s: str | None):
    """Best-effort parse: int, float, then fall back to string."""
    if s is None:
        return None
    s = s.strip()
    if s.lower() in {"none", "null"}:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        pass
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    return s


@click.command()
@click.option("--file", "proposal_file", default=None,
              help="Specific proposal file to apply (default: latest).")
@click.option("--yes", "accept_all", is_flag=True,
              help="Accept every change without prompting.")
@click.option("--regenerate", is_flag=True,
              help="Regenerate the proposal from current plan + heuristics "
                   "instead of reading the saved markdown.")
def main(proposal_file: str | None, accept_all: bool, regenerate: bool) -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    art_dir = Path(cfg["artifacts_dir"])

    plan_path = art_dir / "plan.yaml"
    heur_path = art_dir / "heuristics.yaml"
    state_path = art_dir / "state.json"
    proposals_dir = art_dir / "proposals"

    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)

    # ----- get the change list ---------------------------------------------
    if regenerate:
        heuristics = load_heuristics(heur_path)
        proposal = generate_proposal(plan, heuristics)
        change_dicts = [
            {
                "session_id": c.session_id, "field_path": c.field_path,
                "old_value": c.old_value, "new_value": c.new_value,
                "rule_id": c.rule_id, "reason": c.reason,
            }
            for c in proposal.changes
        ]
        proposal_id = proposal.id
    else:
        if proposal_file:
            path = proposals_dir / proposal_file
        else:
            path = _latest_proposal_file(proposals_dir) if proposals_dir.exists() else None
        if not path or not path.exists():
            raise SystemExit("No proposal file found. Run propose.py first, or "
                             "use --regenerate.")
        change_dicts = _parse_changes_from_md(path.read_text(encoding="utf-8"))
        proposal_id = path.stem

    if not change_dicts:
        click.echo("This proposal contains no changes — nothing to apply.")
        return

    # ----- interactive walkthrough -----------------------------------------
    click.echo(f"\nApplying proposal {proposal_id}  ({len(change_dicts)} change(s))\n")
    accepted: list[dict] = []
    auto_yes = accept_all

    for i, cd in enumerate(change_dicts, 1):
        click.echo(f"[{i}/{len(change_dicts)}] {cd['session_id']}")
        click.echo(f"      {cd['field_path']}:  {cd['old_value']} → {cd['new_value']}")
        click.echo(f"      reason: {cd['reason']}")
        click.echo(f"      rule:   {cd['rule_id']}")

        if auto_yes:
            click.echo("      [auto-yes]")
            decision = "y"
        else:
            decision = click.prompt(
                "      [y]es / [n]o / [a]ll-remaining-yes / [q]uit",
                default="n", show_default=False,
            ).strip().lower()

        if decision == "a":
            auto_yes = True
            decision = "y"
        if decision == "q":
            click.echo("Quit. Changes accepted so far will still be saved.")
            break

        if decision == "y":
            change = ProposedChange(
                session_id=cd["session_id"], field_path=cd["field_path"],
                old_value=cd["old_value"], new_value=cd["new_value"],
                reason=cd["reason"], rule_id=cd["rule_id"],
            )
            ok = apply_change_to_plan(plan, change)
            if not ok:
                click.echo(f"      WARNING: session {cd['session_id']} not "
                           f"found in plan — skipped.")
                continue
            accepted.append(cd)
            click.echo("      applied.")
        else:
            click.echo("      skipped.")
        click.echo("")

    if not accepted:
        click.echo("No changes accepted. plan.yaml untouched.")
        return

    # ----- persist ---------------------------------------------------------
    plan_mod.save(plan_path, plan)

    state = state_mod.load(state_path)
    state["last_proposal_id"] = proposal_id
    state.setdefault("applied_adaptations", []).append({
        "proposal_id": proposal_id,
        "accepted_at": datetime.now().isoformat(timespec="seconds"),
        "changes": accepted,
    })
    state_mod.save(state_path, state)

    click.echo(f"\nApplied {len(accepted)} change(s). plan.yaml and state.json updated.")
    click.echo("Run `publish_calendar.py` next to refresh plan.ics (STEP 6).")


if __name__ == "__main__":
    main()
