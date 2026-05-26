# Daily email setup

Send yourself a plain-text email each morning with today's training session,
the week ahead, and any pending plan adaptations.

```
06:00 (Task Scheduler) ─►  send_daily_email.py  ─►  SMTP smtp.gmail.com:587
                                                 ─►  inbox: mswhitehead@gmail.com
```

Two pieces to set up, one time only:

1. **A Gmail App Password** — so SMTP can authenticate without your real
   Google password.
2. **A Windows scheduled task** — so the script runs every morning.

Total time: ~5 minutes.

---

## 1. Generate a Gmail App Password

Gmail's SMTP server doesn't accept your regular Google password (since 2022).
You need an **App Password** — a 16-character throwaway credential that only
works for this one purpose.

Prerequisite: **2-Step Verification must be on** for your Google account. If
it isn't, turn it on first at <https://myaccount.google.com/security>.

1. Go to <https://myaccount.google.com/apppasswords>.
   (If that page says "App passwords aren't available for your account",
   you don't have 2-Step Verification on yet — turn it on, then come back.)
2. Under **App name**, type `trainingplan`. Click **Create**.
3. Google shows you a 16-character password like `abcd efgh ijkl mnop`.
   **Copy it now** — Google won't show it again.
4. Open `.env` in the project root and paste the password (no spaces) as
   the `EMAIL_PASSWORD` value:

   ```
   EMAIL_PASSWORD=abcdefghijklmnop
   ```

5. Confirm `config.yaml` has the `email:` section with the right addresses:

   ```yaml
   email:
     from: "mswhitehead@gmail.com"
     to:   "mswhitehead@gmail.com"
     smtp_host: "smtp.gmail.com"
     smtp_port: 587
   ```

## 2. Test it once manually

Render the email without sending, to confirm the content looks right:

```powershell
cd C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python scripts\send_daily_email.py --dry-run
```

Then send it for real:

```powershell
venv\Scripts\python scripts\send_daily_email.py
```

You should see `sent: [Training] 2026-... → mswhitehead@gmail.com` and the
email lands in your inbox within ~10 seconds. If you get an
`SMTPAuthenticationError`, the App Password is wrong or 2-Step Verification
isn't on for the account.

## 3. Schedule it daily via Task Scheduler

The PowerShell-y way (creates the task in one command, no GUI):

```powershell
$action = New-ScheduledTaskAction `
    -Execute 'C:\Users\Michael\Desktop\TrainingPlan\venv\Scripts\python.exe' `
    -Argument 'C:\Users\Michael\Desktop\TrainingPlan\scripts\send_daily_email.py' `
    -WorkingDirectory 'C:\Users\Michael\Desktop\TrainingPlan'

$trigger = New-ScheduledTaskTrigger -Daily -At 06:00

# StartWhenAvailable means: if the PC was asleep at 06:00, run as soon as it wakes up.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries

Register-ScheduledTask `
    -TaskName 'TrainingPlan-DailyEmail' `
    -Description 'Send today''s training plan email each morning' `
    -Action $action -Trigger $trigger -Settings $settings
```

To verify:

```powershell
Get-ScheduledTask -TaskName 'TrainingPlan-DailyEmail' | Get-ScheduledTaskInfo
```

To run it on demand (for testing):

```powershell
Start-ScheduledTask -TaskName 'TrainingPlan-DailyEmail'
```

To remove it later:

```powershell
Unregister-ScheduledTask -TaskName 'TrainingPlan-DailyEmail' -Confirm:$false
```

### The clicky way (Task Scheduler GUI)

If you'd rather not paste PowerShell:

1. Win+R → `taskschd.msc` → Enter.
2. Right-pane → **Create Basic Task**.
3. Name: `TrainingPlan-DailyEmail`. Next.
4. Trigger: **Daily**. Next. Start time: 06:00. Next.
5. Action: **Start a program**. Next.
6. Program/script: `C:\Users\Michael\Desktop\TrainingPlan\venv\Scripts\python.exe`
   Arguments: `C:\Users\Michael\Desktop\TrainingPlan\scripts\send_daily_email.py`
   Start in: `C:\Users\Michael\Desktop\TrainingPlan`
7. Finish.

## 4. (Optional) Combine into a daily routine

You'll probably want to run `sync.py` first (pull yesterday's workouts and
generate verdicts) before the email goes out — that way yesterday's verdict
appears in this morning's email.

Save this as `scripts\daily_routine.bat`:

```bat
@echo off
cd /d C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python.exe scripts\sync.py --quiet
venv\Scripts\python.exe scripts\propose.py --dry-run > NUL 2>&1
venv\Scripts\python.exe scripts\send_daily_email.py
```

Then point the scheduled task at `daily_routine.bat` instead of the Python
script. Order: sync (find new workouts) → propose dry-run (only logs to
stdout, doesn't surprise you) → email.

## Troubleshooting

**`SMTPAuthenticationError: Username and Password not accepted`** — the App
Password is wrong or 2-Step Verification was disabled. Regenerate the App
Password.

**The task says "Last Run Result: 0x1"** — open a normal PowerShell, manually
run the same command Task Scheduler runs, and read the error. Common causes:
the venv path moved, `EMAIL_PASSWORD` isn't loaded (the `.env` file must be
in the project root), or the working directory isn't set.

**Email shows up with weird characters (`·` rendered as `Â·`)** — your email
client is reading UTF-8 as Latin-1. Gmail, Apple Mail, and Outlook all
handle the email correctly; if a specific client doesn't, that's a client
config issue.

**No email at 06:00** — `Get-ScheduledTaskInfo -TaskName TrainingPlan-DailyEmail`
shows `NextRunTime`. If it's empty, the task isn't enabled. If it's set but
nothing arrives, `LastTaskResult` will tell you what went wrong (0 = success,
0x1 = generic error, 0x41306 = task was terminated by user).
