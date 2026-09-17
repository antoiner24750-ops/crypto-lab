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

from algo import STATE, PAIRS, initial, market, cycle, save, FEE, SLIP

status_lock = threading.Lock()
runtime_status = {
    "started_at": time.time(), "last_ok": 0, "last_error": None,
    "equity": 500.0, "cash": 500.0, "gain_loss": 0.0, "gain_loss_pct": 0.0,
    "drawdown": 0.0, "invested": 0.0, "unrealized_pnl": 0.0,
    "positions": {}, "markets": {}, "trades_count": 0, "wins": 0,
    "win_rate": None, "realized_pnl": 0.0, "last_trades": [],
    "alerts": [], "warnings": [],
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


def publish_status(s, equity, cards=None, alerts=None, warnings=None, error=None):
    trades = s.get("trades", [])
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    realized = sum(float(t.get("pnl", 0)) for t in trades)
    cards = cards or {}
    positions = {}
    invested = 0.0
    unrealized = 0.0
    markets = {}

    for name, p in s.get("positions", {}).items():
        item = dict(p)
        invested += float(p.get("cost", 0))
        if name in cards:
            c = cards[name]
            bid = float(c["bid"])
            liquidation = float(p["qty"]) * bid * (1-SLIP) * (1-FEE)
            upnl = liquidation - float(p["cost"])
            unrealized += upnl
            item.update(current_bid=bid, current_ask=float(c["ask"]),
                        unrealized_pnl=upnl,
                        unrealized_pct=(upnl/float(p["cost"])*100 if p.get("cost") else 0))
        positions[name] = item

    for name, c in cards.items():
        markets[name] = dict(
            bid=float(c["bid"]), ask=float(c["ask"]), state=c.get("state","ATTENDRE"),
            reason=c.get("reason",""), details=c.get("details","")
        )

    with status_lock:
        runtime_status["last_ok"] = time.time() if error is None else runtime_status["last_ok"]
        runtime_status["last_error"] = error
        runtime_status["equity"] = round(float(equity), 2)
        runtime_status["cash"] = round(float(s.get("cash", 0)), 2)
        runtime_status["gain_loss"] = round(float(equity)-500.0, 2)
        runtime_status["gain_loss_pct"] = round((float(equity)/500.0-1)*100, 2)
        runtime_status["drawdown"] = round(float(s.get("drawdown", 0))*100, 2)
        runtime_status["invested"] = round(invested, 2)
        runtime_status["unrealized_pnl"] = round(unrealized, 2)
        runtime_status["positions"] = positions
        runtime_status["markets"] = markets
        runtime_status["trades_count"] = len(trades)
        runtime_status["wins"] = wins
        runtime_status["win_rate"] = round(wins/len(trades)*100, 1) if trades else None
        runtime_status["realized_pnl"] = round(realized, 2)
        runtime_status["last_trades"] = trades[-8:]
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
            publish_status(s, equity, cards, alerts, warnings)

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
    data["initial_capital"] = 500.0
    data["fee_pct"] = FEE * 100
    data["slippage_pct"] = SLIP * 100
    return data


DASHBOARD = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Crypto Lab</title>
<style>
:root{color-scheme:dark;--bg:#07101f;--panel:#101d33;--line:rgba(255,255,255,.08);--text:#f5f8ff;--muted:#91a2bd;--green:#5ee0b5;--red:#ff7995;--blue:#7cb8ff;--yellow:#ffd166}
*{box-sizing:border-box}body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 10% 0,rgba(66,133,244,.15),transparent 30rem),var(--bg);color:var(--text)}
.wrap{max-width:1100px;margin:auto;padding:26px 18px 50px}.top{display:flex;justify-content:space-between;gap:15px;align-items:center;margin-bottom:18px}.top h1{margin:0;font-size:30px}.sub,.muted{color:var(--muted)}.live{color:var(--green);font-size:13px;font-weight:800;background:rgba(94,224,181,.08);border:1px solid rgba(94,224,181,.2);padding:9px 12px;border-radius:999px}
.hero{display:grid;grid-template-columns:1.2fr .8fr;gap:13px}.panel{background:linear-gradient(180deg,#12213a,#0d192c);border:1px solid var(--line);border-radius:22px;box-shadow:0 18px 50px rgba(0,0,0,.25)}.main{padding:22px}.eyebrow{font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}.equity{font-size:48px;font-weight:900;letter-spacing:-.04em;margin:8px 0}.change{font-size:17px;font-weight:850}.good{color:var(--green)}.bad{color:var(--red)}.blue{color:var(--blue)}.note{font-size:13px;color:var(--muted);line-height:1.5;margin-top:10px}
.metrics{padding:13px;display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric{background:rgba(255,255,255,.035);border:1px solid var(--line);border-radius:17px;padding:15px}.metric b{display:block;font-size:22px;margin-top:6px}.metric small{display:block;color:var(--muted);margin-top:5px;line-height:1.35}
.section{margin-top:13px;padding:18px}.head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:13px}.title{font-size:17px;font-weight:850}.badge{font-size:11px;color:var(--blue);border:1px solid rgba(124,184,255,.18);background:rgba(124,184,255,.08);padding:6px 9px;border-radius:999px}.marketgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.market,.position{background:rgba(255,255,255,.032);border:1px solid var(--line);border-radius:17px;padding:15px}.mrow{display:flex;justify-content:space-between;gap:12px}.asset{font-size:18px;font-weight:900}.price{font-size:25px;font-weight:900;margin-top:5px}.signal{font-size:11px;font-weight:900;padding:7px 9px;border-radius:999px;height:max-content;background:rgba(124,184,255,.09);color:var(--blue)}.reason{margin-top:12px;font-size:13px;line-height:1.45;color:var(--muted)}.criteria{font-size:12px;margin-top:7px;color:#c8d4e8}
.position{margin-top:9px}.position:first-child{margin-top:0}.phead{display:flex;justify-content:space-between;gap:12px}.pnl{text-align:right;font-size:18px;font-weight:900}.levels{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:13px}.level{background:#0a1527;padding:10px;border-radius:12px}.level span{display:block;color:var(--muted);font-size:10px;margin-bottom:4px}.level b{font-size:12px}.trade{display:grid;grid-template-columns:1fr auto;gap:12px;padding:11px 0;border-top:1px solid var(--line)}.trade:first-child{border-top:0}.trade small{display:block;color:var(--muted);margin-top:4px}.engine{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.info{background:rgba(255,255,255,.032);border:1px solid var(--line);border-radius:14px;padding:11px}.info span{display:block;color:var(--muted);font-size:10px;margin-bottom:5px}.info b{font-size:13px}.explain{margin-top:13px;padding:13px;border-radius:14px;background:rgba(124,184,255,.06);border:1px solid rgba(124,184,255,.15);font-size:12px;line-height:1.55;color:#c9daf4}.alert{margin-top:10px;padding:11px 13px;border-radius:13px;background:rgba(255,121,149,.08);border:1px solid rgba(255,121,149,.18);font-size:12px}.empty{color:var(--muted);font-size:13px}.footer{text-align:center;color:#6e809c;font-size:11px;margin-top:15px}button{border:0;border-radius:12px;background:#203754;color:white;font-weight:800;padding:10px 13px;cursor:pointer}
@media(max-width:760px){.hero,.marketgrid{grid-template-columns:1fr}.equity{font-size:40px}.levels,.engine{grid-template-columns:1fr 1fr}}@media(max-width:480px){.wrap{padding:18px 12px 35px}.top h1{font-size:24px}.equity{font-size:36px}.metric b{font-size:19px}.section{padding:14px}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>CRYPTO LAB</h1><div class="sub">Simulation fictive · données publiques Kraken</div></div><div class="live" id="live">● EN LIGNE</div></div>
<div class="hero"><div class="panel main"><div class="eyebrow">Valeur totale estimée</div><div class="equity" id="equity">—</div><div class="change" id="gain">—</div><div class="note">Valeur du portefeuille en tenant compte des liquidités et de la valeur actuelle des positions, avec frais et glissement simulés.</div></div>
<div class="panel metrics"><div class="metric"><div class="eyebrow">Liquidités</div><b id="cash">—</b><small>Capital encore disponible.</small></div><div class="metric"><div class="eyebrow">Capital engagé</div><b id="invested">—</b><small>Coût des positions ouvertes.</small></div><div class="metric"><div class="eyebrow">P/L latent</div><b id="upnl">—</b><small>Gain/perte non encore réalisé(e).</small></div><div class="metric"><div class="eyebrow">Drawdown max.</div><b id="drawdown">—</b><small>Plus forte baisse depuis un sommet.</small></div></div></div>
<div class="panel section"><div class="head"><div><div class="title">Marchés surveillés</div><div class="note">Ce que voit l'algo et pourquoi il agit ou attend.</div></div><div class="badge">cycle ≈ 30 s</div></div><div class="marketgrid" id="markets"><div class="empty">Chargement…</div></div></div>
<div class="panel section"><div class="head"><div><div class="title">Positions ouvertes</div><div class="note">Entrée, prix actuel, stop, objectif et performance latente.</div></div><div class="badge" id="pc">0 position</div></div><div id="positions"><div class="empty">Aucune position.</div></div></div>
<div class="panel section"><div class="head"><div><div class="title">Historique</div><div class="note">Derniers trades clôturés et résultat net simulé.</div></div><div class="badge" id="tc">0 trade</div></div><div id="trades"><div class="empty">Aucun trade clôturé.</div></div></div>
<div class="panel section"><div class="head"><div><div class="title">État du moteur</div><div class="note">Santé du serveur et statistiques de la simulation.</div></div><button onclick="load()">Actualiser</button></div><div class="engine"><div class="info"><span>Dernier cycle</span><b id="cycle">—</b></div><div class="info"><span>Uptime</span><b id="uptime">—</b></div><div class="info"><span>Trades gagnants</span><b id="wins">—</b></div><div class="info"><span>Win rate</span><b id="wr">—</b></div></div><div id="messages"></div><div class="explain"><b>Comment lire la stratégie :</b> l'algo n'entre que si tendance, cassure et volume sont réunis. Le stop représente une sortie défensive simulée, l'objectif une sortie bénéficiaire visée. Cette page suit une simulation avec argent fictif et ne garantit aucun résultat réel.</div></div>
<div class="footer">Capital initial 500 € · frais simulés <span id="fee">—</span> par côté · glissement <span id="slip">—</span> par côté</div></div>
<script>
const eur=v=>Number(v||0).toLocaleString('fr-FR',{minimumFractionDigits:2,maximumFractionDigits:2})+' €';const pct=v=>Number(v||0).toLocaleString('fr-FR',{minimumFractionDigits:2,maximumFractionDigits:2})+' %';const signed=v=>(Number(v)>=0?'+':'')+eur(v);const cls=v=>Number(v)>=0?'good':'bad';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));const tm=t=>t?new Date(t*1000).toLocaleTimeString('fr-FR'):'Jamais';const dur=s=>{s=Number(s||0);let h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h?`${h} h ${m} min`:`${m} min`};
async function load(){try{let r=await fetch('/api/status?x='+Date.now(),{cache:'no-store'});let d=await r.json();equity.textContent=eur(d.equity);gain.textContent=`${signed(d.gain_loss)} (${d.gain_loss_pct>=0?'+':''}${pct(d.gain_loss_pct)}) depuis 500 €`;gain.className='change '+cls(d.gain_loss);cash.textContent=eur(d.cash);invested.textContent=eur(d.invested);upnl.textContent=signed(d.unrealized_pnl);upnl.className=cls(d.unrealized_pnl);drawdown.textContent=pct(d.drawdown);
let mk=Object.entries(d.markets||{});markets.innerHTML=mk.length?mk.map(([n,m])=>`<div class="market"><div class="mrow"><div><div class="asset">${esc(n)}</div><div class="price">${eur(m.ask)}</div></div><div class="signal">${esc(m.state)}</div></div><div class="reason"><b>Pourquoi :</b> ${esc(m.reason||'—')}</div><div class="criteria">${esc(m.details||'')}</div></div>`).join(''):'<div class="empty">Données disponibles après le prochain cycle.</div>';
let ps=Object.entries(d.positions||{});pc.textContent=`${ps.length} position${ps.length>1?'s':''}`;positions.innerHTML=ps.length?ps.map(([n,p])=>`<div class="position"><div class="phead"><div><div class="asset">${esc(n)}</div><div class="note">Entrée ${eur(p.entry)} · engagé ${eur(p.cost)}</div></div><div class="pnl ${cls(p.unrealized_pnl||0)}">${signed(p.unrealized_pnl||0)}<div class="note">${p.unrealized_pct>=0?'+':''}${pct(p.unrealized_pct||0)}</div></div></div><div class="levels"><div class="level"><span>Prix actuel</span><b>${p.current_bid?eur(p.current_bid):'—'}</b></div><div class="level"><span>Stop</span><b>${eur(p.stop)}</b></div><div class="level"><span>Objectif</span><b>${eur(p.target)}</b></div><div class="level"><span>Quantité</span><b>${Number(p.qty).toPrecision(5)}</b></div></div></div>`).join(''):'<div class="empty">Aucune position ouverte. L’algo attend un signal complet.</div>';
let tr=d.last_trades||[];tc.textContent=`${d.trades_count} trade${d.trades_count>1?'s':''}`;trades.innerHTML=tr.length?tr.slice().reverse().map(t=>`<div class="trade"><div><b>${esc(t.asset)}</b><small>Entrée ${eur(t.entry)} → sortie ${eur(t.exit)} · ${esc(t.reason)}</small></div><b class="${cls(t.pnl)}">${signed(t.pnl)}</b></div>`).join(''):'<div class="empty">Aucun trade clôturé pour le moment.</div>';
cycle.textContent=tm(d.last_ok);uptime.textContent=dur(d.uptime_seconds);wins.textContent=`${d.wins}/${d.trades_count}`;wr.textContent=d.win_rate==null?'—':d.win_rate.toFixed(1)+' %';fee.textContent=pct(d.fee_pct);slip.textContent=pct(d.slippage_pct);let ms=[];if(d.warnings?.length)ms.push(`<div class="alert"><b>Avertissement :</b> ${d.warnings.map(esc).join(' · ')}</div>`);if(d.last_error)ms.push(`<div class="alert"><b>Erreur :</b> ${esc(d.last_error)}</div>`);messages.innerHTML=ms.join('');live.textContent='● EN LIGNE'}catch(e){live.textContent='● INDISPONIBLE';messages.innerHTML='<div class="alert">Impossible de joindre le serveur.</div>'}}
load();setInterval(load,5000);
</script></body></html>"""


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
