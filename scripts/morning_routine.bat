@echo off
:: Morning routine (05:00): sync Strava, write proposal, send daily email.
:: The email goes out after sync so yesterday's verdict is included.
cd /d C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python.exe scripts\sync.py --quiet
venv\Scripts\python.exe scripts\propose.py
venv\Scripts\python.exe scripts\send_daily_email.py
