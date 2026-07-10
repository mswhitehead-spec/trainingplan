"""Generate the 10-week half-marathon prep plan (race: 2026-09-20).

One-shot generator, same contract as generate_plan.py: writes
`<artifacts>/plan.yaml` and OVERWRITES whatever is there (prompt to confirm).
The previous block is archived at history/plan-2026-vatternrundan.yaml.

Design (block: 2026-07-10 → 2026-09-20, 73 days):
  - Base from current fitness: 22-33 km/wk running at 5:30-6:00/km, HR 117-132.
  - Classic build: 3 base weeks -> cutback -> 4 build/peak weeks -> 2-week taper.
  - Masters-athlete bias (Friel, Fast After 50): max 2 quality days/week,
    strength twice weekly until taper, strides for neuromuscular retention,
    hard days hard / easy days genuinely easy.
  - Long run peaks at 18 km two weeks out; race-pace segments appear from
    week 6 so goal pace is rehearsed, not discovered.
  - Bike stays as easy cross-training on Saturdays — aerobic volume without
    running-specific impact load.

Target: sub-1:55 (5:27/km, HR ~138-148 = high Z3). Derived from current easy
pace 5:35-5:45/km at HR ~125; reassess after the week-8 interval session.

Usage:
  venv\\Scripts\\python scripts\\generate_plan_hm.py
  venv\\Scripts\\python scripts\\generate_plan_hm.py --force
  venv\\Scripts\\python scripts\\generate_plan_hm.py --print
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

from trainingplan.plan import save, validate  # noqa: E402


RACE_NAME = "Half marathon"
RACE_DATE = date(2026, 9, 20)
RACE_DISTANCE_KM = 21.1
RACE_TARGET_MIN = 115           # 1:55:00 -> 5:27/km
RACE_HR_RANGE = [138, 148]      # high Z3 / low Z4 for max=168, rest=50

BLOCK_START = date(2026, 7, 10)

# Zone tables (Karvonen, resting 50). Running max 168; cycling max 160
# (observed sport-specific difference — see git history 2026-05-28).
Z_RUN = {"Z1": [109, 121], "Z2": [121, 133], "Z3": [133, 144],
         "Z4": [144, 156], "Z5": [156, 168]}
Z_BIKE = {"Z1": [105, 116], "Z2": [116, 127], "Z3": [127, 138],
          "Z4": [138, 149], "Z5": [149, 160]}


def _sid(d: date, slot: str) -> str:
    return f"{d.isoformat()}_{d.strftime('%a').lower()}_{slot}"


def _base(d: date, slot: str, discipline: str, stype: str,
          targets: dict, notes: str, tod: str | None = "morning") -> dict:
    s = {
        "id": _sid(d, slot),
        "date": d.isoformat(),
        "discipline": discipline,
        "type": stype,
        "targets": targets,
        "notes": notes,
        "status": "planned",
        "actual": None,
        "analysis": None,
        "adaptations": [],
    }
    if tod:
        s["time_of_day"] = tod   # morning | evening — drives .ics slot + email order
    return s


REST_NOTES = (
    "Full rest is the default — sleep and food do the work today. "
    "If you get restless, pick ONE and keep it genuinely easy:\n"
    "  - 30-45 min walk\n"
    "  - 20-30 min very easy spin (HR under 116 — cycling Z1)\n"
    "  - 15-20 min mobility / stretching\n"
    "Nothing that touches Z2. Optional movement must not cost recovery."
)


def rest(d: date, notes: str = REST_NOTES) -> dict:
    return _base(d, "rest", "rest", "rest", {}, notes, tod=None)


def strength(d: date, minutes: int = 40, light: bool = False,
             tod: str = "evening") -> dict:
    notes = (
        "Light maintenance only: core, glute bridges, calf raises. Nothing "
        "that creates soreness — taper protects freshness."
        if light else
        "Strength: hips, glutes, calves, core. Single-leg RDLs, step-ups, "
        "calf raises, Copenhagen planks. Masters athletes keep strength or "
        "lose it (Friel, Fast After 50) — this is injury armor for the "
        "running build. Evening slot: the morning run is done, so quality "
        "stays on quality days and easy days stay easy."
    )
    return _base(d, "strength", "strength", "strength",
                 {"duration_min": minutes}, notes, tod=tod)


def easy_run(d: date, km: float, strides: bool = False, slot: str = "easy-run",
             notes: str | None = None, tod: str = "morning") -> dict:
    dur = int(round(km * 5.9 / 5) * 5)
    n = notes or "Easy conversational pace. Z2 ceiling — slower is fine."
    if strides:
        n += (" Finish with 4 x 20 s strides (fast but relaxed, full "
              "recovery) — neuromuscular sharpness, not fatigue.")
    return _base(d, slot, "running", "easy_run",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"]}, n, tod=tod)


def steady_run(d: date, km: float) -> dict:
    dur = int(round(km * 5.75 / 5) * 5)
    return _base(d, "steady-z2", "running", "endurance_z2",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"]},
                 "Steady Z2, upper half of the zone ok. Smooth and even — "
                 "this is aerobic base, the engine for the half.")


def tempo(d: date, km: float, dur: int, notes: str) -> dict:
    return _base(d, "tempo", "running", "tempo",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z3"}, notes)


def intervals(d: date, km: float, dur: int, notes: str) -> dict:
    return _base(d, "intervals", "running", "intervals",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z3"}, notes)


def long_run(d: date, km: float, pace_finish_km: int = 0,
             notes: str | None = None) -> dict:
    dur = int(round(km * 6.1 / 5) * 5)
    if notes is None:
        notes = (f"Long run {km:g} km. Relaxed Z2 — 5:50-6:10/km territory. "
                 f"Fuel if over 90 min (gel at 45 min).")
        if pace_finish_km:
            notes += (f" Last {pace_finish_km} km at goal half pace "
                      f"(~5:27/km, HR drifting into Z3 is expected). "
                      f"Practicing race pace on tired legs is the single "
                      f"most race-specific stimulus in the plan.")
    return _base(d, "long-run", "running", "long_endurance",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"]}, notes)


def bike(d: date, minutes: int, tod: str = "morning") -> dict:
    return _base(d, "easy-spin", "cycling", "easy_endurance",
                 {"duration_min": minutes, "avg_hr_zone": "Z2",
                  "avg_hr_range": Z_BIKE["Z2"]},
                 "Easy spin — aerobic volume with zero impact. Cycling Z2 "
                 "(116-127). Legs should feel better after than before.",
                 tod=tod)


def walk(d: date, minutes: int, tod: str = "morning") -> dict:
    return _base(d, "recovery-walk", "walking", "recovery",
                 {"duration_min": minutes},
                 "Easy walk only — active recovery.", tod=tod)


def openers(d: date) -> dict:
    return _base(d, "openers", "running", "openers",
                 {"duration_min": 25, "distance_km": 4},
                 "Openers: 15 min easy, then 3 x 60 s at race effort with "
                 "2 min easy between, 5 min easy to finish. Wake up the "
                 "legs, don't tire them. You should finish feeling springy.")


def race(d: date) -> dict:
    return _base(d, "half-marathon", "running", "race",
                 {"duration_min": RACE_TARGET_MIN,
                  "distance_km": RACE_DISTANCE_KM,
                  "avg_hr_range": RACE_HR_RANGE,
                  "avg_pace_min_per_km": "5:27"},
                 "*** RACE *** Half marathon — 21.1 km. Sub-1:55 target "
                 "(5:27/km).\n\n"
                 "Pacing\n"
                 "  Km 1-3: AT goal pace, not under it. It must feel easy.\n"
                 "  Km 4-15: settle at 5:25-5:30, HR 138-148. Lock in.\n"
                 "  Km 16-21: whatever is left. This is where the taper "
                 "pays out.\n\n"
                 "Fueling\n"
                 "  Breakfast 2.5-3 h out, familiar carbs.\n"
                 "  1 gel ~15 min before start, 1 gel around km 10-12.\n"
                 "  Water at stations — a few sips each, don't skip.\n\n"
                 "If the day goes sideways\n"
                 "  HR > 150 in the first 5 km → ease off 10 s/km "
                 "immediately.\n"
                 "  Side stitch → exhale hard on the opposite foot strike, "
                 "shorten stride until it clears.")


def build_sessions() -> list[dict]:
    s: list[dict] = []
    d0 = BLOCK_START  # Fri 2026-07-10

    # --- Lead-in weekend ----------------------------------------------------
    s.append(rest(d0, "Rest — you ran yesterday. Block starts with fresh legs."))
    s.append(easy_run(d0 + timedelta(days=1), 6))
    s.append(long_run(d0 + timedelta(days=2), 10,
                      notes="First long run of the block: 10 km relaxed Z2. "
                            "Sets the baseline the next ten weeks build on."))

    # Weekly template. Doubles land on Tue (AM run + PM strength) and Thu
    # (AM run + PM walk) — Michael trains early morning and evening, so the
    # plan structures that instead of leaving the second session unplanned.
    # Mon + Fri stay rest (with optional-activity notes in REST_NOTES).
    def week(monday: date, tue_am, wed, thu_am, sat, sun,
             tue_pm=None, thu_pm=None):
        s.append(rest(monday))
        s.append(tue_am(monday + timedelta(days=1)))
        if tue_pm:
            s.append(tue_pm(monday + timedelta(days=1)))
        s.append(wed(monday + timedelta(days=2)))
        s.append(thu_am(monday + timedelta(days=3)))
        if thu_pm:
            s.append(thu_pm(monday + timedelta(days=3)))
        s.append(rest(monday + timedelta(days=4)))
        s.append(sat(monday + timedelta(days=5)))
        s.append(sun(monday + timedelta(days=6)))

    w = date(2026, 7, 13)
    pm_strength = lambda d: strength(d)                       # noqa: E731
    pm_walk = lambda d: walk(d, 30, tod="evening")            # noqa: E731
    am_spin = lambda d: bike(d, 40)                           # noqa: E731

    # W1-2: base
    week(w,
         tue_am=lambda d: easy_run(d, 6, strides=True),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: steady_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 45),
         sun=lambda d: long_run(d, 11))
    week(w + timedelta(weeks=1),
         tue_am=lambda d: easy_run(d, 7, strides=True),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: steady_run(d, 8),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 12))

    # W3: first quality
    week(w + timedelta(weeks=2),
         tue_am=lambda d: tempo(d, 8, 45,
             "Tempo intro: 15 min easy, then 2 x 10 min at Z3 (133-144) "
             "with 5 min easy between, 5 min easy to finish. Comfortably "
             "hard — you could speak in short phrases, not sentences."),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 6),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 13))

    # W4: cutback
    week(w + timedelta(weeks=3),
         tue_am=lambda d: easy_run(d, 6),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7, strides=True),
         sat=lambda d: walk(d, 45),
         sun=lambda d: long_run(d, 10,
             notes="Cutback long run — 10 km, genuinely easy. Absorption "
                   "week: the fitness from weeks 1-3 lands now."))

    # W5-7: build
    week(w + timedelta(weeks=4),
         tue_am=lambda d: tempo(d, 9, 50,
             "3 x 10 min at Z3 with 4 min easy between. Even effort across "
             "all three — the third rep should feel like the first."),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 14))
    week(w + timedelta(weeks=5),
         tue_am=lambda d: tempo(d, 10, 55,
             "2 x 15 min at goal half-marathon effort (~5:27/km, HR high "
             "Z3) with 5 min easy between. First proper rehearsal of race "
             "rhythm."),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 16, pace_finish_km=3))
    week(w + timedelta(weeks=6),
         tue_am=lambda d: tempo(d, 9, 50,
             "25 min continuous at Z3. One block, steady effort — mental "
             "rehearsal for holding pace when it stops feeling fresh."),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 8),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 17, pace_finish_km=4))

    # W8: peak
    week(w + timedelta(weeks=7),
         tue_am=lambda d: intervals(d, 11, 60,
             "4 x 2 km at goal half pace (5:25-5:30/km) with 2 min jog "
             "between. The fitness check: if these feel controlled, "
             "sub-1:55 is on. If they're a fight, adjust race target to "
             "5:35/km (1:58) — a strong finish beats a brave blowup."),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: walk(d, 30),
         sun=lambda d: long_run(d, 18,
             notes="Peak long run — 18 km relaxed Z2, fuel like race day "
                   "(gel at 45 and 90 min). Longest run of the block; "
                   "after today the hay is in the barn."))

    # W9: taper 1 — volume down, doubles get lighter (light strength, no
    # second bike). Intensity stays (Bosquet 2007).
    week(w + timedelta(weeks=8),
         tue_am=lambda d: tempo(d, 8, 45,
             "2 x 10 min at goal half pace, 5 min easy between. Volume "
             "drops in taper; intensity stays — that's what preserves "
             "race sharpness (Bosquet 2007, Mujika & Padilla 2003)."),
         tue_pm=lambda d: strength(d, 30, light=True),
         wed=lambda d: bike(d, 30),
         thu_am=lambda d: easy_run(d, 6),
         sat=lambda d: bike(d, 45),
         sun=lambda d: long_run(d, 12,
             notes="Taper long run — 12 km easy. No pace work. Rehearse "
                   "race-morning routine: same breakfast, same start time "
                   "if possible."))

    # W10: race week
    rw = w + timedelta(weeks=9)
    s.append(rest(rw))
    s.append(easy_run(rw + timedelta(days=1), 5, strides=True,
                      notes="Easy 5 km. Strides at race pace — rhythm "
                            "check, nothing more."))
    s.append(rest(rw + timedelta(days=2)))
    s.append(openers(rw + timedelta(days=3)))
    s.append(rest(rw + timedelta(days=4),
                  "Rest. Carb intake up, hydrate, sleep is the workout. "
                  "Lay out race kit tonight."))
    s.append(easy_run(rw + timedelta(days=5), 3,
                      slot="shakeout",
                      notes="3 km shakeout + 2 strides. Legs itchy is "
                            "exactly right — save it."))
    s.append(race(rw + timedelta(days=6)))

    return s


def build_plan(today: date) -> dict:
    return {
        "athlete": {
            "name": "Michael",
            "age": 51,
            "max_hr": 168,
            "vo2max": 50,
            "resting_hr": 50,
            "hr_zones": Z_RUN,
            "max_hr_cycling": 160,
            "hr_zones_cycling": Z_BIKE,
        },
        "events": [{
            "name": RACE_NAME,
            "date": RACE_DATE.isoformat(),
            "discipline": "running",
            "distance_km": RACE_DISTANCE_KM,
            "priority": "A",
            "target": {
                "time": "1:55:00",
                "avg_pace_min_per_km": "5:27",
                "avg_hr_range": RACE_HR_RANGE,
            },
        }],
        "block": {
            "name": "half-marathon-2026",
            "generated": today.isoformat(),
            "start_date": BLOCK_START.isoformat(),
            "race_date": RACE_DATE.isoformat(),
            "days_in_block": (RACE_DATE - BLOCK_START).days + 1,
            "goal": "sub-1h55",
            "philosophy": (
                "Coming off Vätternrundan (315 km completed 2026-06-12, "
                "~11h11m moving) with a rebuilt run habit: 22-33 km/wk at "
                "5:30-6:00/km, HR 117-132. Ten weeks is enough runway to "
                "build properly: 3 base weeks, cutback, 4 build/peak weeks "
                "with race-pace work, 2-week taper. Two quality days max "
                "per week, strength until taper, long run peaks at 18 km. "
                "Target 1:55; the week-8 interval session is the go/no-go "
                "check on that number."
            ),
        },
        "sessions": build_sessions(),
    }


@click.command()
@click.option("--force", is_flag=True, help="Overwrite plan.yaml without confirmation.")
@click.option("--print", "print_only", is_flag=True, help="Print YAML to stdout; don't write.")
def main(force: bool, print_only: bool) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    plan_path = Path(cfg["artifacts_dir"]) / "plan.yaml"

    plan = build_plan(date.today())
    validate(plan)

    if print_only:
        click.echo(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=100))
        return

    if plan_path.exists() and not force:
        click.confirm(f"{plan_path} exists — overwrite?", abort=True)

    save(plan_path, plan)
    n = len(plan["sessions"])
    click.echo(f"wrote {plan_path}  ({n} sessions, "
               f"{BLOCK_START} → {RACE_DATE})")


if __name__ == "__main__":
    main()
