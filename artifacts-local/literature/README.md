# Literature backing the adaptation heuristics

Each rule in `heuristics.yaml` cites entries from this bibliography. Reviewing
this file is the easiest way to audit *why* the pipeline proposes what it does
— and to challenge a rule if the science doesn't actually support it.

Last updated: 2026-05-25.

---

## 1. Mujika, I. & Padilla, S. (2003)
**"Scientific Bases for Precompetition Tapering Strategies."**
*Medicine & Science in Sports & Exercise* 35(7):1182–1187.
PMID: [12840640](https://pubmed.ncbi.nlm.nih.gov/12840640/) · DOI: 10.1249/01.MSS.0000074448.73931.11 · Open PDF: <http://robin.candau.free.fr/Mujika_Padilla.pdf>

**Foundational taper review.** Numeric guidance:

- Volume reduction during taper: **60–90%**
- Frequency reduction: **no more than 20%**
- Optimal taper duration range: **4 to >28 days**
- Progressive **nonlinear** tapers outperform step tapers
- Typical performance gain: ~3% (range 0.5–6.0%)
- Mechanism: positive changes in cardiorespiratory, metabolic, hematological,
  hormonal, neuromuscular, and psychological status

Used by rules: `race_window_cap_long_duration`, `race_week_cap_intensity`.

---

## 2. Bosquet, L., Montpetit, J., Arvisais, D. & Mujika, I. (2007)
**"Effects of Tapering on Performance: A Meta-Analysis."**
*Medicine & Science in Sports & Exercise* 39(8):1358–1365.
PMID: [17762369](https://pubmed.ncbi.nlm.nih.gov/17762369/) · DOI: 10.1249/mss.0b013e31806010e0

Meta-analysis of 27 studies. **Conclusion:** a **2-week taper with
exponentially reduced volume of 41–60%** is the most efficient strategy to
maximize performance gains. Intensity should be maintained.

Used by rules: `race_window_cap_long_duration`, `race_week_cap_intensity`.

---

## 3. Bouzid, M.A. et al. (2023)
**"Effects of tapering on performance in endurance athletes: a systematic
review and meta-analysis."**
PMC: [PMC10171681](https://pmc.ncbi.nlm.nih.gov/articles/PMC10171681/) · open access

**Most recent meta-analysis (14 studies).** Refines Bosquet 2007:

- **Optimal taper duration: 8–14 days** (largest effect size). ≤7 d and
  15–21 d also produce positive effects.
- **Volume reduction: 41–60% optimal.** <40% is insufficient (residual fatigue);
  >60% degrades training quality.
- **Intensity: maintain** (SMD −0.55 in favor of maintained intensity; reducing
  intensity yields SMD 0.25 — not significant).
- **Frequency: maintain.**
- Combining taper with **pre-taper overload** produced the best outcomes.

**Important nuance for Michael's case:** the meta-analysis pool is mostly
elite athletes peaking for races ≤marathon distance. For a 315 km
ultra-endurance event where the goal is **safe completion**, not optimized
performance, *more* conservative taper is defensible. The heuristic
`race_week_cap_intensity` deliberately reduces intensity in the final week,
which is more cautious than the literature recommends for elite peaking. This
is a deliberate trade-off, not an evidence violation.

Used by rules: `race_window_cap_long_duration`, `race_week_cap_intensity`.

---

## 4. Friel, J. — *The Cyclist's Training Bible*, 4th ed. (VeloPress, 2018)

The most widely-used self-coaching reference for endurance cyclists.
Not open access. Relevant chapters cited:

- **Ch. 4** — long-ride heart-rate drift ("aerobic decoupling") as a fatigue
  indicator. Threshold convention: <5% drift indicates clean aerobic
  fitness; >5% suggests more base needed.
- **Ch. 9** — overreaching signals (elevated HR at fixed workload, declining
  performance, mood disturbance).
- **Ch. 13** — taper protocols. Friel's recommendation: a 2-3 week
  pre-taper "Peak" block followed by a sharpening week. Missed long sessions
  in the final 3 weeks should NOT be made up.

Used by rules: `hr_drift_high`, `two_hot_sessions`,
`missed_long_no_makeup_short_window`.

---

## 5. Friel, J. — *Fast After 50* (VeloPress, 2015)

Friel's masters-athlete-specific guide (highly relevant at age 51). Key
themes used here:

- Recovery requirements grow with age — masters athletes need MORE rest
  between hard sessions, not the same as their younger selves.
- VO2max declines modestly until ~50 then accelerates; trainability is
  preserved but adaptation timelines lengthen.
- Strength work and high-intensity intervals are the two most age-protective
  stimuli, but their recovery cost is also higher.

Used by rules: `race_window_cap_long_duration` (the duration-cap value of
180 min is informed by Friel's masters taper recommendations).

---

## 6. Aerobic-decoupling / HR-drift convention

Multiple practitioner sources converge on the same threshold convention
(<5% clean, >5% needs more base, >10% high fatigue):

- [TrainingPeaks — "Aerobic Decoupling and Heart Rate Drift Explained"](https://www.trainingpeaks.com/coach-blog/aerobic-endurance-and-decoupling/)
- [Uphill Athlete — "Understanding the Heart Rate Drift Test"](https://uphillathlete.com/aerobic-training/heart-rate-drift/)
- [Roadman Cycling — Aerobic Decoupling for Cyclists (2026)](https://roadmancycling.com/blog/aerobic-decoupling-cycling-cardiac-drift)

Phil Maffetone is credited with the original "low-HR aerobic test" protocol
(MAF test, 180−age) from the 1980s; Friel formalized the percentage drift
metric in cycling.

Recent academic work: ["Quantifying training response in cycling based on
cardiovascular drift using machine learning"](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12271085/)
(PMC, 2025) — confirms HR drift as a useful response marker but proposes
ML refinements beyond a simple percentage threshold. Worth revisiting once
we have Strava streams (post STEP 2b).

Used by rules: `hr_drift_high`.

---

## Books not yet sourced (Scribd availability sweep TODO)

The plan calls for a Scribd availability sweep (per the EE-skills pattern at
`Desktop\Skills\.tools\scribd-availability.md`). That requires manual
browser sessions to verify access; it's deferred. Once done, results land at
`literature/scribd-availability.md`. Highest-value candidates:

- **Friel — *The Cyclist's Training Bible* (4th ed., 2018)**
- **Friel — *Fast After 50* (2015)** — directly relevant at age 51
- **Daniels — *Daniels' Running Formula* (3rd ed., 2013)** — post-Vätternrundan run focus
- **Allen & Coggan — *Training and Racing with a Power Meter* (3rd ed., 2019)** — if power data ever enters the pipeline
- **Mujika — *Tapering and Peaking for Optimal Performance* (Human Kinetics, 2009)** — book-length expansion of the 2003 paper

---

## How to extend this

When adding a new rule:

1. Find a citation that supports it (peer-reviewed preferred; coaching text
   acceptable if peer-reviewed work doesn't directly address it).
2. Add a section here with the bibliographic info + actionable numbers.
3. Reference the section id from the `citations:` list in `heuristics.yaml`.
4. Note any contextual caveats (Michael's case vs literature population).
