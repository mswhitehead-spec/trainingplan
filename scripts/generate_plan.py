"""Generate the initial 19-day Vätternrundan prep plan.

This is a one-shot generator. It writes `<artifacts>/plan.yaml`. After that,
the plan is the source of truth — you hand-edit it, the adaptation layer
proposes changes to it, etc. Re-running this script OVERWRITES it (with a
prompt to confirm), so only re-run if you want to start fresh.

Usage:
  venv\\Scripts\\python scripts\\generate_plan.py
  venv\\Scripts\\python scripts\\generate_plan.py --force   # overwrite without prompt
  venv\\Scripts\\python scripts\\generate_plan.py --print   # print to stdout, don't write
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.plan import karvonen_zones, save, validate  # noqa: E402


# Race + athlete constants — tweak in config.yaml; this script reads them.

RACE_NAME = "Vätternrundan"
RACE_DATE = date(2026, 6, 12)
RACE_DISTANCE_KM = 315
RACE_TARGET_TIME_H = 14
RACE_TARGET_HR_RANGE = [121, 133]  # Z2 for max=168, rest=50; recomputed if config differs.


def _sid(d: date, slot: str) -> str:
    """Compose a stable session id like 2026-05-25_mon_easy-spin."""
    return f"{d.isoformat()}_{d.strftime('%a').lower()}_{slot}"


def build_plan(
    today: date,
    race_date: date,
    athlete: dict,
    hr_zones: dict[str, list[int]],
) -> dict:
    """Build the full plan dict ready to be saved.

    The plan is anchored to `race_date`: it always spans the 19 days ending on
    race day (start = race_date - 18 days), regardless of when this script runs.
    `today` is recorded as the generation timestamp only.
    """
    z2 = hr_zones["Z2"]
    start = race_date - timedelta(days=18)

    sessions: list[dict] = []

    # --- Week 1 (build — the last real stimulus week) -----------------------

    # Day 0 (Mon 5/25) — easy spin (return-from-Tampa shake)
    d = start + timedelta(days=0)
    sessions.append({
        "id": _sid(d, "easy-spin"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "easy_endurance",
        "targets": {
            "duration_min": 45,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": (
            "Wake the legs up after travel from Tampa. Easy spin, talk-test "
            "pace. Don't push. The heat-acclimatized engine is the asset — "
            "don't waste it on day 1."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Tue 5/26 — easy run
    d = start + timedelta(days=1)
    sessions.append({
        "id": _sid(d, "easy-run"),
        "date": d.isoformat(),
        "discipline": "running",
        "type": "easy_run",
        "targets": {
            "duration_min": 30,
            "distance_km": 5,
            "avg_hr_zone": "Z2",
        },
        "notes": "Easy conversational pace. Not a workout — general aerobic only.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Wed 5/27 — Z2 endurance ride 90 min
    d = start + timedelta(days=2)
    sessions.append({
        "id": _sid(d, "z2-endurance"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "endurance_z2",
        "targets": {
            "duration_min": 90,
            "distance_km_min": 30,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": (
            "Steady Z2 for 90 min. Practice the race fueling: 60 g carb/hr "
            "starting from minute 20. Don't go above Z2 even on climbs."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Thu 5/28 — strength OR rest
    d = start + timedelta(days=3)
    sessions.append({
        "id": _sid(d, "strength"),
        "date": d.isoformat(),
        "discipline": "strength",
        "type": "strength",
        "targets": {"duration_min": 40},
        "notes": (
            "Light maintenance: core + leg stability. No new heavy work this "
            "close to a long ride. Skip if travel-tired."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Fri 5/29 — pre-long-ride shakeout
    d = start + timedelta(days=4)
    sessions.append({
        "id": _sid(d, "easy-run"),
        "date": d.isoformat(),
        "discipline": "running",
        "type": "easy_run",
        "targets": {
            "duration_min": 25,
            "distance_km": 4,
            "avg_hr_zone": "Z2",
        },
        "notes": "Short shakeout before tomorrow's long ride. Easy.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Sat 5/30 — LONG RIDE (the key session of the whole block)
    d = start + timedelta(days=5)
    sessions.append({
        "id": _sid(d, "long-ride"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "long_endurance",
        "targets": {
            "duration_min": 240,
            "distance_km": 80,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
            "elevation_gain_m": 600,
        },
        "notes": (
            "*** KEY SESSION ***\n"
            "4 hours Z2 — your longest ride in months. This is the ONLY real "
            "endurance stimulus you'll get before the race.\n"
            "Pacing: stay in Z2 ({}-{}) even when fresh. If HR drifts above, "
            "slow down or shorten — don't push through.\n"
            "Fueling: 80 g carb/hr from minute 30. Real-food + bottle "
            "rehearsal — exactly what you'll do on race day.\n"
            "Bail criteria: if HR drift exceeds +10% in the last hour, or "
            "you can't maintain Z2 power on flats, cut the ride short. The "
            "point is time-on-bike, not heroics.".format(z2[0], z2[1])
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Sun 5/31 — recovery walk
    d = start + timedelta(days=6)
    sessions.append({
        "id": _sid(d, "recovery-walk"),
        "date": d.isoformat(),
        "discipline": "walking",
        "type": "recovery",
        "targets": {"duration_min": 45},
        "notes": "Easy walk only. Legs will be tired. No cycling, no running.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # --- Week 2 (taper begins — volume down, intensity preserved) ------------

    # Mon 6/1 — rest
    d = start + timedelta(days=7)
    sessions.append({
        "id": _sid(d, "rest"),
        "date": d.isoformat(),
        "discipline": "rest",
        "type": "rest",
        "targets": {},
        "notes": "Full rest after the long ride. Sleep priority.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Tue 6/2 — easy spin
    d = start + timedelta(days=8)
    sessions.append({
        "id": _sid(d, "easy-spin"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "easy_endurance",
        "targets": {
            "duration_min": 60,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": "Spin out residual fatigue. Keep it in low Z2 — flush the legs.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Wed 6/3 — tempo opener
    d = start + timedelta(days=9)
    sessions.append({
        "id": _sid(d, "tempo-opener"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "tempo",
        "targets": {
            "duration_min": 45,
            "avg_hr_zone": "Z2",
        },
        "notes": (
            "Warm up 15 min Z2. Then 2 x 5 min in Z3 (134-144 HR) with "
            "5 min Z2 between. Cool down 10 min Z2. This is the only "
            "intensity work in the block — keep it controlled."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Thu 6/4 — easy run
    d = start + timedelta(days=10)
    sessions.append({
        "id": _sid(d, "easy-run"),
        "date": d.isoformat(),
        "discipline": "running",
        "type": "easy_run",
        "targets": {
            "duration_min": 30,
            "distance_km": 5,
            "avg_hr_zone": "Z2",
        },
        "notes": "Easy. Skip if legs feel off — taper says when in doubt, rest.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Fri 6/5 — easy spin
    d = start + timedelta(days=11)
    sessions.append({
        "id": _sid(d, "easy-spin"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "easy_endurance",
        "targets": {
            "duration_min": 45,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": "Pre-medium-ride shake. Easy.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Sat 6/6 — medium ride (last meaningful ride before race week)
    d = start + timedelta(days=12)
    sessions.append({
        "id": _sid(d, "medium-ride"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "endurance_z2",
        "targets": {
            "duration_min": 150,
            "distance_km": 50,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": (
            "2.5 h Z2. Last ride > 90 min before the race. Same fueling "
            "protocol as last Saturday. Treat as a dress rehearsal."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Sun 6/7 — recovery walk
    d = start + timedelta(days=13)
    sessions.append({
        "id": _sid(d, "recovery-walk"),
        "date": d.isoformat(),
        "discipline": "walking",
        "type": "recovery",
        "targets": {"duration_min": 30},
        "notes": "Walk only.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # --- Week 3 (sharpen and race) -------------------------------------------

    # Mon 6/8 — rest
    d = start + timedelta(days=14)
    sessions.append({
        "id": _sid(d, "rest"),
        "date": d.isoformat(),
        "discipline": "rest",
        "type": "rest",
        "targets": {},
        "notes": "Rest. Race week.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Tue 6/9 — easy spin
    d = start + timedelta(days=15)
    sessions.append({
        "id": _sid(d, "easy-spin"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "easy_endurance",
        "targets": {
            "duration_min": 45,
            "avg_hr_zone": "Z2",
            "avg_hr_range": z2,
        },
        "notes": "Easy. Wake the legs. Race week — less is more.",
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Wed 6/10 — openers
    d = start + timedelta(days=16)
    sessions.append({
        "id": _sid(d, "openers"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "openers",
        "targets": {"duration_min": 35},
        "notes": (
            "Openers: 20 min easy Z2, then 4 x 30 s strong (Z4) with 2 min "
            "easy spin between, then 5 min Z2 cool down. Total ~35 min. "
            "Goal: wake up neuromuscular system, not fatigue."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Thu 6/11 — rest (travel day; race is overnight Fri evening typically)
    d = start + timedelta(days=17)
    sessions.append({
        "id": _sid(d, "rest"),
        "date": d.isoformat(),
        "discipline": "rest",
        "type": "rest",
        "targets": {},
        "notes": (
            "Rest. Travel day to Motala (Sweden). Carb-load. Hydrate. "
            "Bike check, gear check, sleep priority. No spin today even "
            "if legs feel itchy."
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    # Fri 6/12 — RACE
    d = start + timedelta(days=18)
    assert d == race_date, f"day math wrong: {d} vs {race_date}"
    sessions.append({
        "id": _sid(d, "vatternrundan"),
        "date": d.isoformat(),
        "discipline": "cycling",
        "type": "race",
        "targets": {
            "duration_min": RACE_TARGET_TIME_H * 60,
            "distance_km": RACE_DISTANCE_KM,
            "avg_hr_zone": "Z2",
            "avg_hr_range": list(hr_zones["Z2"]),
            "avg_speed_kmh": round(RACE_DISTANCE_KM / RACE_TARGET_TIME_H, 1),
        },
        "notes": (
            "*** RACE *** Vätternrundan — 315 km. Sub-{}h target.\n"
            "\n"
            "Pacing\n"
            "  First 100 km: low Z2 ({}-{} HR). Resist the urge to go fast.\n"
            "  Middle 100 km: hold Z2; some drift to high Z2 is normal.\n"
            "  Last 100 km: hold whatever feels sustainable. Prioritize fuel.\n"
            "\n"
            "Fueling\n"
            "  Carb: 70-80 g/h from km 5. Real food + drink mix.\n"
            "  Fluids: 750 ml/h baseline; more if it's hot.\n"
            "  Caffeine: hold until the last 100 km if possible.\n"
            "\n"
            "Stops\n"
            "  Keep them short (5-10 min). Eat while moving where possible.\n"
            "  Don't sit down at controls — gets cold, hard to restart.\n"
            "\n"
            "Bail criteria\n"
            "  HR > {} for 15+ min in first 100 km → slow immediately.\n"
            "  Can't keep food down → walk, sip, restart slow.\n"
            "  Mechanical you can't fix → don't try to limp 200 km."
        ).format(
            RACE_TARGET_TIME_H,
            hr_zones["Z2"][0],
            hr_zones["Z2"][1] - 6,  # low-Z2 ceiling
            hr_zones["Z2"][1] + 4,  # warning threshold (low Z3)
        ),
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    })

    plan = {
        "athlete": {
            "name": athlete["name"],
            "age": athlete["age"],
            "max_hr": athlete["max_hr"],
            "vo2max": athlete["vo2max"],
            "resting_hr": athlete["resting_hr"],
            "hr_zones": hr_zones,
        },
        "events": [{
            "name": RACE_NAME,
            "date": race_date.isoformat(),
            "discipline": "cycling",
            "distance_km": RACE_DISTANCE_KM,
            "priority": "A",
            "target": {
                "time_h": RACE_TARGET_TIME_H,
                "avg_speed_kmh": round(RACE_DISTANCE_KM / RACE_TARGET_TIME_H, 1),
                "avg_hr_range": list(hr_zones["Z2"]),
            },
        }],
        "block": {
            "name": "vatternrundan-final-prep",
            "generated": today.isoformat(),
            "start_date": start.isoformat(),
            "race_date": race_date.isoformat(),
            "days_in_block": (race_date - start).days + 1,
            "goal": f"complete-sub-{RACE_TARGET_TIME_H}h",
            "philosophy": (
                "Recent cycling volume is ~16 km/wk; the race is 315 km in "
                "19 days. One genuine endurance stimulus (the May 30 long "
                "ride), then aggressive taper. Don't chase fitness now — it "
                "won't compound in time. Arrive fresh and fuel well."
            ),
        },
        "sessions": sessions,
    }
    return plan


@click.command()
@click.option("--force", is_flag=True, default=False,
              help="Overwrite an existing plan.yaml without prompting.")
@click.option("--print", "do_print", is_flag=True, default=False,
              help="Print the generated plan to stdout instead of writing.")
def main(force: bool, do_print: bool) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    artifacts = Path(cfg["artifacts_dir"])
    plan_path = artifacts / "plan.yaml"

    athlete_cfg = cfg["athlete"]
    zones = karvonen_zones(athlete_cfg["max_hr"], athlete_cfg["resting_hr"])

    today = date.today()
    plan = build_plan(
        today=today,
        race_date=RACE_DATE,
        athlete=athlete_cfg,
        hr_zones=zones,
    )
    validate(plan)

    if do_print:
        click.echo(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=100))
        return

    if plan_path.exists() and not force:
        click.echo(f"plan.yaml already exists at {plan_path}")
        click.echo("re-run with --force to overwrite (you will lose hand-edits).")
        sys.exit(1)

    save(plan_path, plan)
    click.echo(f"Wrote plan: {plan_path}")
    click.echo(f"Sessions:   {len(plan['sessions'])}")
    click.echo(f"Range:      {plan['sessions'][0]['date']} → {plan['sessions'][-1]['date']}")
    click.echo("")
    click.echo("HR zones (Karvonen, max={}, rest={}):".format(
        athlete_cfg["max_hr"], athlete_cfg["resting_hr"]))
    for name, (lo, hi) in zones.items():
        click.echo(f"  {name}: {lo}-{hi} bpm")


if __name__ == "__main__":
    main()
