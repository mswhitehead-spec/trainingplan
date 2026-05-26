# Strava API setup

You need to do this **once** to give the pipeline live access to your Strava
account. After that, the refresh token in `~/.trainingplan/strava_tokens.json`
keeps things working — you never re-enter credentials.

Takes ~5 minutes.

---

## 1. Register an API application

1. Sign in to https://www.strava.com/settings/api
2. If you've never made an app, click **Create & Manage Your App**.
3. Fill in the form:
   - **Application Name:** anything, e.g. `Michael TrainingPlan`
   - **Category:** Training
   - **Club:** leave blank
   - **Website:** `http://localhost`
   - **Application Description:** anything, e.g. *Personal training pipeline*
   - **Authorization Callback Domain:** `localhost`  (**no http://, no port, just `localhost`**)
4. Upload a placeholder image if Strava insists (any small image).
5. Click **Create**.

Strava now shows you:
- **Client ID** (a number, ~6 digits)
- **Client Secret** (a long hex string — click "show")

---

## 2. Put the credentials in `.env`

In the project root:

```powershell
copy .env.example .env
notepad .env
```

Paste your two values:

```
STRAVA_CLIENT_ID=12345
STRAVA_CLIENT_SECRET=abcdef0123456789abcdef0123456789abcdef01
```

Save and close. `.env` is gitignored.

---

## 3. Run the one-time auth flow

```powershell
venv\Scripts\python scripts\auth_strava.py
```

What happens:

1. A local web server starts on port 8000.
2. Your browser opens to the Strava authorization page.
3. You click **Authorize**.
4. Strava redirects to `http://localhost:8000/callback?code=...`
5. The local server captures the code, exchanges it with Strava for an
   access token + refresh token, and saves them to:

   ```
   C:\Users\Michael\.trainingplan\strava_tokens.json
   ```

6. The browser tab shows "Authorized — you can close this tab."
7. The script prints `OK — tokens stored.` and exits.

---

## 4. Verify

```powershell
venv\Scripts\python scripts\fetch.py --last 5
```

Should print your five most recent activities. If you see them, you're done.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Browser opens but Strava says "Bad redirect URI" | The callback domain in your app settings isn't `localhost`. Edit the app and fix it. |
| Browser doesn't open | Open the URL the script prints manually. |
| Port 8000 in use | Another process is holding it. Pass `--port 8765` (or any free port) and update the app's callback domain to match... actually no, keep `localhost` as the domain and just change the port — Strava accepts any port on that domain. |
| `fetch.py` says "no tokens" | `auth_strava.py` didn't finish. Re-run it. |
| Rate limited | Strava allows 100 calls / 15 min and 1000 / day per app. Normal use is well below that. |
