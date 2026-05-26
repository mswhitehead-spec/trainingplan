"""Print a snapshot of the pipeline state.

What this does
--------------
Reads `config.yaml` from the project root and reports:

  - whether config.yaml exists at all,
  - whether the configured `artifacts_dir` exists on disk,
  - whether `plan.yaml` and `state.json` exist inside it,
  - and (later, once the analysis layer lands) the next planned session.

Exit codes
----------
  0 — everything we know about is fine for the current build stage
  1 — config.yaml is missing
  2 — config.yaml exists but artifacts_dir is missing

Usage
-----
  venv\\Scripts\\python scripts\\status.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp1252; force UTF-8 so emoji/non-ASCII paths work.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

# Project root is the parent of the scripts/ directory.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def main() -> int:
    print(f"project root:  {ROOT}")
    print(f"config:        {CONFIG_PATH}")

    if not CONFIG_PATH.exists():
        print()
        print("NO CONFIG.")
        print("  Copy config.yaml.example to config.yaml and edit it, then re-run.")
        return 1

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    art_dir = Path(config["artifacts_dir"])

    art_ok = art_dir.exists()
    plan_path = art_dir / "plan.yaml"
    state_path = art_dir / "state.json"

    print(f"artifacts dir: {art_dir}  [{'OK' if art_ok else 'MISSING'}]")
    print(f"  plan.yaml:   {'present' if plan_path.exists() else 'not yet'}")
    print(f"  state.json:  {'present' if state_path.exists() else 'not yet'}")

    # Athlete summary helps catch a config that's pointed at the wrong file.
    athlete = config.get("athlete", {})
    if athlete:
        print()
        print(f"athlete:       {athlete.get('name', '?')}, "
              f"age {athlete.get('age', '?')}, "
              f"max HR {athlete.get('max_hr', '?')}")

    if not art_ok:
        print()
        print("Create the artifacts dir or fix the path in config.yaml.")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
