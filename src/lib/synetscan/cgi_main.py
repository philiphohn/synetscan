"""api.cgi: authenticate the DSM session and proxy the request to synetscand."""
import json
import os
import re
import subprocess
import sys
import urllib.parse

from . import daemon, netinfo

AUTH_CGI = "/usr/syno/synoman/webman/modules/authenticate.cgi"
DEFAULT_VAR = "/var/packages/SynetScan/var"
WRITE_ACTIONS = {"device_update", "device_known", "device_delete", "wake", "scan", "cancel",
                 "clear_events", "config_set", "clear_offline", "reset"}
USER_RE = re.compile(r"^[\w.@\\ $-]{1,128}$", re.U)


def respond(obj, status="200 OK", ctype="application/json; charset=utf-8", extra=None):
    body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
    out = sys.stdout.buffer
    out.write(("Status: %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\n"
               "X-Content-Type-Options: nosniff\r\n" % (status, ctype)).encode())
    for k, v in (extra or {}).items():
        out.write(("%s: %s\r\n" % (k, v)).encode())
    out.write(b"\r\n" + body)
    out.flush()


def error(code, message, status="200 OK"):
    # DSM's nginx may swap 5xx/403 CGI answers for its own HTML error page, which would hide the
    # error code from the UI. Errors are always sent as 200 with "success": false (like DSM's
    # own web API); `status` only documents the HTTP meaning.
    respond({"success": False, "error": {"code": code, "message": message}})


def authenticate(query):
    """Return the DSM user name of the current session, or None."""
    if os.environ.get("SYNETSCAN_DEV") == "1":
        return "dev"
    if not os.access(AUTH_CGI, os.X_OK):
        return None
    env = dict(os.environ)
    token = env.get("HTTP_X_SYNO_TOKEN") or (query.get("SynoToken") or [""])[0]
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
    if os.environ.get("SYNETSCAN_DEV") == "1" or user in ("admin", "root"):
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


def main():
    var_dir = os.environ.get("SYNETSCAN_VAR", DEFAULT_VAR)
    query = urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""))
    action = (query.get("action") or [""])[0]
    method = os.environ.get("REQUEST_METHOD", "GET").upper()

    user = authenticate(query)
    if not user:
        return error("auth", "Not logged in to DSM or session expired", "401 Unauthorized")
    if not is_admin(user):
        return error("permission", "SynetScan is only available to administrators", "403 Forbidden")
    if action in WRITE_ACTIONS and method != "POST":
        return error("method", "POST required", "405 Method Not Allowed")

    if action == "client":
        # Answered here, not by the service: only the CGI sees the browser's address.
        return respond({"success": True, "data": netinfo.client_location(os.environ.get("REMOTE_ADDR", ""))})

    params = {}
    if method == "POST":
        try:
            length = int(os.environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > daemon.MAX_REQUEST:
            return error("too_large", "Request too large", "413 Payload Too Large")
        raw = sys.stdin.buffer.read(length) if length else b""
        if raw:
            try:
                params = json.loads(raw.decode("utf-8"))
            except ValueError:
                return error("bad_request", "Invalid JSON body", "400 Bad Request")
            if not isinstance(params, dict):
                return error("bad_request", "JSON object expected", "400 Bad Request")

    try:
        resp = daemon.request(var_dir, action, params, user=user)
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
