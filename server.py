"""Version serveur/headless de Crypto Lab pour Render.

- Réutilise la logique de algo.py
- N'ouvre aucune interface Tkinter
- Lance la simulation toutes les 30 secondes
- Expose un petit endpoint HTTP / et /health pour que Render voie un Web Service
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from algo import STATE, PAIRS, initial, market, cycle, save

status_lock = threading.Lock()
runtime_status = {
    "started_at": time.time(),
    "last_ok": 0,
    "last_error": None,
    "equity": None,
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

def simulation_loop():
    s = load_state()

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

            with status_lock:
                runtime_status["last_ok"] = time.time()
                runtime_status["last_error"] = None
                runtime_status["equity"] = round(equity, 2)
                runtime_status["alerts"] = alerts
                runtime_status["warnings"] = warnings

            print(
                f"[OK] equity={equity:.2f}€ "
                f"alerts={alerts or '-'} warnings={warnings or '-'}",
                flush=True,
            )

        except Exception as exc:
            with status_lock:
                runtime_status["last_error"] = str(exc)
            print(f"[ERROR] {exc}", flush=True)

        elapsed = time.time() - started
        time.sleep(max(1, 30 - elapsed))

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/health"):
            self._send_json({"error": "not found"}, 404)
            return

        with status_lock:
            data = dict(runtime_status)

        data["service"] = "crypto-lab"
        data["mode"] = "simulation uniquement"
        data["uptime_seconds"] = int(time.time() - data["started_at"])
        self._send_json(data)

    def log_message(self, fmt, *args):
        # Évite de polluer les logs Render à chaque ping de santé.
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
