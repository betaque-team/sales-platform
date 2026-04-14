import http.server
import urllib.request
import os

PORT = int(os.environ.get('PORT', 3100))
TARGET = 'http://localhost:3000'

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._proxy()
    def do_POST(self):
        self._proxy()
    def do_PUT(self):
        self._proxy()
    def do_PATCH(self):
        self._proxy()
    def do_DELETE(self):
        self._proxy()
    def do_OPTIONS(self):
        self._proxy()

    def _proxy(self):
        url = TARGET + self.path
        body = None
        if 'Content-Length' in self.headers:
            body = self.rfile.read(int(self.headers['Content-Length']))

        headers = {k: v for k, v in self.headers.items() if k.lower() != 'host'}
        req = urllib.request.Request(url, data=body, headers=headers, method=self.command)

        try:
            with urllib.request.urlopen(req) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ('transfer-encoding',):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding',):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        pass  # silence logs

if __name__ == '__main__':
    server = http.server.HTTPServer(('', PORT), ProxyHandler)
    print(f'Proxy listening on port {PORT}')
    server.serve_forever()
