#!/usr/bin/env python3
"""Local preview: mock DSM desktop + the real api.cgi + the real daemon.

    python3 tools/devserver.py [--port 8640] [--var DIR] [--no-daemon]

Open http://127.0.0.1:8640/ (add ?lang=de for German).
"""
import argparse
import http.server
import os
import signal
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UI = os.path.join(ROOT, "src", "ui")
PREFIX = "/webman/3rdparty/SynetScan/"
MOCK = os.path.join(ROOT, "tools", "mock_dsm.html")


class Handler(http.server.SimpleHTTPRequestHandler):
    var_dir = None

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    def translate_path(self, path):
        path = urllib.parse.urlparse(path).path
        if path in ("/", "/index.html"):
            return MOCK
        if path.startswith(PREFIX):
            rel = os.path.normpath(path[len(PREFIX):]).lstrip("/")
            if rel.startswith(".."):
                return "/nonexistent"
            return os.path.join(UI, rel)
        return "/nonexistent"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _cgi(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        env = dict(os.environ, REQUEST_METHOD=self.command, QUERY_STRING=u.query,
                   CONTENT_LENGTH=str(len(body)), CONTENT_TYPE=self.headers.get("Content-Type", ""),
                   HTTP_X_SYNO_TOKEN=self.headers.get("X-SYNO-TOKEN", ""), SYNETSCAN_DEV="1",
                   SYNETSCAN_VAR=self.var_dir, GATEWAY_INTERFACE="CGI/1.1",
                   # SYNETSCAN_DEV_CLIENT=8.8.8.8 previews a remote (QuickConnect/internet) session;
                   # without it the browser address is left out and the UI treats the preview as local
                   REMOTE_ADDR=os.environ.get("SYNETSCAN_DEV_CLIENT", ""))
        r = subprocess.run([os.path.join(UI, "api.cgi")], input=body, capture_output=True, env=env, timeout=60)
        head, _, payload = r.stdout.partition(b"\r\n\r\n")
        status = 200
        headers = []
        for line in head.decode("latin-1").split("\r\n"):
            k, _, v = line.partition(":")
            if k.lower() == "status":
                status = int(v.strip().split()[0])
            elif k:
                headers.append((k, v.strip()))
        if r.stderr:
            sys.stderr.write(r.stderr.decode("utf-8", "replace"))
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == PREFIX + "api.cgi":
            return self._cgi()
        return super().do_GET()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == PREFIX + "api.cgi":
            return self._cgi()
        self.send_error(404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8640)
    ap.add_argument("--var", default=os.path.join(ROOT, ".devvar"))
    ap.add_argument("--no-daemon", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.var, exist_ok=True)
    Handler.var_dir = os.path.abspath(args.var)
    proc = None
    if not args.no_daemon:
        env = dict(os.environ, SYNOPKG_PKGVAR=Handler.var_dir)
        proc = subprocess.Popen([os.path.join(ROOT, "src", "bin", "synetscand"),
                                 os.path.join(Handler.var_dir, "synetscan.log")], env=env)
        time.sleep(0.5)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("SynetScan dev server: http://127.0.0.1:%d/  (data: %s)" % (args.port, Handler.var_dir))

    def stop(*_):
        if proc:
            proc.terminate()
            proc.wait(10)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
