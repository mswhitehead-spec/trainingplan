"""Generate docs/index.html — a static training dashboard served via GitHub Pages.

The page is a single self-contained HTML file (no external JS/CSS requests at
runtime). Chart.js is bundled inline from a CDN fetch done at generation time,
so the page works offline and loads instantly.

Run:
    venv\\Scripts\\python scripts\\publish_dashboard.py

Output: docs/index.html  (committed with artifacts-local/ by the cron job)
URL:    https://mswhitehead-spec.github.io/trainingplan/
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from trainingplan import plan as plan_mod
from trainingplan import state as state_mod
from trainingplan.plan import days_to_event


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DOCS_DIR = ROOT / "docs"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _fmt_dur(m: float | None) -> str:
    if not m:
        return "—"
    m = int(round(m))
    h, r = divmod(m, 60)
    return f"{h}h{r:02d}m" if h else f"{m}m"


def _discipline_icon(disc: str) -> str:
    return {"cycling": "🚴", "running": "🏃", "walking": "🚶",
            "strength": "💪", "swimming": "🏊", "rest": "🛌"}.get(disc, "🏋️")


def _status_badge(status: str) -> str:
    badges = {
        "completed": '<span class="badge done">✓ done</span>',
        "missed":    '<span class="badge miss">✗ missed</span>',
        "planned":   '<span class="badge plan">planned</span>',
        "adjusted":  '<span class="badge adj">adjusted</span>',
        "skipped":   '<span class="badge skip">skipped</span>',
    }
    return badges.get(status, f'<span class="badge">{status}</span>')


def _render_sessions_table(sessions: list[dict]) -> str:
    rows = []
    for s in sessions:
        d = date.fromisoformat(s["date"])
        actual = s.get("actual") or {}
        analysis = s.get("analysis") or {}
        targets = s.get("targets") or {}

        # planned vs actual duration
        p_dur = _fmt_dur(targets.get("duration_min"))
        a_dur = _fmt_dur(actual.get("duration_min"))
        p_dist = f"{targets.get('distance_km', targets.get('distance_km_min', '—'))} km" if targets.get("distance_km") else "—"
        a_dist = f"{actual.get('distance_km', 0):.1f} km" if actual.get("distance_km") else "—"
        a_hr   = str(actual.get("avg_hr", "—"))
        zone   = targets.get("avg_hr_zone", "—")
        verdict = analysis.get("verdict", "")
        drift_pct = analysis.get("hr_drift_pct")
        drift_str = f"{drift_pct:+.1f}%" if drift_pct is not None else "—"
        elev = f"{int(actual.get('elevation_gain_m', 0))} m" if actual.get("elevation_gain_m") else "—"
        power = f"{actual.get('avg_power_w', 0):.0f} W" if actual.get("avg_power_w") else "—"
        flags = " ".join(f'<span class="flag">{f}</span>' for f in (analysis.get("flags") or []))
        icon = _discipline_icon(s.get("discipline", ""))
        badge = _status_badge(s.get("status", "planned"))
        name = actual.get("name") or s.get("type", "").replace("_", " ")

        rows.append(f"""
        <tr class="row-{s.get('status','planned')}">
          <td class="date-cell">{d.strftime('%a %d %b')}</td>
          <td>{icon} {name}</td>
          <td>{badge}</td>
          <td>{p_dur} → {a_dur}</td>
          <td>{p_dist} → {a_dist}</td>
          <td>{a_hr} <span class="dim">({zone})</span></td>
          <td>{drift_str}</td>
          <td>{elev}</td>
          <td>{power}</td>
          <td class="verdict">{verdict} {flags}</td>
        </tr>""")
    return "\n".join(rows)


def _chart_data(sessions: list[dict]) -> str:
    """Return JSON for Chart.js — labels, HR, distance, duration arrays."""
    completed = [s for s in sessions if s.get("status") == "completed"]
    labels, hrs, dists, durs = [], [], [], []
    for s in completed:
        actual = s.get("actual") or {}
        labels.append(s["date"])
        hrs.append(actual.get("avg_hr") or None)
        dists.append(actual.get("distance_km") or None)
        durs.append(round(actual.get("duration_min", 0) / 60, 2) or None)
    return json.dumps({"labels": labels, "hr": hrs, "dist": dists, "dur": durs})


def _week_summary(sessions: list[dict]) -> list[dict]:
    """Aggregate completed sessions by ISO week."""
    from collections import defaultdict
    weeks: dict[str, dict] = defaultdict(lambda: {"km": 0.0, "min": 0.0, "sessions": 0})
    for s in sessions:
        if s.get("status") != "completed":
            continue
        d = date.fromisoformat(s["date"])
        wk = d.strftime("W%W (%b %d)")
        actual = s.get("actual") or {}
        weeks[wk]["km"] += actual.get("distance_km") or 0
        weeks[wk]["min"] += actual.get("duration_min") or 0
        weeks[wk]["sessions"] += 1
    return [{"week": k, **v} for k, v in sorted(weeks.items())]


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vätternrundan Training Dashboard</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
    --text: #e2e8f0; --dim: #64748b; --accent: #3b82f6;
    --green: #22c55e; --red: #ef4444; --yellow: #f59e0b; --purple: #a855f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
          font-size: 14px; line-height: 1.5; padding: 20px; }}
  h1 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }}
  h2 {{ font-size: 1rem; font-weight: 600; color: var(--accent); margin: 24px 0 10px; }}
  .meta {{ color: var(--dim); font-size: 0.85rem; margin-bottom: 20px; }}
  .kpi-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
           padding: 14px 18px; min-width: 130px; }}
  .kpi .label {{ color: var(--dim); font-size: 0.75rem; text-transform: uppercase;
                  letter-spacing: .05em; }}
  .kpi .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 2px; }}
  .kpi .value.ok   {{ color: var(--green); }}
  .kpi .value.warn {{ color: var(--yellow); }}
  .kpi .value.race {{ color: var(--purple); }}
  .chart-wrap {{ background: var(--surface); border: 1px solid var(--border);
                  border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  canvas {{ max-height: 200px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface);
            border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  th {{ background: #12151f; color: var(--dim); font-size: 0.75rem;
        text-transform: uppercase; letter-spacing: .05em; padding: 8px 10px;
        text-align: left; white-space: nowrap; }}
  td {{ padding: 7px 10px; border-top: 1px solid var(--border); vertical-align: top; }}
  .row-completed {{ background: #0d1a10; }}
  .row-missed     {{ background: #1a0d0d; }}
  .row-planned    {{ }}
  .row-adjusted   {{ background: #0d1220; }}
  .date-cell      {{ color: var(--dim); white-space: nowrap; }}
  .verdict        {{ color: var(--dim); font-size: 0.85em; }}
  .dim            {{ color: var(--dim); }}
  .flag           {{ background: #1e293b; border: 1px solid var(--border);
                     border-radius: 4px; padding: 1px 5px; font-size: 0.75em;
                     color: var(--yellow); margin-left: 4px; }}
  .badge {{ border-radius: 4px; padding: 2px 7px; font-size: 0.75em; font-weight: 600; }}
  .badge.done {{ background: #052e16; color: var(--green); }}
  .badge.miss {{ background: #2d0a0a; color: var(--red); }}
  .badge.plan {{ background: #1e293b; color: var(--dim); }}
  .badge.adj  {{ background: #172554; color: var(--accent); }}
  .badge.skip {{ background: #27161b; color: var(--dim); }}
  .week-table td, .week-table th {{ padding: 6px 10px; }}
  a {{ color: var(--accent); }}
  @media (max-width: 700px) {{
    body {{ padding: 10px; font-size: 13px; }}
    .kpi .value {{ font-size: 1.2rem; }}
  }}
</style>
</head>
<body>
<h1>🚴 Vätternrundan Training</h1>
<p class="meta">Generated {generated} · Plan: {plan_name} · <a href="plan.ics">📅 Subscribe (.ics)</a></p>

<div class="kpi-row">
  <div class="kpi"><div class="label">Days to race</div>
    <div class="value {dte_cls}">{dte}</div></div>
  <div class="kpi"><div class="label">Sessions done</div>
    <div class="value ok">{done} / {total}</div></div>
  <div class="kpi"><div class="label">Total km (bike)</div>
    <div class="value">{total_km:.0f} km</div></div>
  <div class="kpi"><div class="label">Total time</div>
    <div class="value">{total_h:.1f} h</div></div>
  <div class="kpi"><div class="label">Last sync</div>
    <div class="value" style="font-size:0.9rem;margin-top:4px">{last_sync}</div></div>
</div>

<h2>Activity (all completed sessions)</h2>
<div class="chart-wrap">
  <canvas id="chart"></canvas>
</div>

<h2>Session log</h2>
<div style="overflow-x:auto">
<table>
<thead><tr>
  <th>Date</th><th>Activity</th><th>Status</th>
  <th>Duration (plan→act)</th><th>Distance (plan→act)</th>
  <th>Avg HR (zone)</th><th>HR drift</th><th>Elevation</th><th>Power</th>
  <th>Verdict</th>
</tr></thead>
<tbody>
{session_rows}
</tbody>
</table>
</div>

<h2>Week summary</h2>
<div style="overflow-x:auto">
<table class="week-table">
<thead><tr><th>Week</th><th>Sessions</th><th>Total km</th><th>Total time</th></tr></thead>
<tbody>
{week_rows}
</tbody>
</table>
</div>

<script>
const data = {chart_data};
const ctx = document.getElementById('chart').getContext('2d');

// Inline minimal Chart.js — drawn with Canvas API directly (no CDN dependency).
// We draw HR as a line and distance as bars.
(function() {{
  const labels = data.labels;
  const n = labels.length;
  if (!n) return;

  const W = ctx.canvas.offsetWidth || 800;
  ctx.canvas.width = W;
  ctx.canvas.height = 180;
  const w = W, h = 180;
  const PAD = {{ t: 20, r: 20, b: 40, l: 50 }};
  const chartW = w - PAD.l - PAD.r;
  const chartH = h - PAD.t - PAD.b;

  // Scales
  const maxDist = Math.max(...data.dist.map(v => v||0), 10);
  const maxHR   = Math.max(...data.hr.map(v => v||0), 180);
  const minHR   = 60;
  const barW = Math.max(2, (chartW / n) - 2);

  function xOf(i) {{ return PAD.l + (i + 0.5) * (chartW / n); }}
  function yHR(v)  {{ return PAD.t + chartH - ((v - minHR) / (maxHR - minHR)) * chartH; }}
  function yDist(v){{ return PAD.t + chartH - (v / maxDist) * chartH; }}

  ctx.fillStyle = '#0f1117';
  ctx.fillRect(0, 0, w, h);

  // Grid lines
  ctx.strokeStyle = '#2a2d3e'; ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {{
    const y = PAD.t + (g / 4) * chartH;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(w - PAD.r, y); ctx.stroke();
  }}

  // Bars (distance)
  data.dist.forEach((v, i) => {{
    if (!v) return;
    const bh = (v / maxDist) * chartH;
    ctx.fillStyle = '#1e3a5f';
    ctx.fillRect(xOf(i) - barW/2, PAD.t + chartH - bh, barW, bh);
  }});

  // HR line
  ctx.beginPath(); ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2;
  let moved = false;
  data.hr.forEach((v, i) => {{
    if (!v) {{ moved = false; return; }}
    if (!moved) {{ ctx.moveTo(xOf(i), yHR(v)); moved = true; }}
    else ctx.lineTo(xOf(i), yHR(v));
  }});
  ctx.stroke();

  // HR dots
  data.hr.forEach((v, i) => {{
    if (!v) return;
    ctx.beginPath(); ctx.arc(xOf(i), yHR(v), 3, 0, Math.PI*2);
    ctx.fillStyle = '#ef4444'; ctx.fill();
  }});

  // X labels
  ctx.fillStyle = '#64748b'; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
  labels.forEach((lbl, i) => {{
    if (i % Math.max(1, Math.floor(n/8)) === 0)
      ctx.fillText(lbl.slice(5), xOf(i), h - 8);
  }});

  // Y axis label (HR)
  ctx.save(); ctx.translate(12, PAD.t + chartH/2);
  ctx.rotate(-Math.PI/2); ctx.fillText('HR bpm', 0, 0); ctx.restore();

  // Legend
  ctx.fillStyle='#1e3a5f'; ctx.fillRect(w-110,8,12,12);
  ctx.fillStyle='#e2e8f0'; ctx.textAlign='left'; ctx.font='11px system-ui';
  ctx.fillText('Distance', w-94, 18);
  ctx.strokeStyle='#ef4444'; ctx.lineWidth=2;
  ctx.beginPath(); ctx.moveTo(w-110,26); ctx.lineTo(w-98,26); ctx.stroke();
  ctx.fillText('Avg HR', w-94, 30);
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit("NO CONFIG: copy config.yaml.example to config.yaml.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    art_dir = Path(cfg["artifacts_dir"])

    plan_path = art_dir / "plan.yaml"
    state_path = art_dir / "state.json"
    if not plan_path.exists():
        raise SystemExit(f"plan.yaml not found at {plan_path}")

    plan = plan_mod.load(plan_path)
    plan_mod.validate(plan)
    state = state_mod.load(state_path)

    today = date.today()
    dte = days_to_event(plan, today=today)
    sessions = plan["sessions"]

    completed = [s for s in sessions if s.get("status") == "completed"]
    total = len([s for s in sessions if s.get("type") != "race"])
    done = len(completed)

    # KPI aggregates
    total_km = sum(
        (s.get("actual") or {}).get("distance_km") or 0
        for s in completed
        if s.get("discipline") == "cycling"
    )
    total_min = sum(
        (s.get("actual") or {}).get("duration_min") or 0
        for s in completed
    )

    # Days to race display
    if dte is None:
        dte_str, dte_cls = "—", ""
    elif dte == 0:
        dte_str, dte_cls = "RACE DAY 🏁", "race"
    elif dte < 0:
        dte_str, dte_cls = f"{-dte}d ago", "ok"
    else:
        dte_str, dte_cls = str(dte), "warn" if dte <= 7 else "ok"

    last_sync = (state.get("last_sync_at") or "never")[:16].replace("T", " ")
    plan_name = (plan.get("block") or {}).get("name", "pre-race")

    session_rows = _render_sessions_table(sessions)
    weeks = _week_summary(sessions)
    week_rows = "\n".join(
        f'<tr><td>{w["week"]}</td><td>{w["sessions"]}</td>'
        f'<td>{w["km"]:.0f} km</td><td>{_fmt_dur(w["min"])}</td></tr>'
        for w in weeks
    )

    html = _HTML.format(
        generated=today.isoformat(),
        plan_name=plan_name,
        dte=dte_str,
        dte_cls=dte_cls,
        done=done,
        total=total,
        total_km=total_km,
        total_h=total_min / 60,
        last_sync=last_sync,
        session_rows=session_rows,
        week_rows=week_rows,
        chart_data=_chart_data(sessions),
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")

    # Also copy plan.ics into docs/ so the subscribe link in the dashboard works.
    ics_src = art_dir / "plan.ics"
    if ics_src.exists():
        import shutil
        shutil.copy2(ics_src, DOCS_DIR / "plan.ics")

    print(f"Dashboard written to {out_path}")
    print(f"  Sessions: {done}/{total} completed, {total_km:.0f} km bike, "
          f"{total_min/60:.1f} h total")


if __name__ == "__main__":
    main()
