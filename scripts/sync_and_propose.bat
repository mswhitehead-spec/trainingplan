@echo off
:: Pulls latest activities from Strava, matches to plan, and writes a proposal.
:: Safe to run any number of times — sync.py and propose.py are both idempotent.
cd /d C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python.exe scripts\sync.py --quiet
venv\Scripts\python.exe scripts\propose.py
