"""Generate the 10-week half-marathon prep plan (race: 2026-09-20).

One-shot generator, same contract as generate_plan.py: writes
`<artifacts>/plan.yaml` and OVERWRITES whatever is there (prompt to confirm).
The previous block is archived at history/plan-2026-vatternrundan.yaml.

Design (block: 2026-07-10 → 2026-09-20, 73 days):
  - Base from current fitness: 22-33 km/wk running at 5:30-6:00/km, HR 117-132.
  - Classic build: 3 base weeks -> cutback -> 4 build/peak weeks -> 2-week taper.
  - Masters-athlete bias (Friel, Fast After 50): max 2 quality days/week,
    strength until taper, strides for neuromuscular retention,
    hard days hard / easy days genuinely easy.
  - Long run peaks at 18 km two weeks out; goal-pace segments from week 6.
  - Bike stays as easy cross-training — aerobic volume without impact load.

Target: sub-1:40 (4:44/km, HR ~144-154 = Z4). AMBITIOUS by design — last
year's half was 1:49 (5:10/km), so this asks for ~9 min in one build. The
quality progression carries it: threshold intro -> threshold volume ->
1 km speed reps -> goal-pace blocks -> the week-8 checkpoint (4 x 2 km at
goal pace). If that session is a fight, the race plan drops to 4:58/km
(~1:45) — still a 4-min PR. Decide then, not on race morning.

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
RACE_TARGET_MIN = 100           # 1:40:00 -> 4:44/km (last year: 1:49 = 5:10/km)
RACE_HR_RANGE = [144, 154]      # Z4 band — ~87-92% of max 168, right for a 100-min race
GOAL_PACE = "4:44"              # A-goal pace per km
B_GOAL_PACE = "4:58"            # fallback -> 1:45 if the week-8 check says no

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
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": ["5:40", "6:10"]}, n, tod=tod)


def steady_run(d: date, km: float) -> dict:
    dur = int(round(km * 5.75 / 5) * 5)
    return _base(d, "steady-z2", "running", "endurance_z2",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": ["5:20", "5:45"]},
                 "Steady Z2, upper half of the zone ok. Smooth and even — "
                 "this is aerobic base, the engine for the half.")


def tempo(d: date, km: float, dur: int, notes: str,
          pace: tuple[str, str]) -> dict:
    # pace = the WORK-rep target, not the session average (warmup/cooldown
    # pull the average down — analysis knows to skip session-avg pace checks
    # for tempo/intervals).
    return _base(d, "tempo", "running", "tempo",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z3",
                  "pace_range_min_per_km": list(pace)}, notes)


def intervals(d: date, km: float, dur: int, notes: str,
              pace: tuple[str, str]) -> dict:
    return _base(d, "intervals", "running", "intervals",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z4",
                  "pace_range_min_per_km": list(pace)}, notes)


def long_run(d: date, km: float, pace_finish_km: int = 0,
             notes: str | None = None) -> dict:
    dur = int(round(km * 6.1 / 5) * 5)
    if notes is None:
        notes = (f"Long run {km:g} km. Relaxed Z2 — 5:40-6:00/km territory. "
                 f"Fuel if over 90 min (gel at 45 min).")
        if pace_finish_km:
            notes += (f" Last {pace_finish_km} km at goal half pace "
                      f"({GOAL_PACE}/km — HR will climb into Z4; that's the "
                      f"point). Practicing race pace on tired legs is the "
                      f"single most race-specific stimulus in the plan.")
    return _base(d, "long-run", "running", "long_endurance",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": ["5:30", "6:00"]}, notes)


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
                 {"duration_min": 25, "distance_km": 4,
                  "pace_range_min_per_km": ["4:35", "4:45"]},
                 "Openers: 15 min easy, then 3 x 60 s at race effort "
                 "(4:35-4:45/km) with 2 min easy between, 5 min easy to "
                 "finish. Wake up the legs, don't tire them. You should "
                 "finish feeling springy.")


def race(d: date) -> dict:
    return _base(d, "half-marathon", "running", "race",
                 {"duration_min": RACE_TARGET_MIN,
                  "distance_km": RACE_DISTANCE_KM,
                  "avg_hr_range": RACE_HR_RANGE,
                  "avg_pace_min_per_km": GOAL_PACE,
                  "pace_range_min_per_km": ["4:40", "4:46"]},
                 "*** RACE *** Half marathon — 21.1 km. Sub-1:40 target "
                 f"({GOAL_PACE}/km). Last year: 1:49 — this is the A-goal; "
                 f"B-goal is sub-1:45 ({B_GOAL_PACE}/km), still a 4-min PR.\n\n"
                 "Pacing\n"
                 f"  Km 1-3: {GOAL_PACE}, never faster. Banked seconds cost "
                 "minutes later.\n"
                 f"  Km 4-15: lock in 4:42-4:46, HR 144-154. Rhythm over "
                 "heroics.\n"
                 "  Km 16-21: race. Empty it in the last 3 km, not at 16.\n\n"
                 "Decision gate (set after the Sep 1 checkpoint session)\n"
                 f"  Green: 4x2km @ 4:40-4:44 felt controlled → race at "
                 f"{GOAL_PACE}.\n"
                 f"  Amber: it was a fight → race at {B_GOAL_PACE} and "
                 "negative-split.\n\n"
                 "Fueling\n"
                 "  Breakfast 2.5-3 h out, familiar carbs.\n"
                 "  1 gel ~15 min before start, 1 gel around km 10-12.\n"
                 "  Water at stations — a few sips each, don't skip.\n\n"
                 "If the day goes sideways\n"
                 "  HR > 156 in the first 5 km → ease off 10 s/km "
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
             "Threshold intro: 15 min easy, then 2 x 10 min at 4:55-5:00/km "
             "(HR drifting to ~145) with 5 min easy between, 5 min easy to "
             "finish. Comfortably hard — short phrases, not sentences. This "
             "is last year's race pace; it should feel manageable.",
             pace=("4:55", "5:00")),
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
             "3 x 10 min at 4:50-4:55/km with 4 min easy between. Even "
             "effort across all three — the third rep should feel like the "
             "first. Threshold volume is what moves the 1:40 needle.",
             pace=("4:50", "4:55")),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 14))
    week(w + timedelta(weeks=5),
         tue_am=lambda d: intervals(d, 10, 55,
             "Speed: 5 x 1 km at 4:30-4:35/km with 400 m jog between. "
             "Faster than race pace on purpose — it makes 4:44 feel like "
             "cruising. Full warmup (15 min + 4 strides) before rep 1. "
             "Stop at 4 reps if form falls apart; quality over count.",
             pace=("4:30", "4:35")),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 16, pace_finish_km=3))
    week(w + timedelta(weeks=6),
         tue_am=lambda d: tempo(d, 10, 55,
             f"2 x 15 min at goal pace ({GOAL_PACE}/km, HR settling around "
             "144-150) with 5 min easy between. First proper rehearsal of "
             "race rhythm — learn what 4:44 feels like when fresh so you "
             "can find it by feel at km 10.",
             pace=("4:42", "4:46")),
         tue_pm=pm_strength,
         wed=am_spin,
         thu_am=lambda d: easy_run(d, 8),
         thu_pm=pm_walk,
         sat=lambda d: bike(d, 60),
         sun=lambda d: long_run(d, 17, pace_finish_km=4))

    # W8: peak
    week(w + timedelta(weeks=7),
         tue_am=lambda d: intervals(d, 11, 60,
             "*** CHECKPOINT *** 4 x 2 km at 4:40-4:44/km with 2 min jog "
             "between. This decides the race plan: controlled and "
             f"repeatable → race at {GOAL_PACE} (sub-1:40). A fight → race "
             f"at {B_GOAL_PACE} (sub-1:45, still a 4-min PR). A strong "
             "finish beats a brave blowup — decide today, not at km 16.",
             pace=("4:40", "4:44")),
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
             f"2 x 10 min at race pace (per the Sep 1 decision: {GOAL_PACE} "
             f"or {B_GOAL_PACE}), 5 min easy between. Volume drops in "
             "taper; intensity stays — that's what preserves race "
             "sharpness (Bosquet 2007, Mujika & Padilla 2003).",
             pace=("4:44", "4:58")),
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
                "time": "1:40:00",
                "avg_pace_min_per_km": GOAL_PACE,
                "avg_hr_range": RACE_HR_RANGE,
                "b_goal": {"time": "1:45:00", "avg_pace_min_per_km": B_GOAL_PACE},
                "last_year": "1:49",
            },
        }],
        "block": {
            "name": "half-marathon-2026",
            "generated": today.isoformat(),
            "start_date": BLOCK_START.isoformat(),
            "race_date": RACE_DATE.isoformat(),
            "days_in_block": (RACE_DATE - BLOCK_START).days + 1,
            "goal": "sub-1h40",
            "philosophy": (
                "Coming off Vätternrundan (315 km completed 2026-06-12, "
                "~11h11m moving) with a rebuilt run habit: 22-33 km/wk at "
                "5:30-6:00/km, HR 117-132. Target sub-1:40 (4:44/km) — "
                "ambitious against last year's 1:49, so the quality "
                "progression earns it: threshold intro, threshold volume, "
                "1 km speed reps, goal-pace blocks, then the Sep 1 "
                "checkpoint (4x2 km at goal pace) locks the race plan — "
                "green: 4:44, amber: 4:58 (sub-1:45, still a 4-min PR). "
                "Two quality days max per week, strength until taper, "
                "long run peaks at 18 km with goal-pace finishes."
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
