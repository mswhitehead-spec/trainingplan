"""Rebuild the half-marathon block from 2026-08-08 to race day (2026-09-20).

Unlike generate_plan_hm.py this is NOT a from-scratch generator: it loads the
existing plan.yaml, keeps every session dated before REBUILD_FROM verbatim
(status, actual, analysis, adaptations intact), and replaces only the future.
The superseded plan is archived at history/plan-2026-hm-sub140.yaml.

Why the rebuild (audit 2026-08-07, Strava Apr 7 - Aug 6)
  The block was written on 2026-07-10 assuming a run base that never
  materialised. What actually happened in those four months:
    - 852 km cycling / 35.6 h vs 265 km running / 25.5 h. Vaetternrundan
      (315 km) sat in the middle of it.
    - Exactly two runs over 10 km in four months: 10.1 km (11 May) and
      12.0 km (18 Jul).
    - A locked-up back cost 22-29 Jul. The 8/7/6-weeks-out weeks came to
      7 / 13 / 16 km, against 35 / 34 / 21 km at the same point in the 2025
      build that produced 1:49:42.
    - Best 5 km split of the whole window: 26:00 (5:12/km). The 2025 build
      had a 24:13 parkrun.
  Riegel off that 5 km projects ~1:59. He beat Riegel by ~2 min in 2025, so
  current fitness is worth roughly 1:57. Sub-1:40 needs 4:44/km for 21.1 km
  and his fastest single kilometre in four months was 4:56 -- inside an
  interval session with jog recoveries. The A-goal was never reachable from
  this base; holding it would just paint the whole run-in amber.

What changed
  1. Target: A-goal 1:52:00 (5:18/km), B-goal 1:56:00 (5:30/km). PR pace
     (5:12 -> 1:49:42) stays as a green-light stretch off the Sep 1 checkpoint.
  2. HR zones rebuilt from measured data instead of age. See ZONE NOTE below.
  3. Long run is the whole point of the remaining six weeks:
     9 -> 11 -> 14 -> 16 -> 17 -> 10 -> race. It is the single biggest gap.
  4. Bike prescriptions mostly dropped. Adherence over the first four weeks:
     running 77%, cycling 29%, rest 0%. Prescribing rides he skips inflates
     the plan and depresses the completion stats; running is the deficit
     anyway. One optional spin survives per week.
  5. Easy pace slowed to 6:00-6:30/km. His "easy" runs have been 5:45-6:00 --
     only ~30 s/km off his threshold, which is why they accumulate fatigue
     without building base.
  6. Mobility/yoga added back (discipline "strength" -- Strava Yoga
     normalises to that, see activity.py). He built a 9-session habit
     13-21 Jul, then stopped dead when the back went.

ZONE NOTE (max HR was wrong by ~25 bpm)
  Highest heart rate recorded anywhere in four months: 154 bpm. A VO2max
  session at self-rated PE 8 peaked at 149; Vaetternrundan averaged 108.
  The old table assumed max 168 (age-derived: 220-51), so Z5 156-168 was
  unreachable and the race target 144-154 asked for the entire half at his
  observed lifetime maximum.

  Measured, from time-weighted rolling windows across the four hardest runs:
    peak sample     154
    best 10-min     147
    best 20-min     144
  Anchoring on LTHR ~146 (Friel) and cross-checking against Karvonen off a
  max of 158 (observed 154 + a few bpm for never having gone truly maximal)
  gives the table below. Both methods agree inside ~3 bpm through Z3-Z5.

  These are still an estimate. Retest with a proper maximal effort -- a hard
  5 km or hill repeats on a chest strap -- and rerun this script if it lands
  outside 155-162.

Usage:
  venv\\Scripts\\python scripts\\generate_plan_hm_rebuild.py
  venv\\Scripts\\python scripts\\generate_plan_hm_rebuild.py --print
  venv\\Scripts\\python scripts\\generate_plan_hm_rebuild.py --force
"""

from __future__ import annotations

import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.plan import load, save, validate  # noqa: E402


RACE_NAME = "Half marathon"
RACE_DATE = date(2026, 9, 20)
RACE_DISTANCE_KM = 21.1

# Everything from this date forward is regenerated; earlier sessions are kept
# exactly as they are, actuals and all.
REBUILD_FROM = date(2026, 8, 8)

RACE_TARGET_MIN = 112           # 1:52:00 -> 5:18/km
GOAL_PACE = "5:18"              # A-goal
B_GOAL_PACE = "5:30"            # -> 1:56:00, the bad-day floor
PR_PACE = "5:12"                # -> 1:49:42, last year's time; stretch only
RACE_HR_RANGE = [139, 147]      # Z4 on the rebuilt table

MAX_HR_RUN = 158
MAX_HR_BIKE = 150
LTHR = 146
RESTING_HR = 50

# Rebuilt from measured data (see ZONE NOTE). Contiguous [lo, hi] bands.
Z_RUN = {"Z1": [105, 120], "Z2": [120, 132], "Z3": [132, 139],
         "Z4": [139, 147], "Z5": [147, 158]}
Z_BIKE = {"Z1": [100, 110], "Z2": [110, 120], "Z3": [120, 130],
          "Z4": [130, 140], "Z5": [140, 150]}

# Pace bands. Easy is deliberately slower than he has been running it.
P_EASY = ["6:00", "6:30"]
P_LONG = ["5:50", "6:20"]
P_STEADY = ["5:40", "6:00"]
P_THRESHOLD = ["5:10", "5:20"]
P_GOAL = ["5:15", "5:22"]
P_SPEED = ["4:55", "5:05"]


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
        s["time_of_day"] = tod
    return s


REST_NOTES = (
    "Full rest is the default — sleep and food do the work today. "
    "If you get restless, pick ONE and keep it genuinely easy:\n"
    "  - 30-45 min walk\n"
    "  - 20-30 min very easy spin (HR under 110 — cycling Z1)\n"
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
        "lose it (Friel, Fast After 50) — and after the late-July back "
        "episode this is the session that protects the build."
    )
    return _base(d, "strength", "strength", "strength",
                 {"duration_min": minutes}, notes, tod=tod)


def mobility(d: date, minutes: int = 25, tod: str = "evening") -> dict:
    return _base(d, "mobility", "strength", "recovery",
                 {"duration_min": minutes},
                 "Yoga / mobility — hips, hamstrings, thoracic spine. You "
                 "built a nine-session habit 13-21 Jul and it stopped when "
                 "the back locked up. Restarting it is cheap insurance on "
                 "the only thing that can end this block.", tod=tod)


def easy_run(d: date, km: float, strides: bool = False, slot: str = "easy-run",
             notes: str | None = None, tod: str = "morning") -> dict:
    dur = int(round(km * 6.2 / 5) * 5)
    n = notes or (
        "Easy conversational pace, 6:00-6:30/km. This is slower than you "
        "have been running easy days — that is the point. Easy runs at "
        "5:45 sit only ~30 s/km off threshold, so they cost recovery "
        "without adding base. HR ceiling 132 (Z2)."
    )
    if strides:
        n += (" Finish with 4 x 20 s strides (fast but relaxed, full "
              "recovery) — neuromuscular sharpness, not fatigue.")
    return _base(d, slot, "running", "easy_run",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": list(P_EASY)}, n, tod=tod)


def steady_run(d: date, km: float) -> dict:
    dur = int(round(km * 5.9 / 5) * 5)
    return _base(d, "steady-z2", "running", "endurance_z2",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": list(P_STEADY)},
                 "Steady Z2, upper half of the zone ok. Smooth and even — "
                 "aerobic base, the engine for the half.")


def tempo(d: date, km: float, dur: int, notes: str, pace: list[str]) -> dict:
    # pace = the WORK-rep target, not the session average (warmup/cooldown
    # pull the average down — analysis skips session-avg pace checks for
    # tempo/intervals).
    return _base(d, "tempo", "running", "tempo",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z4",
                  "pace_range_min_per_km": list(pace)}, notes)


def intervals(d: date, km: float, dur: int, notes: str, pace: list[str]) -> dict:
    return _base(d, "intervals", "running", "intervals",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z4",
                  "pace_range_min_per_km": list(pace)}, notes)


def long_run(d: date, km: float, pace_finish_km: int = 0,
             notes: str | None = None) -> dict:
    dur = int(round(km * 6.1 / 5) * 5)
    if notes is None:
        notes = (f"Long run {km:g} km, relaxed at 5:50-6:20/km. Fuel if over "
                 f"90 min (gel at 45 min). This is the session the whole "
                 f"rebuild turns on — you have run over 10 km exactly twice "
                 f"since April.")
        if pace_finish_km:
            notes += (f" Last {pace_finish_km} km at goal pace "
                      f"({GOAL_PACE}/km — HR will climb into Z4, that's the "
                      f"point). Race pace on tired legs is the most "
                      f"race-specific stimulus in the plan.")
    return _base(d, "long-run", "running", "long_endurance",
                 {"duration_min": dur, "distance_km": km,
                  "avg_hr_zone": "Z2", "avg_hr_range": Z_RUN["Z2"],
                  "pace_range_min_per_km": list(P_LONG)}, notes)


def bike(d: date, minutes: int, tod: str = "morning") -> dict:
    return _base(d, "easy-spin", "cycling", "easy_endurance",
                 {"duration_min": minutes, "avg_hr_zone": "Z2",
                  "avg_hr_range": Z_BIKE["Z2"]},
                 "Optional easy spin — aerobic volume with zero impact. "
                 "Cycling Z2 (110-120). Skip it without guilt if the legs "
                 "want the day off; running volume is the priority now.",
                 tod=tod)


def walk(d: date, minutes: int, tod: str = "evening") -> dict:
    return _base(d, "recovery-walk", "walking", "recovery",
                 {"duration_min": minutes},
                 "Easy walk only — active recovery.", tod=tod)


def openers(d: date) -> dict:
    return _base(d, "openers", "running", "openers",
                 {"duration_min": 25, "distance_km": 4,
                  "pace_range_min_per_km": ["5:10", "5:20"]},
                 "Openers: 15 min easy, then 3 x 60 s at race effort "
                 "(5:10-5:20/km) with 2 min easy between, 5 min easy to "
                 "finish. Wake the legs up, don't tire them. You should "
                 "finish feeling springy.")


def race(d: date) -> dict:
    return _base(d, "half-marathon", "running", "race",
                 {"duration_min": RACE_TARGET_MIN,
                  "distance_km": RACE_DISTANCE_KM,
                  "avg_hr_range": RACE_HR_RANGE,
                  "avg_pace_min_per_km": GOAL_PACE,
                  "pace_range_min_per_km": list(P_GOAL)},
                 "*** RACE *** Half marathon — 21.1 km.\n\n"
                 f"A-goal 1:52 ({GOAL_PACE}/km). B-goal 1:56 "
                 f"({B_GOAL_PACE}/km). Stretch: PR pace {PR_PACE} (1:49:42) "
                 "only if the Sep 1 checkpoint was green.\n\n"
                 "This target is set off what the last four months actually "
                 "contained, not off ambition: best 5 km split 26:00, two "
                 "runs over 10 km since April, a back injury in late July. "
                 "1:52 off that base is a real six-week gain.\n\n"
                 "Pacing\n"
                 f"  Km 1-3: {GOAL_PACE}, never faster. This is the failure "
                 "mode — going out at a pace the training didn't buy turns "
                 "1:52 into 2:05.\n"
                 f"  Km 4-15: lock in 5:15-5:22, HR 139-147. Rhythm over "
                 "heroics.\n"
                 "  Km 16-21: race. Empty it in the last 3 km, not at 16.\n\n"
                 "Decision gate (set after the Sep 1 checkpoint)\n"
                 f"  Green — 3x2 km at 5:15 felt controlled → race at "
                 f"{GOAL_PACE}, and if it felt genuinely easy consider "
                 f"{PR_PACE} for a PR.\n"
                 f"  Amber — it was a fight → race at {B_GOAL_PACE} and "
                 "negative-split.\n\n"
                 "Fueling\n"
                 "  Breakfast 2.5-3 h out, familiar carbs.\n"
                 "  1 gel ~15 min before start, 1 gel around km 10-12.\n"
                 "  Water at stations — a few sips each, don't skip.\n\n"
                 "If the day goes sideways\n"
                 "  HR over 150 in the first 5 km → ease off 10 s/km "
                 "immediately.\n"
                 "  Back tightens → shorten stride, lift cadence, don't "
                 "fight it. A finished 2:00 beats a walked 18 km.")


def build_sessions() -> list[dict]:
    """Sessions from REBUILD_FROM (Sat 2026-08-08) through race day."""
    s: list[dict] = []

    # --- Bridge weekend -----------------------------------------------------
    # Deliberately light. Last three weeks were 31.5 / 7.0 / 13.2 / 16.3 km;
    # the back went in there. A 9 km long run keeps the acute:chronic ratio
    # near 1.4 instead of pushing 1.8.
    s.append(mobility(date(2026, 8, 8), 30, tod="morning"))
    s.append(long_run(date(2026, 8, 9), 9,
                      notes="Long run 9 km, easy at 5:50-6:20/km. First step "
                            "back to real long-run volume — deliberately "
                            "modest because the back is three weeks old and "
                            "last week was 16 km total. Nothing to prove "
                            "today."))

    def week(monday: date, tue_am, wed, thu_am, sun,
             tue_pm=None, thu_pm=None, sat=None, fri=None):
        s.append(rest(monday))
        s.append(tue_am(monday + timedelta(days=1)))
        if tue_pm:
            s.append(tue_pm(monday + timedelta(days=1)))
        s.append(wed(monday + timedelta(days=2)))
        s.append(thu_am(monday + timedelta(days=3)))
        if thu_pm:
            s.append(thu_pm(monday + timedelta(days=3)))
        s.append(fri(monday + timedelta(days=4)) if fri
                 else rest(monday + timedelta(days=4)))
        s.append(sat(monday + timedelta(days=5)) if sat
                 else rest(monday + timedelta(days=5)))
        s.append(sun(monday + timedelta(days=6)))

    pm_strength = lambda d: strength(d)                       # noqa: E731
    pm_mobility = lambda d: mobility(d)                       # noqa: E731

    # --- W1: 10-16 Aug — reintroduce volume, one threshold session ~31 km ---
    week(date(2026, 8, 10),
         tue_am=lambda d: tempo(d, 8, 45,
             "Threshold intro: 15 min easy, then 2 x 8 min at 5:10-5:20/km "
             "with 4 min easy between, 8 min easy to finish. Comfortably "
             "hard — short phrases, not sentences. HR will settle around "
             "142-146. First real quality since the back; if anything "
             "twinges, stop at one rep.",
             pace=P_THRESHOLD),
         tue_pm=pm_strength,
         wed=lambda d: easy_run(d, 6),
         thu_am=lambda d: easy_run(d, 6, strides=True),
         thu_pm=pm_mobility,
         sat=lambda d: bike(d, 45),
         sun=lambda d: long_run(d, 11))

    # --- W2: 17-23 Aug — threshold volume ~35 km ---------------------------
    week(date(2026, 8, 17),
         tue_am=lambda d: tempo(d, 9, 50,
             "3 x 8 min at 5:10-5:20/km with 3 min easy between. Even effort "
             "across all three — the third rep should feel like the first. "
             "Threshold volume is what moves race pace.",
             pace=P_THRESHOLD),
         tue_pm=pm_strength,
         wed=lambda d: easy_run(d, 6),
         thu_am=lambda d: steady_run(d, 6),
         thu_pm=pm_mobility,
         sat=lambda d: bike(d, 45),
         sun=lambda d: long_run(d, 14))

    # --- W3: 24-30 Aug — speed + biggest volume jump ~39 km ----------------
    week(date(2026, 8, 24),
         tue_am=lambda d: intervals(d, 10, 55,
             "Speed: 4 x 1 km at 4:55-5:05/km with 400 m jog between. Faster "
             "than race pace on purpose — it makes 5:18 feel like cruising. "
             "Full warmup (15 min + 4 strides) before rep 1. Stop at 3 reps "
             "if form falls apart; quality over count.",
             pace=P_SPEED),
         tue_pm=pm_strength,
         wed=lambda d: easy_run(d, 6),
         thu_am=lambda d: easy_run(d, 7),
         thu_pm=pm_mobility,
         sun=lambda d: long_run(d, 16))

    # --- W4: 31 Aug-6 Sep — checkpoint + peak long run ~38 km --------------
    week(date(2026, 8, 31),
         tue_am=lambda d: intervals(d, 10, 55,
             "*** CHECKPOINT *** 3 x 2 km at 5:15-5:19/km with 2 min jog "
             "between. This decides the race plan. Controlled and repeatable "
             f"→ race at {GOAL_PACE} (1:52); if it felt genuinely easy, "
             f"{PR_PACE} and a PR are on. A fight → race at {B_GOAL_PACE} "
             "(1:56). Decide today, not at km 16.",
             pace=P_GOAL),
         tue_pm=pm_strength,
         wed=lambda d: easy_run(d, 5),
         thu_am=lambda d: easy_run(d, 6),
         thu_pm=pm_mobility,
         sun=lambda d: long_run(d, 17, pace_finish_km=3,
             notes="Peak long run — 17 km. Easy at 5:50-6:20/km for the "
                   "first 14, then last 3 km at goal pace (5:18). Fuel like "
                   "race day: gel at 45 and 90 min. Longest run of the "
                   "block; after today the hay is in the barn."))

    # --- W5: 7-13 Sep — taper 1. Volume down, intensity stays ~28 km -------
    #     (Bosquet 2007, Mujika & Padilla 2003.)
    week(date(2026, 9, 7),
         tue_am=lambda d: tempo(d, 8, 45,
             f"2 x 10 min at race pace (per the Sep 1 decision: {GOAL_PACE} "
             f"or {B_GOAL_PACE}), 5 min easy between. Volume drops in taper; "
             "intensity stays — that is what preserves sharpness.",
             pace=P_GOAL),
         tue_pm=lambda d: strength(d, 30, light=True),
         wed=lambda d: easy_run(d, 5),
         thu_am=lambda d: easy_run(d, 5, strides=True),
         thu_pm=pm_mobility,
         sun=lambda d: long_run(d, 10,
             notes="Taper long run — 10 km easy, no pace work. Rehearse the "
                   "race-morning routine: same breakfast, same start time "
                   "if you can."))

    # --- W6: 14-20 Sep — race week -----------------------------------------
    rw = date(2026, 9, 14)
    s.append(rest(rw))
    s.append(easy_run(rw + timedelta(days=1), 5, strides=True,
                      notes="Easy 5 km. Strides at race pace — rhythm check, "
                            "nothing more."))
    s.append(rest(rw + timedelta(days=2)))
    s.append(openers(rw + timedelta(days=3)))
    s.append(rest(rw + timedelta(days=4),
                  "Rest. Carb intake up, hydrate, sleep is the workout. "
                  "Lay out race kit tonight."))
    s.append(easy_run(rw + timedelta(days=5), 3, slot="shakeout",
                      notes="3 km shakeout + 2 strides. Legs itchy is exactly "
                            "right — save it."))
    s.append(race(rw + timedelta(days=6)))

    return s


def build_plan(today: date, kept: list[dict]) -> dict:
    return {
        "athlete": {
            "name": "Michael",
            "age": 51,
            "max_hr": MAX_HR_RUN,
            "lthr": LTHR,
            "vo2max": 50,
            "resting_hr": RESTING_HR,
            "hr_zones": Z_RUN,
            "max_hr_cycling": MAX_HR_BIKE,
            "hr_zones_cycling": Z_BIKE,
            "zone_note": (
                "Rebuilt 2026-08-07 from measured data. Highest HR recorded "
                "in four months of Strava: 154. Best 10-min 147, best 20-min "
                "144. Old table assumed max 168 (age-derived) so Z5 was "
                "unreachable. Anchored on LTHR ~146, cross-checked against "
                "Karvonen off max 158. Estimate — retest with a maximal 5 km "
                "or hill repeats on a chest strap."
            ),
        },
        "events": [{
            "name": RACE_NAME,
            "date": RACE_DATE.isoformat(),
            "discipline": "running",
            "distance_km": RACE_DISTANCE_KM,
            "priority": "A",
            "target": {
                "time": "1:52:00",
                "avg_pace_min_per_km": GOAL_PACE,
                "avg_hr_range": RACE_HR_RANGE,
                "b_goal": {"time": "1:56:00",
                           "avg_pace_min_per_km": B_GOAL_PACE},
                "stretch_goal": {"time": "1:49:42",
                                 "avg_pace_min_per_km": PR_PACE,
                                 "condition": "only if Sep 1 checkpoint is green"},
                "last_year": "1:49:42",
            },
        }],
        "block": {
            "name": "half-marathon-2026",
            "generated": today.isoformat(),
            "revision": "rebuild-2026-08-07",
            "start_date": "2026-07-10",
            "rebuilt_from": REBUILD_FROM.isoformat(),
            "race_date": RACE_DATE.isoformat(),
            "days_in_block": (RACE_DATE - date(2026, 7, 10)).days + 1,
            "goal": "sub-1h52",
            "philosophy": (
                "Rebuilt six weeks out after a Strava audit (Apr 7 - Aug 6) "
                "showed the block was written against a run base that never "
                "existed: 852 km cycling vs 265 km running, only two runs "
                "over 10 km since April, and a locked-up back costing "
                "22-29 Jul. Best 5 km split of the window is 26:00, which "
                "projects ~1:57 — so sub-1:40 (4:44/km) was never reachable "
                "and the fastest single kilometre in four months was 4:56. "
                "New target 1:52 (5:18/km), B-goal 1:56, with last year's "
                "1:49:42 as a green-light stretch off the Sep 1 checkpoint. "
                "The six weeks are built around one thing: the long run, "
                "9 -> 11 -> 14 -> 16 -> 17, because that is the gap. Bike "
                "prescriptions mostly dropped (29% adherence vs 77% for "
                "running), easy pace slowed to 6:00-6:30 so easy days stop "
                "costing recovery, mobility restored after the back episode, "
                "and HR zones rebuilt from measured data — observed max is "
                "154, not the 168 the old table assumed."
            ),
        },
        "sessions": kept + build_sessions(),
    }


@click.command()
@click.option("--force", is_flag=True, help="Overwrite plan.yaml without confirmation.")
@click.option("--print", "print_only", is_flag=True, help="Print YAML to stdout; don't write.")
def main(force: bool, print_only: bool) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    artifacts = Path(cfg["artifacts_dir"])
    plan_path = artifacts / "plan.yaml"

    old = load(plan_path)
    kept = [s for s in old["sessions"]
            if date.fromisoformat(s["date"]) < REBUILD_FROM]
    dropped = len(old["sessions"]) - len(kept)
    with_actuals = sum(1 for s in kept if s.get("actual"))

    plan = build_plan(date.today(), kept)
    validate(plan)

    if print_only:
        click.echo(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=100))
        return

    if not force:
        click.confirm(
            f"{plan_path}: keep {len(kept)} past sessions "
            f"({with_actuals} with actuals), replace {dropped} future ones "
            f"with {len(plan['sessions']) - len(kept)} new — proceed?",
            abort=True)

    archive = artifacts / "history" / "plan-2026-hm-sub140.yaml"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        shutil.copy2(plan_path, archive)
        click.echo(f"archived previous plan -> {archive}")

    save(plan_path, plan)
    click.echo(f"wrote {plan_path}  ({len(plan['sessions'])} sessions; "
               f"kept {len(kept)} pre-{REBUILD_FROM}, "
               f"generated {len(plan['sessions']) - len(kept)} through {RACE_DATE})")


if __name__ == "__main__":
    main()
