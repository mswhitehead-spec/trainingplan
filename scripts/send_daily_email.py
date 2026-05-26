"""Send today's training email.

Designed to be run from Windows Task Scheduler each morning. With `--dry-run`
it prints the rendered email to stdout without contacting SMTP — useful for
debugging and for the initial setup test.

Required config (config.yaml):

    email:
      from: mswhitehead@gmail.com
      to:   mswhitehead@gmail.com
      smtp_host: smtp.gmail.com
      smtp_port: 587

Required env (.env):

    EMAIL_PASSWORD=<Gmail App Password>  # see docs/email_setup.md

Usage
-----
    venv\\Scripts\\python scripts\\send_daily_email.py
    venv\\Scripts\\python scripts\\send_daily_email.py --dry-run
    venv\\Scripts\\python scripts\\send_daily_email.py --today 2026-06-12
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml
from dotenv import load_dotenv

from trainingplan import plan as plan_mod
from trainingplan import state as state_mod
from trainingplan.email_sender import (
    _latest_pending_proposal,
    render_daily_email,
    send_email,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@click.command()
@click.option("--dry-run", is_flag=True,
              help="Print the email to stdout instead of sending.")
@click.option("--today", default=None, help="Override today's date (YYYY-MM-DD).")
def main(dry_run: bool, today: str | None) -> None:
    load_dotenv(ROOT / ".env")   # populates EMAIL_PASSWORD into os.environ

    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    email_cfg = cfg.get("email")
    if not email_cfg:
        raise SystemExit("config.yaml is missing the 'email' section — see "
                         "docs/email_setup.md.")
    from_addr = email_cfg.get("from")
    to_addr = email_cfg.get("to")
    if not from_addr or not to_addr:
        raise SystemExit("config.yaml email section must set 'from' and 'to'.")

    art_dir = Path(cfg["artifacts_dir"])
    plan_path = art_dir / "plan.yaml"
    state_path = art_dir / "state.json"
    if not plan_path.exists():
        raise SystemExit(f"plan.yaml not found at {plan_path}")
    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)
    state = state_mod.load(state_path)

    today_d = date.fromisoformat(today) if today else date.today()
    pending = _latest_pending_proposal(art_dir, state)

    subject, body = render_daily_email(
        plan, today=today_d, state=state, pending_proposal=pending
    )

    if dry_run:
        click.echo(f"=== Subject ===\n{subject}\n")
        click.echo(f"=== Body ===\n{body}")
        return

    send_email(
        subject,
        body,
        from_addr=from_addr,
        to_addr=to_addr,
        smtp_host=email_cfg.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(email_cfg.get("smtp_port", 587)),
    )
    click.echo(f"sent: {subject}  →  {to_addr}")


if __name__ == "__main__":
    main()
