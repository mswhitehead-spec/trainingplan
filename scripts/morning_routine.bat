@echo off
:: Morning routine (05:00): sync Strava, write proposal, auto-apply, regenerate
:: calendar, then send daily email. Email goes out last so it reflects any
:: plan changes made by the auto-apply step.
cd /d C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python.exe scripts\sync.py --quiet
venv\Scripts\python.exe scripts\propose.py
venv\Scripts\python.exe scripts\apply_proposal.py --yes
venv\Scripts\python.exe scripts\publish_calendar.py
venv\Scripts\python.exe scripts\publish_dashboard.py
venv\Scripts\python.exe scripts\send_daily_email.py
