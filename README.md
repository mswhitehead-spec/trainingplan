# TrainingPlan

Personal adaptive training-plan pipeline. Pulls workouts from Strava, compares
them against a YAML plan, proposes conservative adaptations (never auto-applies),
and exports a Google Calendar–subscribable `.ics` file.

Designed around one principle: **the plan is a YAML file you can hand-edit.**
The scripts are thin wrappers that read it, update it, and emit derivatives.

---

## Layout

```
TrainingPlan/
├── src/trainingplan/      # library code (importable modules)
├── scripts/               # standalone runnable entry points
├── tests/                 # pytest unit tests + fixtures
├── docs/                  # one-time setup walkthroughs
└── artifacts-local/       # plan, state, .ics, summaries, proposals
```

`artifacts-local/` holds everything the pipeline writes. It's gitignored —
treat the YAML files inside as your hand-edited source of truth.

Input data (Strava bulk export, Garmin CSV) can live anywhere; their paths
are set in `config.yaml` under `sources:`.

---

## First-time setup

1. **Create a virtualenv and install deps:**

   ```powershell
   cd C:\Users\Michael\Desktop\TrainingPlan
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```

2. **Create your config file:**

   ```powershell
   copy config.yaml.example config.yaml
   notepad config.yaml
   ```

   Defaults to `artifacts-local/` and the Strava/Garmin paths used at
   setup. Edit if you've moved things.

3. **Sanity check:**

   ```powershell
   venv\Scripts\python scripts\status.py
   ```

   Should print where the artifacts dir is and that no plan or state exists
   yet. That's expected at STEP 1.

4. **Continue to STEP 2** (Strava auth) — see `docs/strava_setup.md`.

---

## Daily use (once everything is wired up)

```powershell
venv\Scripts\python scripts\sync.py     # fetch new Strava activities, write summaries
venv\Scripts\python scripts\propose.py  # see proposed plan changes
venv\Scripts\python scripts\apply_proposal.py  # accept/reject changes
```

Every plan mutation regenerates `plan.ics` in the Drive folder; Google Calendar
picks it up automatically via the subscribed URL.

---

## Design rules

- All adaptations are proposals; nothing auto-applies.
- OAuth tokens only; no passwords stored anywhere.
- Every script runnable in isolation with no arguments (or `--help`).
- Adaptation logic lives in `heuristics.yaml` with citations on every rule.
