"""Crypto Lab — version Render avec tableau de bord web mobile.

- Réutilise toute la logique de simulation de algo.py
- Aucun Tkinter côté serveur
- Cycle de simulation toutes les 30 secondes
- Page web sur /
- API JSON sur /api/status et /health
- Tolère les paramètres d'URL ajoutés par les navigateurs (ex: ?utm_source=...)
"""

import html
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from algo import STATE, PAIRS, initial, market, cycle, save

status_lock = threading.Lock()
runtime_status = {
    "started_at": time.time(),
    "last_ok": 0,
    "last_error": None,
    "equity": 500.0,
    "cash": 500.0,
    "gain_loss": 0.0,
    "drawdown": 0.0,
    "positions": {},
    "trades_count": 0,
    "last_trades": [],
    "alerts": [],
    "warnings": [],
}


def load_state():
    if not STATE.exists():
        return initial()
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(s, dict) or not initial().keys() <= s.keys():
            raise ValueError("Sauvegarde incompatible")
        return s
    except Exception as exc:
        print(f"[WARN] Sauvegarde ignorée: {exc}", flush=True)
        return initial()


def publish_status(s, equity, alerts=None, warnings=None, error=None):
    with status_lock:
        runtime_status["last_ok"] = time.time() if error is None else runtime_status["last_ok"]
        runtime_status["last_error"] = error
        runtime_status["equity"] = round(float(equity), 2)
        runtime_status["cash"] = round(float(s.get("cash", 0)), 2)
        runtime_status["gain_loss"] = round(float(equity) - 500.0, 2)
        runtime_status["drawdown"] = round(float(s.get("drawdown", 0)) * 100, 2)
        runtime_status["positions"] = s.get("positions", {})
        runtime_status["trades_count"] = len(s.get("trades", []))
        runtime_status["last_trades"] = s.get("trades", [])[-5:]
        runtime_status["alerts"] = alerts or []
        runtime_status["warnings"] = warnings or []


def simulation_loop():
    s = load_state()

    # Affiche déjà l'état sauvegardé au démarrage.
    publish_status(s, s.get("cash", 500.0))

    while True:
        started = time.time()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {name: pool.submit(market, pair) for name, pair in PAIRS.items()}
                snapshots = {name: future.result() for name, future in futures.items()}

            if time.time() - started > 25:
                raise ValueError("Collecte trop lente : cycle abandonné.")

            candidate, cards, equity, alerts, warnings = cycle(s, snapshots, time.time())
            save(candidate)
            s = candidate
            publish_status(s, equity, alerts, warnings)

            print(
                f"[OK] equity={equity:.2f}€ "
                f"cash={s['cash']:.2f}€ "
                f"positions={len(s['positions'])} "
                f"trades={len(s['trades'])} "
                f"alerts={alerts or '-'} warnings={warnings or '-'}",
                flush=True,
            )

        except Exception as exc:
            with status_lock:
                runtime_status["last_error"] = str(exc)
            print(f"[ERROR] {exc}", flush=True)

        elapsed = time.time() - started
        time.sleep(max(1, 30 - elapsed))


def snapshot():
    with status_lock:
        data = dict(runtime_status)
    data["service"] = "crypto-lab"
    data["mode"] = "simulation uniquement"
    data["uptime_seconds"] = int(time.time() - data["started_at"])
    return data


DASHBOARD = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Crypto Lab</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #0b1020; color: #eef3ff;
}
.wrap { max-width: 780px; margin: 0 auto; padding: 22px 16px 40px; }
h1 { margin: 0; font-size: 28px; }
.sub { color: #98a6bd; margin: 6px 0 22px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.card {
  background: #151d31; border-radius: 18px; padding: 16px;
  border: 1px solid rgba(255,255,255,.06);
}
.big { font-size: 30px; font-weight: 800; margin-top: 4px; }
.label { color: #98a6bd; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
.good { color: #59e3b2; } .bad { color: #ff8198; } .neutral { color: #8bb7ff; }
.full { grid-column: 1 / -1; }
.row { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-top:1px solid rgba(255,255,255,.06); }
.row:first-of-type { border-top:0; }
.small { color:#98a6bd; font-size:13px; }
.status-dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:#59e3b2; margin-right:7px; }
button {
  width:100%; border:0; border-radius:14px; padding:13px; margin-top:12px;
  background:#243049; color:#eef3ff; font-weight:700; font-size:15px;
}
@media (max-width: 520px) { .grid { grid-template-columns: 1fr 1fr; } .big { font-size: 25px; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>CRYPTO LAB</h1>
  <div class="sub"><span class="status-dot"></span>Simulation fictive · mise à jour automatique</div>

  <div class="grid">
    <div class="card">
      <div class="label">Valeur totale</div>
      <div class="big" id="equity">—</div>
    </div>
    <div class="card">
      <div class="label">Gain / perte</div>
      <div class="big" id="gain">—</div>
    </div>
    <div class="card">
      <div class="label">Liquidités</div>
      <div class="big" id="cash">—</div>
    </div>
    <div class="card">
      <div class="label">Drawdown max.</div>
      <div class="big" id="drawdown">—</div>
    </div>

    <div class="card full">
      <div class="label">Positions ouvertes</div>
      <div id="positions" style="margin-top:10px">—</div>
    </div>

    <div class="card full">
      <div class="label">Derniers trades</div>
      <div id="trades" style="margin-top:10px">—</div>
    </div>

    <div class="card full">
      <div class="label">État du moteur</div>
      <div id="engine" style="margin-top:10px">Chargement…</div>
      <button onclick="load()">Actualiser maintenant</button>
    </div>
  </div>
</div>

<script>
function eur(v) {
  return Number(v).toLocaleString('fr-FR', {minimumFractionDigits:2, maximumFractionDigits:2}) + ' €';
}
function fmtTime(ts) {
  if (!ts) return 'Jamais';
  return new Date(ts * 1000).toLocaleTimeString('fr-FR');
}
async function load() {
  try {
    const r = await fetch('/api/status?ts=' + Date.now(), {cache:'no-store'});
    const d = await r.json();

    document.getElementById('equity').textContent = eur(d.equity);
    const gain = document.getElementById('gain');
    gain.textContent = (d.gain_loss >= 0 ? '+' : '') + eur(d.gain_loss);
    gain.className = 'big ' + (d.gain_loss >= 0 ? 'good' : 'bad');

    document.getElementById('cash').textContent = eur(d.cash);
    document.getElementById('drawdown').textContent = Number(d.drawdown).toFixed(2) + ' %';

    const pos = Object.entries(d.positions || {});
    document.getElementById('positions').innerHTML = pos.length ? pos.map(([name,p]) =>
      `<div class="row"><div><b>${name}</b><div class="small">Entrée ${eur(p.entry)}</div></div><div>Stop ${eur(p.stop)}<br><span class="small">Objectif ${eur(p.target)}</span></div></div>`
    ).join('') : '<div class="small">Aucune position ouverte.</div>';

    const trades = d.last_trades || [];
    document.getElementById('trades').innerHTML = trades.length ? trades.slice().reverse().map(t =>
      `<div class="row"><div><b>${t.asset}</b><div class="small">${t.reason}</div></div><div class="${t.pnl >= 0 ? 'good':'bad'}"><b>${t.pnl >= 0 ? '+':''}${eur(t.pnl)}</b></div></div>`
    ).join('') : '<div class="small">Aucun trade clôturé pour le moment.</div>';

    const bits = [
      `Dernier cycle : <b>${fmtTime(d.last_ok)}</b>`,
      `Trades clôturés : <b>${d.trades_count}</b>`
    ];
    if (d.alerts && d.alerts.length) bits.push(`<span class="good">${d.alerts.join(' · ')}</span>`);
    if (d.warnings && d.warnings.length) bits.push(`<span class="bad">${d.warnings.join(' · ')}</span>`);
    if (d.last_error) bits.push(`<span class="bad">Erreur : ${d.last_error}</span>`);
    document.getElementById('engine').innerHTML = bits.join('<br>');
  } catch (e) {
    document.getElementById('engine').innerHTML = '<span class="bad">Impossible de joindre le serveur.</span>';
  }
}
load();
setInterval(load, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body_text, status=200):
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Important : on ignore les paramètres ?utm_source=... ajoutés par certains navigateurs.
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/":
            self._send_html(DASHBOARD)
            return
        if path in ("/health", "/api/status"):
            self._send_json(snapshot())
            return

        self._send_json({"error": "not found", "path": path}, 404)

    def log_message(self, fmt, *args):
        return


def main():
    thread = threading.Thread(target=simulation_loop, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[SERVER] Crypto Lab écoute sur 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
