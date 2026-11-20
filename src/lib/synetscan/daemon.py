"""synetscand: background service owning all state; serves a JSON API on a unix socket."""
import json
import os
import re
import signal
import socket
import socketserver
import threading
import time

from . import __version__, ipv6, netinfo, probes
from . import config as config_mod
from .classify import PORT_NAMES, TYPES
from .scanner import ScanCancelled, Scanner
from .store import MAX_DEVICES, Store
from .util import clean_text, error_text, log, make_private, now, raise_fd_limit

MAX_REQUEST = 1024 * 1024
_ACTION = re.compile(r"^[a-z_]{1,32}$")
_DATA_FILES = ("devices.json", "events.json", "scans.json", "config.json")


def _ids(p):
    """The device ids of a request as a list of strings, whatever was sent."""
    ids = p.get("ids")
    return [i for i in ids if isinstance(i, str)][:MAX_DEVICES] if isinstance(ids, list) else []


class ApiError(Exception):
    """An error for the UI. `code` selects the translated message; `extra` fills it in."""

    def __init__(self, code, message="", **extra):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.extra = extra


class Service:
    def __init__(self, var_dir):
        self.var_dir = var_dir
        self.store = Store(var_dir)
        self.cancel = threading.Event()
        self.scan_thread = None
        self.state = {"status": "idle", "phase": "", "done": 0, "total": 0, "found": 0,
                      "started": None, "trigger": ""}
        self.state_lock = threading.Lock()
        self.started_at = now()
        self.stop_event = threading.Event()
        self.last_error = ""
        self.last_attempt = 0
        # A fresh installation scans nothing until the app has been opened once: installing the
        # package causes no network activity of its own. Any data file, even an emptied or damaged
        # one, means it was installed and used before (Delete All Data keeps the schedule running).
        self.awaiting_open = not any(os.path.exists(os.path.join(var_dir, n)) for n in _DATA_FILES)

    # ---------------------------------------------------------------- scanning
    def scanning(self):
        return self.scan_thread is not None and self.scan_thread.is_alive()

    def start_scan(self, trigger="manual"):
        with self.state_lock:
            if self.scanning():
                return False
            self.awaiting_open = False
            self.cancel.clear()
            self.last_attempt = now()
            self.state.update(status="scanning", phase="prepare", done=0, total=0, found=0,
                              started=now(), trigger=trigger)
            self.scan_thread = threading.Thread(target=self._scan, args=(trigger,), name="scan", daemon=True)
            self.scan_thread.start()
            return True

    def _progress(self, phase, done, total, found):
        with self.state_lock:
            self.state.update(phase=phase, done=done, total=total, found=found)

    def _scan(self, trigger):
        try:
            with self.store.lock:
                cfg = dict(self.store.config)
            result = Scanner(cfg, progress=self._progress, cancel=self.cancel).run()
            result["trigger"] = trigger
            summary = self.store.merge_scan(result)
            self.last_error = ""
        except ScanCancelled:
            log.info("scan cancelled")
            self.last_error = "cancelled"
        except Exception as e:  # noqa: BLE001
            log.exception("scan failed")
            self.last_error = error_text(e)
        finally:
            with self.state_lock:
                self.state.update(status="idle", phase="", done=0, total=0)

    def next_scan_at(self):
        cfg = self.store.config
        if not cfg.get("schedule_enabled"):
            return None
        scans = self.store.scans
        last = scans[-1]["finished"] if scans else self.started_at
        # failed/cancelled scans count as well, so errors never cause a tight retry loop
        last = max(last, self.last_attempt)
        try:
            interval = max(1, int(cfg.get("schedule_interval", 60)))
        except (TypeError, ValueError):
            interval = 60
        return last + interval * 60

    def scheduler(self):
        if self.awaiting_open:
            log.info("no scan yet: the first scan starts when SynetScan is opened")
        elif self.store.config.get("scan_on_start", True):
            self.start_scan("startup")
        while not self.stop_event.wait(5):
            try:
                nxt = self.next_scan_at()
                if nxt is not None and now() >= nxt and not self.scanning() and not self.awaiting_open:
                    self.start_scan("schedule")
            except Exception:  # noqa: BLE001 - the schedule must outlive any single mistake
                log.exception("scheduler")

    # --------------------------------------------------------------------- API
    def handle(self, req):
        action = req.get("action") if isinstance(req, dict) else None
        fn = getattr(self, "api_" + action, None) if isinstance(action, str) and _ACTION.match(action) else None
        if fn is None:
            raise ApiError("unknown_action", "Unknown action")
        params = req.get("params")
        return fn(params if isinstance(params, dict) else {}, clean_text(req.get("user"), 128))

    def api_status(self, p, user):
        with self.state_lock:
            st = dict(self.state)
        scans = self.store.scans  # a reset swaps the list, it never empties this one
        last = scans[-1] if scans else None
        lt = time.localtime()
        st.update(version=__version__, last_scan=last, next_scan=self.next_scan_at(),
                  awaiting_open=self.awaiting_open,
                  last_error=self.last_error, now=now(), ping=probes.ping_available(),
                  tz_offset=lt.tm_gmtoff, tz_name=lt.tm_zone)
        return st

    def api_opened(self, p, user):
        """The app was opened while the service waits for that: start the first scan."""
        if self.awaiting_open:
            if self.store.config.get("scan_on_start", True):
                if self.start_scan("open"):
                    log.info("first scan started: SynetScan was opened by %s", user or "?")
            else:
                self.started_at = now()  # the schedule counts from the opening, not from a boot long ago
            self.awaiting_open = False
        return self.api_status(p, user)

    def api_overview(self, p, user):
        devices = self.store.list_devices()
        ifaces = netinfo.interfaces()
        gws = netinfo.default_gateways()
        v6, old = {}, {}
        for a in sorted(ipv6.own_addresses(), key=lambda a: a.get("deprecated", False)):
            if a["scope"] != "link":
                v6.setdefault(a["dev"], []).append("%s/%d" % (a["ip"], a["prefix"]))
                if a.get("deprecated"):
                    old.setdefault(a["dev"], []).append("%s/%d" % (a["ip"], a["prefix"]))
        for i in ifaces:
            i["gateway"] = gws.get(i["name"], "")
            i["ipv6"] = v6.get(i["name"], [])
            i["ipv6_deprecated"] = old.get(i["name"], [])
        types = {}
        for d in devices:
            if d.get("online"):
                types[d["type"]] = types.get(d["type"], 0) + 1
        return {
            "status": self.api_status(p, user),
            "hostname": netinfo.hostname(),
            "interfaces": ifaces,
            "dns": netinfo.dns_servers(),
            "counts": {
                "total": len(devices),
                "online": sum(1 for d in devices if d.get("online")),
                "offline": sum(1 for d in devices if not d.get("online")),
                "new24h": sum(1 for d in devices if d.get("new24h")),
                "unknown": sum(1 for d in devices if not d.get("known")),
            },
            "types": types,
            "events": list(reversed(self.store.events[-12:])),
            "scans": list(reversed(self.store.scans[-20:])),
        }

    def api_devices(self, p, user):
        return {"devices": self.store.list_devices(), "port_names": {str(k): v for k, v in PORT_NAMES.items()},
                "types": TYPES}

    def api_device_update(self, p, user):
        try:
            dev = self.store.update_device(str(p.get("id")), p)
        except KeyError:
            raise ApiError("not_found", "Device not found")
        return {"id": dev["id"]}

    def api_device_known(self, p, user):
        self.store.set_known(_ids(p), bool(p.get("known", True)))
        return {}

    def api_device_delete(self, p, user):
        n = self.store.delete_devices(_ids(p))
        log.info("%d device(s) deleted by %s", n, user or "?")
        return {"deleted": n}

    def api_wake(self, p, user):
        dev = self.store.devices.get(str(p.get("id")))
        if not dev:
            raise ApiError("not_found", "Device not found")
        if not dev.get("mac"):
            raise ApiError("no_mac", "Device has no MAC address")
        broadcasts = {"255.255.255.255"}
        import ipaddress
        for i in netinfo.interfaces():
            if not i["virtual"] and i["prefix"] < 31:
                broadcasts.add(str(ipaddress.IPv4Network(i["network"]).broadcast_address))
        sent = probes.wake_on_lan(dev["mac"], sorted(broadcasts))
        log.info("WOL sent to %s by %s", dev["mac"], user)
        return {"sent": sent}

    def api_scan(self, p, user):
        started = self.start_scan("manual")
        if started:
            log.info("manual scan requested by %s", user or "?")
        return {"started": started}

    def api_cancel(self, p, user):
        self.cancel.set()
        return {}

    def api_events(self, p, user):
        return {"events": list(reversed(self.store.events))}

    def api_clear_events(self, p, user):
        self.store.clear_events()
        return {}

    def api_scans(self, p, user):
        return {"scans": list(reversed(self.store.scans))}

    def api_config_get(self, p, user):
        ifaces = [{"name": i["name"], "ip": i["ip"], "prefix": i["prefix"], "network": i["network"],
                   "virtual": i["virtual"], "up": i["up"]} for i in netinfo.interfaces()]
        return {"config": self.store.config, "defaults": config_mod.DEFAULTS, "interfaces": ifaces,
                "intervals": config_mod.INTERVALS, "port_names": {str(k): v for k, v in PORT_NAMES.items()}}

    def api_config_set(self, p, user):
        try:
            cfg = config_mod.validate(p.get("config") or {}, self.store.config)
        except config_mod.ConfigError as e:
            raise ApiError("invalid_config", str(e), field=e.field, value=e.value)
        with self.store.lock:
            self.store.config = cfg
            self.store.save_config()
        log.info("configuration changed by %s", user or "?")
        return {"config": cfg}

    def api_clear_offline(self, p, user):
        n = self.store.clear_offline()
        log.info("%d offline device(s) removed by %s", n, user or "?")
        return {"deleted": n}

    def api_reset(self, p, user):
        if self.scanning():
            raise ApiError("busy", "A scan is running")
        self.store.reset()
        log.info("all data deleted by %s", user or "?")
        return {}

    def api_export(self, p, user):
        return {"csv": self.store.export_csv()}


class _Handler(socketserver.StreamRequestHandler):
    timeout = 30  # a client that connects and then says nothing does not keep a thread

    def handle(self):
        service = self.server.service
        try:
            line = self.rfile.readline(MAX_REQUEST + 4096)
            req = json.loads(line.decode("utf-8"))
            data = service.handle(req)
            resp = {"success": True, "data": data}
        except ApiError as e:
            err = {"code": e.code, "message": e.message}
            err.update(e.extra)
            resp = {"success": False, "error": err}
        except Exception as e:  # noqa: BLE001
            log.exception("API error")
            resp = {"success": False, "error": {"code": "internal", "message": error_text(e)}}
        try:
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
        except OSError:
            pass  # the client has gone


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def socket_path(var_dir):
    return os.path.join(var_dir, "synetscan.sock")


def run(var_dir):
    # Device list, history, settings, log and the control socket are for the package user only.
    os.umask(0o077)
    make_private(*(os.path.join(var_dir, n) for n in
                   ("devices.json", "events.json", "scans.json", "config.json", "daemon.out")))
    raise_fd_limit()
    service = Service(var_dir)
    path = socket_path(var_dir)
    try:
        os.unlink(path)
    except OSError:
        pass
    # Bind relative to the var dir so long paths do not hit the AF_UNIX 108 byte limit.
    os.chdir(var_dir)
    server = _Server(os.path.basename(path), _Handler)
    # Only the package user (DSM runs the package's CGI as that user) may talk to the daemon;
    # everyone else has to go through api.cgi and its DSM session + admin check.
    os.chmod(path, 0o600)
    server.service = service

    def stop(*_):
        service.stop_event.set()
        service.cancel.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=service.scheduler, name="scheduler", daemon=True).start()
    log.info("synetscand %s listening on %s", __version__, path)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        try:
            os.unlink(path)
        except OSError:
            pass
        if service.scan_thread:
            service.scan_thread.join(timeout=5)
        log.info("synetscand stopped")


def request(var_dir, action, params=None, user="", timeout=30):
    """Client side helper used by the CGI and tools."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        path = socket_path(var_dir)
        if len(path) > 100:
            os.chdir(var_dir)
            path = os.path.basename(path)
        s.connect(path)
        # compact and unescaped: the line stays within what the service reads, like the body it came from
        s.sendall(json.dumps({"action": action, "params": params or {}, "user": user},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8", "replace") + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8"))
    finally:
        s.close()
