# Subscribing to plan.ics in Google Calendar

One-time setup so your training plan shows up as a Google Calendar — and
auto-updates whenever you re-run `publish_calendar.py`.

## How it works

```
plan.yaml  ─►  publish_calendar.py  ─►  artifacts-local\plan.ics
                                   ─►  G:\Mit drev\Training plan\plan.ics
                                          │
                                          ▼ Drive syncs to drive.google.com
                                          │
                                          ▼ GCal polls subscribed URL (~24 h)
                                          │
                                          ▼ Calendar updates
```

Google Calendar **polls subscribed URLs roughly once every 24 hours** — that's
a Google limit, not something we can speed up. If you change the plan and want
to see it sooner, just re-import the file manually (instructions at the
bottom).

---

## Setup (≈3 minutes, one time)

### 1. Generate `plan.ics`

```powershell
cd C:\Users\Michael\Desktop\TrainingPlan
venv\Scripts\python scripts\publish_calendar.py
```

You should see something like:

```
wrote 10161 bytes → C:\Users\Michael\Desktop\TrainingPlan\artifacts-local\plan.ics
sessions in calendar: 19
mirrored to: G:\Mit drev\Training plan\plan.ics
```

### 2. Wait ~30 seconds for Drive to sync

Drive for Desktop will upload `plan.ics` to your `Training plan` folder in
the cloud. The Drive tray icon shows when it's done.

### 3. Open the file in Drive (web)

Go to <https://drive.google.com/>, navigate to **Training plan**, and you
should see `plan.ics` listed.

### 4. Get a public download URL

Right-click `plan.ics` → **Share** → **General access** → **Anyone with the link**
(Viewer). Click **Copy link**. You'll get something like:

```
https://drive.google.com/file/d/FILE_ID_HERE/view?usp=sharing
```

The piece between `/d/` and `/view` is your **FILE_ID**.

Now transform that link into a direct-download URL:

```
https://drive.google.com/uc?export=download&id=FILE_ID_HERE
```

(Same FILE_ID, different host path.) Test it in a private browser window —
it should immediately download the .ics file. If it asks you to log in,
the Share permission isn't set to "Anyone with the link" yet — go back and
fix it.

### 5. Subscribe in Google Calendar

Open <https://calendar.google.com/>. Bottom-left, next to **Other calendars**,
click **+** → **From URL**. Paste your `uc?export=download&id=…` URL.
Click **Add calendar**.

Within a few seconds the events appear as a new calendar named "Training
plan". Pick a color in the left sidebar — I'd suggest something distinct from
your work calendar.

### 6. (Optional) Rename it

Google may name the new calendar after the FILE_ID by default. Click the
three-dot menu next to it in the sidebar → **Settings** → rename to "Training".

---

## Day-to-day

After this is set up, the routine is:

```powershell
venv\Scripts\python scripts\sync.py           # pull workouts, write summaries
venv\Scripts\python scripts\propose.py        # see proposed plan changes
venv\Scripts\python scripts\apply_proposal.py # accept/reject changes
venv\Scripts\python scripts\publish_calendar.py  # regenerate plan.ics
```

The last command updates both copies (`artifacts-local\plan.ics` and the
Drive mirror). GCal picks up the change on its next ~24 h poll.

## When you want to see changes immediately (manual reimport)

The 24-hour poll is the only frustration. If you make a change and want it
in GCal right now:

1. Run `publish_calendar.py`.
2. Open <https://calendar.google.com/>.
3. Gear icon (top-right) → **Settings** → **Import & export** → **Import**.
4. Pick your local `artifacts-local\plan.ics`.
5. Choose the **Training** calendar as the destination.
6. Click **Import**.

Because every VEVENT has a stable UID (derived from the session id), GCal
treats this as an **update** of existing events, not duplicates.

---

## Troubleshooting

**Drive's share link doesn't auto-download.** Some Drive accounts have
DLP/admin restrictions that block public sharing. If "Anyone with the link"
isn't available, the alternatives below work without Drive sharing entirely.

**Events appear at the wrong time.** `plan.ics` uses *floating* local time —
no timezone is embedded. Google Calendar treats floating times as "whatever
local timezone the user is in." So if you fly to Sweden the day before the
race, the race-day event displays in Swedish local time automatically. If
you want fixed timezones, that's a future-me problem.

**Updates aren't showing up.** GCal poll is ~24 h and there's no manual
"refresh" button for subscribed calendars. Reimport (see above) is the
workaround. After ~24 h, polled updates take over.

---

## Alternative: GitHub Gist (no Drive at all)

If you'd rather not share via Drive:

1. Create a private Gist at <https://gist.github.com/> with the contents of
   `plan.ics`. Click **Create secret gist**.
2. After creating, click **Raw** on the file. Copy that URL — it ends in
   `.../raw/<commit>/plan.ics`. Strip the `<commit>` part to get a permalink
   that always serves the latest version:
   `https://gist.githubusercontent.com/<you>/<gist-id>/raw/plan.ics`
3. Use that URL in GCal "From URL".
4. After every `publish_calendar.py`, push the new file to the Gist
   (`gh gist edit <id> -a plan.ics` works if you have `gh`).

Pros: clean URL, no transformation needed. Cons: one more command after
publish to actually update the Gist.
