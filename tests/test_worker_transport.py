"""A malicious coordinator must not redirect a volunteer's device token."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
import worker

seen=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        seen.append(self.path)
        if self.path=="/redirect":
            self.send_response(302);self.send_header("Location","/credential-sink");self.end_headers()
        else:
            body=b'[]' if self.path=="/array" else b'{"ok":true}'
            self.send_response(200);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    base=f"http://127.0.0.1:{server.server_port}"
    assert worker.get_json(base,"/ok")=={"ok":True}
    for path in ("/redirect","/array"):
        try:worker.get_json(base,path)
        except ValueError:pass
        else:raise AssertionError(path)
    assert "/credential-sink" not in seen
    for url in ("https://user:password@example.com","https://","https://example.com?token=x"):
        try:worker.validate_server_url(url)
        except ValueError:pass
        else:raise AssertionError(url)
finally:
    server.shutdown();server.server_close();thread.join()
print("WORKER_TRANSPORT_OK")
