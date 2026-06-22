import http.server
import socketserver
import mimetypes
import json
import os
import urllib.request
import urllib.error

# ── Chargement de la config unique ──
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devkit_config.json")
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

GUI_PORT = CONFIG["ports"]["GUI_FRONTEND"]       # 8092
API_PORT  = CONFIG["ports"]["ORCHESTRATOR_API"]   # 8095
BACKEND_URL = f"http://127.0.0.1:{API_PORT}"
DIRECTORY = "."

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _proxy_to_backend(self, method):
        """Proxyfie une requête API vers le backend (port 8095)."""
        target = f"{BACKEND_URL}{self.path}"
        try:
            body = None
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
            
            req = urllib.request.Request(
                target,
                data=body,
                headers={k: v for k, v in self.headers.items() 
                         if k.lower() not in ("host", "connection", "transfer-encoding")},
                method=method
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "content-encoding"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Proxy error: {e}"}).encode())

    def do_GET(self):
        if self.path.startswith("/api/") or self.path.startswith("/agent/") or self.path.startswith("/health") or self.path.startswith("/system/"):
            return self._proxy_to_backend("GET")
        if self.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(json.dumps(CONFIG).encode("utf-8"))
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/") or self.path.startswith("/agent/"):
            return self._proxy_to_backend("POST")
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def guess_type(self, path):
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

with socketserver.TCPServer(("", GUI_PORT), Handler) as httpd:
    print(f"🧰 DevKit GUI → http://localhost:{GUI_PORT}/realia_dev_gui.html")
    print(f"   (proxy API → {BACKEND_URL})")
    httpd.serve_forever()
