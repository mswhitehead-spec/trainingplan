@echo off
:: Pulls latest activities from Strava, matches to plan, auto-applies any
:: proposals, and regenerates plan.ics.
:: Safe to run any number of times — already-applied rules are filtered out.
cd /d C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python.exe scripts\sync.py --quiet
venv\Scripts\python.exe scripts\propose.py
venv\Scripts\python.exe scripts\apply_proposal.py --yes
venv\Scripts\python.exe scripts\publish_calendar.py
venv\Scripts\python.exe scripts\publish_dashboard.py
