"""One-time Strava OAuth.

Runs a tiny local HTTP server, opens your browser to Strava, captures the
authorization code from the redirect, swaps it for a token pair, and writes
~/.trainingplan/strava_tokens.json.

Usage:
  venv\\Scripts\\python scripts\\auth_strava.py

Re-run any time you need to re-auth (e.g. after revoking access).
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
from dotenv import load_dotenv
from stravalib import Client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trainingplan.strava import DEFAULT_SCOPES, save_tokens  # noqa: E402


# Shared between the callback handler and the main thread.
_captured: dict = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches Strava's GET /callback?code=XXX&state=YYY redirect."""

    def do_GET(self):  # noqa: N802 (stdlib-mandated naming)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        code = (qs.get("code") or [None])[0]
        error = (qs.get("error") or [None])[0]
        scope = (qs.get("scope") or [None])[0]
        _captured["code"] = code
        _captured["error"] = error
        _captured["scope"] = scope

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            body = "<h2>Authorized.</h2><p>You can close this tab.</p>"
        else:
            body = f"<h2>Auth failed.</h2><pre>{error}</pre>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args, **kwargs):  # silence default access-log noise
        return


@click.command()
@click.option("--port", default=8000, show_default=True,
              help="Local callback port. Must match the port in your browser if changed.")
def main(port: int) -> None:
    load_dotenv(ROOT / ".env")
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        click.echo("STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set in .env.", err=True)
        click.echo("See docs/strava_setup.md for how to get them.", err=True)
        sys.exit(1)

    redirect_uri = f"http://localhost:{port}/callback"
    client = Client()
    auth_url = client.authorization_url(
        client_id=int(client_id),
        redirect_uri=redirect_uri,
        scope=DEFAULT_SCOPES,
    )

    server = HTTPServer(("localhost", port), _CallbackHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    click.echo(f"Opening browser to authorize at Strava...")
    click.echo(f"  (If it doesn't open, paste this URL manually:)")
    click.echo(f"  {auth_url}")
    webbrowser.open(auth_url)

    # Wait for the callback to populate _captured.
    click.echo(f"Listening on http://localhost:{port}/callback ...")
    while "code" not in _captured and "error" not in _captured:
        try:
            t.join(timeout=0.5)
        except KeyboardInterrupt:
            click.echo("aborted", err=True)
            server.shutdown()
            sys.exit(2)

    server.shutdown()

    if _captured.get("error"):
        click.echo(f"Strava returned an error: {_captured['error']}", err=True)
        sys.exit(3)

    code = _captured["code"]
    click.echo(f"Got auth code. Exchanging for tokens...")
    tokens = client.exchange_code_for_token(
        client_id=int(client_id),
        client_secret=client_secret,
        code=code,
    )
    # stravalib returns a dict (v2) or a model — handle either.
    access = tokens.get("access_token") if isinstance(tokens, dict) else tokens.access_token
    refresh = tokens.get("refresh_token") if isinstance(tokens, dict) else tokens.refresh_token
    expires = tokens.get("expires_at") if isinstance(tokens, dict) else tokens.expires_at

    save_tokens(access, refresh, expires)
    click.echo(f"OK — tokens stored at ~/.trainingplan/strava_tokens.json")
    click.echo(f"Scopes granted: {_captured.get('scope', '?')}")


if __name__ == "__main__":
    main()
