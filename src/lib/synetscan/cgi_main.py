"""api.cgi: authenticate the DSM session and proxy the request to synetscand."""
import json
import os
import re
import select
import subprocess
import sys
import time
import urllib.parse

from . import daemon, netinfo

AUTH_CGI = "/usr/syno/synoman/webman/modules/authenticate.cgi"
VAR_DIR = "/var/packages/SynetScan/var"
# Everything that is not listed here changes something and needs a POST with a JSON body.
READ_ACTIONS = {"status", "overview", "devices", "events", "scans", "config_get", "export", "client"}
# What the service answers, and "client", which is answered here. Nothing else gets further.
ACTIONS = {name[4:] for name in dir(daemon.Service) if name.startswith("api_")} | {"client"}
USER_RE = re.compile(r"^[\w.@\\ $-]{1,128}$", re.U)
DRAIN_LIMIT = 16 * 1024 * 1024  # what is read of a body too large to use, before giving up
BODY_TIMEOUT = 15  # seconds for a body that arrives slower, or shorter, than announced


def respond(obj, status="200 OK", ctype="application/json; charset=utf-8", extra=None):
    body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
    out = sys.stdout.buffer
    # An API answer is data: never rendered, framed or sent along as a referrer.
    out.write(("Status: %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\n"
               "X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
               "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'\r\n" % (status, ctype)).encode())
    for k, v in (extra or {}).items():
        out.write(("%s: %s\r\n" % (k, v)).encode())
    out.write(b"\r\n" + body)
    out.flush()


def error(code, message, status="200 OK"):
    # DSM's nginx may swap 5xx/403 CGI answers for its own HTML error page, which would hide the
    # error code from the UI. Errors are always sent as 200 with "success": false (like DSM's
    # own web API); `status` only documents the HTTP meaning.
    respond({"success": False, "error": {"code": code, "message": message}})


def authenticate():
    """Return the DSM user name of the current session, or None.

    DSM's own authenticate.cgi decides: it checks the session cookie and, unless the admin
    switched DSM's CSRF protection off, the SynoToken. The token is taken from the request
    header only – the UI never puts it in a URL, where it would end up in logs."""
    if not os.access(AUTH_CGI, os.X_OK):
        return None
    env = dict(os.environ)
    token = env.get("HTTP_X_SYNO_TOKEN", "")
    env["QUERY_STRING"] = "SynoToken=" + urllib.parse.quote(token) if token else ""
    env["REQUEST_METHOD"] = "GET"
    env.pop("CONTENT_LENGTH", None)
    env.pop("CONTENT_TYPE", None)
    try:
        r = subprocess.run([AUTH_CGI], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    user = r.stdout.decode("utf-8", "replace").strip().splitlines()
    user = user[-1].strip() if user else ""
    return user if r.returncode == 0 and USER_RE.match(user) else None


def is_admin(user):
    if user in ("admin", "root"):
        return True
    try:
        with open("/etc/group", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 4 and parts[0] == "administrators":
                    if user in parts[3].split(","):
                        return True
    except OSError:
        pass
    for tool in ("/usr/syno/sbin/synogroup", "/bin/synogroup"):
        if os.access(tool, os.X_OK):
            try:
                out = subprocess.run([tool, "--get", "administrators"], capture_output=True,
                                     timeout=10).stdout.decode("utf-8", "replace")
            except (OSError, subprocess.SubprocessError):
                continue
            return re.search(r"\[%s\]" % re.escape(user), out) is not None
    return False


def cross_site():
    """True if the browser says the request was started by another website.

    Sec-Fetch-Site is set by the browser itself and cannot be forged by a page. SynetScan's
    UI is served from the same origin as this API, so its requests are always "same-origin"
    ("none": the address was typed in). Another site – also another web application on a
    neighbouring host name or port – has no business calling it. Older browsers do not send
    the header; for them the session token and the JSON-only POST below remain."""
    return os.environ.get("HTTP_SEC_FETCH_SITE", "").strip().lower() not in ("", "same-origin", "none")


def read_body():
    """The request body, read before anything is answered: a web server may drop the answer of
    a CGI that ends with its request body unread (seen over plain http on a DS923+, where
    refused POSTs then failed as network errors). None if it is larger than the service takes."""
    try:
        length = max(0, int(os.environ.get("CONTENT_LENGTH") or 0))
    except ValueError:
        length = 0
    stream = getattr(sys.stdin, "buffer", None)
    if not length or stream is None:
        return b""
    keep = length <= daemon.MAX_REQUEST
    chunks, left = [], min(length, DRAIN_LIMIT)
    try:
        fd = stream.fileno()
    except (OSError, ValueError, AttributeError):
        fd = None  # not a real file (tests)
    deadline = time.monotonic() + BODY_TIMEOUT
    try:
        while left > 0:
            if fd is not None:
                wait = deadline - time.monotonic()
                if wait <= 0 or not select.select([fd], [], [], wait)[0]:
                    break
                try:
                    chunk = os.read(fd, min(left, 65536))
                except BlockingIOError:  # a non-blocking stdin that woke up without data
                    continue
            else:
                chunk = stream.read(min(left, 65536))
            if not chunk:
                break
            left -= len(chunk)
            if keep:
                chunks.append(chunk)
    except (OSError, ValueError):
        pass
    return b"".join(chunks) if keep else None


def main():
    body = read_body()
    query = urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""))
    action = (query.get("action") or [""])[0]
    method = os.environ.get("REQUEST_METHOD", "GET").upper()

    if cross_site():
        return error("cross_site", "Request from another website refused", "403 Forbidden")
    user = authenticate()
    if not user:
        return error("auth", "Not logged in to DSM or session expired", "401 Unauthorized")
    if not is_admin(user):
        return error("permission", "SynetScan is only available to administrators", "403 Forbidden")
    if action not in ACTIONS:
        return error("unknown_action", "Unknown action", "400 Bad Request")
    if method not in ("GET", "POST") or (action not in READ_ACTIONS and method != "POST"):
        return error("method", "POST required", "405 Method Not Allowed")
    # A web page of another origin can make a browser send a form or plain text along with the
    # admin's cookies, but not JSON: that needs a permission DSM never gives (CORS preflight).
    if method == "POST" and not os.environ.get("CONTENT_TYPE", "").strip().lower().startswith("application/json"):
        return error("bad_request", "JSON body required", "415 Unsupported Media Type")

    if action == "client":
        # Answered here, not by the service: only the CGI sees the browser's address.
        return respond({"success": True, "data": netinfo.client_location(os.environ.get("REMOTE_ADDR", ""))})

    params = {}
    if method == "POST":
        if body is None:
            return error("too_large", "Request too large", "413 Payload Too Large")
        if body:
            try:
                params = json.loads(body.decode("utf-8"))
            except (ValueError, RecursionError):
                return error("bad_request", "Invalid JSON body", "400 Bad Request")
            if not isinstance(params, dict):
                return error("bad_request", "JSON object expected", "400 Bad Request")

    try:
        resp = daemon.request(VAR_DIR, action, params, user=user)
    except PermissionError:
        # the socket is private to the package user; this CGI apparently runs as someone else
        return error("daemon_perm", "api.cgi runs as uid %d and may not connect to the SynetScan service"
                     % os.getuid(), "503 Service Unavailable")
    except (OSError, ValueError):
        return error("daemon", "The SynetScan service is not running. Start the package in Package Center.",
                     "503 Service Unavailable")

    if action == "export" and resp.get("success") and (query.get("format") or [""])[0] == "csv":
        return respond(resp["data"]["csv"].encode("utf-8-sig"), ctype="text/csv; charset=utf-8",
                       extra={"Content-Disposition": 'attachment; filename="synetscan-devices.csv"'})
    respond(resp)
