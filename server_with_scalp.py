"""Adds /rapide and /api/rapide to the existing Crypto Lab server without replacing it."""
import json, threading
from pathlib import Path
from urllib.parse import urlparse
import server
import scalp_engine

if not hasattr(server,'Handler') or not callable(getattr(server,'main',None)):
    raise RuntimeError('Cette extension nécessite server.Handler et server.main. Conserver le démarrage précédent et demander une adaptation.')

class CombinedHandler(server.Handler):
    def do_GET(self):
        path=urlparse(self.path).path.rstrip('/') or '/'
        if path=='/':
            nav = ('<nav aria-label="Simulations" style="max-width:1100px;margin:18px auto 0;'
                   'padding:0 18px;display:flex;gap:12px;flex-wrap:wrap">'
                   '<a href="/" aria-current="page" style="padding:10px 16px;border-radius:12px;'
                   'background:#203754;color:#f5f8ff;text-decoration:none">Classique · 500 €</a>'
                   '<a href="/rapide" style="padding:10px 16px;border-radius:12px;'
                   'background:#153d3a;color:#5ee0b5;text-decoration:none;font-weight:700">'
                   'Rapide ×10 · 200 € →</a></nav>')
            self._send_html(server.DASHBOARD.replace('<body>', '<body>'+nav, 1))
            return
        if path=='/rapide':
            data=(Path(__file__).parent/'scalp.html').read_bytes();content='text/html; charset=utf-8'
        elif path=='/api/rapide':
            data=json.dumps(scalp_engine.snapshot(),ensure_ascii=False,allow_nan=False).encode();content='application/json; charset=utf-8'
        else:return super().do_GET()
        self.send_response(200);self.send_header('Content-Type',content);self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

if __name__=='__main__':
    server.Handler=CombinedHandler
    threading.Thread(target=scalp_engine.loop,daemon=True).start()
    server.main()
