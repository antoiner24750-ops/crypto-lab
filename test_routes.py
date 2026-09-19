import unittest,sys,types,threading,urllib.request,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
class OldHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'ancienne simulation')
    def log_message(self,*args):pass
class Routes(unittest.TestCase):
    def test_additive_routes(self):
        fake=types.ModuleType('server');fake.Handler=OldHandler;fake.main=lambda:None
        with patch.dict(sys.modules,{'server':fake}):
            import server_with_scalp as wrapper
            http=ThreadingHTTPServer(('127.0.0.1',0),wrapper.CombinedHandler)
            worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
            try:
                base='http://127.0.0.1:'+str(http.server_port)
                with urllib.request.urlopen(base+'/') as r:self.assertEqual(r.read(),b'ancienne simulation')
                with urllib.request.urlopen(base+'/rapide') as r:self.assertIn(b'SHORT',r.read())
                with urllib.request.urlopen(base+'/api/rapide') as r:self.assertEqual(json.load(r)['config']['leverage'],10)
            finally:http.shutdown();http.server_close();worker.join()
