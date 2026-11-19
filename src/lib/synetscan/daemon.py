"""synetscand: background service owning all state; serves a JSON API on a unix socket."""
import json
import os
import signal
import socket
import socketserver
import threading
import time

from . import __version__, netinfo, probes
from . import config as config_mod
from .classify import PORT_NAMES, TYPES
from .scanner import ScanCancelled, Scanner
from .store import Store
from .util import log, now, raise_fd_limit

MAX_REQUEST = 1024 * 1024


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

    # ---------------------------------------------------------------- scanning
    def scanning(self):
        return self.scan_thread is not None and self.scan_thread.is_alive()

    def start_scan(self, trigger="manual"):
        with self.state_lock:
            if self.scanning():
                return False
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
            summary = self.store.merge_scan(result)
            summary["trigger"] = trigger
            self.last_error = ""
        except ScanCancelled:
            log.info("scan cancelled")
            self.last_error = "cancelled"
        except Exception as e:  # noqa: BLE001
            log.exception("scan failed")
            self.last_error = str(e)
        finally:
            with self.state_lock:
                self.state.update(status="idle", phase="", done=0, total=0)

    def next_scan_at(self):
        cfg = self.store.config
        if not cfg.get("schedule_enabled"):
            return None
        last = self.store.scans[-1]["finished"] if self.store.scans else self.started_at
        # failed/cancelled scans count as well, so errors never cause a tight retry loop
        last = max(last, self.last_attempt)
        return last + int(cfg.get("schedule_interval", 60)) * 60

    def scheduler(self):
        if self.store.config.get("scan_on_start", True):
            self.start_scan("startup")
        while not self.stop_event.wait(5):
            nxt = self.next_scan_at()
            if nxt is not None and now() >= nxt and not self.scanning():
                self.start_scan("schedule")

    # --------------------------------------------------------------------- API
    def handle(self, req):
        action = req.get("action", "")
        fn = getattr(self, "api_" + action, None)
        if not action.isidentifier() or fn is None:
            raise ApiError("unknown_action", "Unknown action: %s" % action)
        return fn(req.get("params") or {}, req.get("user", ""))

    def api_status(self, p, user):
        with self.state_lock:
            st = dict(self.state)
        last = self.store.scans[-1] if self.store.scans else None
        lt = time.localtime()
        st.update(version=__version__, last_scan=last, next_scan=self.next_scan_at(),
                  last_error=self.last_error, now=now(), ping=probes.ping_available(),
                  tz_offset=lt.tm_gmtoff, tz_name=lt.tm_zone)
        return st

    def api_overview(self, p, user):
        devices = self.store.list_devices()
        ifaces = netinfo.interfaces()
        gws = netinfo.default_gateways()
        for i in ifaces:
            i["gateway"] = gws.get(i["name"], "")
        types = {}
        for d in devices:
            if d.get("online"):
                types[d["type"]] = types.get(d["type"], 0) + 1
        day = now() - 86400
        return {
            "status": self.api_status(p, user),
            "hostname": netinfo.hostname(),
            "interfaces": ifaces,
            "dns": netinfo.dns_servers(),
            "counts": {
                "total": len(devices),
                "online": sum(1 for d in devices if d.get("online")),
                "offline": sum(1 for d in devices if not d.get("online")),
                "new24h": sum(1 for d in devices if d.get("first_seen", 0) >= day and not d.get("baseline")),
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
        did = p.get("id")
        try:
            dev = self.store.update_device(did, p)
        except KeyError:
            raise ApiError("not_found", "Device not found")
        return {"id": dev["id"]}

    def api_device_known(self, p, user):
        self.store.set_known(list(p.get("ids") or []), bool(p.get("known", True)))
        return {}

    def api_device_delete(self, p, user):
        return {"deleted": self.store.delete_devices(list(p.get("ids") or []))}

    def api_wake(self, p, user):
        dev = self.store.devices.get(p.get("id", ""))
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
        return {"deleted": self.store.clear_offline()}

    def api_reset(self, p, user):
        if self.scanning():
            raise ApiError("busy", "A scan is running")
        self.store.reset()
        return {}

    def api_export(self, p, user):
        return {"csv": self.store.export_csv()}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        service = self.server.service
        try:
            line = self.rfile.readline(MAX_REQUEST)
            req = json.loads(line.decode("utf-8"))
            data = service.handle(req)
            resp = {"success": True, "data": data}
        except ApiError as e:
            err = {"code": e.code, "message": e.message}
            err.update(e.extra)
            resp = {"success": False, "error": err}
        except Exception as e:  # noqa: BLE001
            log.exception("API error")
            resp = {"success": False, "error": {"code": "internal", "message": str(e)}}
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def socket_path(var_dir):
    return os.path.join(var_dir, "synetscan.sock")


def run(var_dir):
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
        s.sendall(json.dumps({"action": action, "params": params or {}, "user": user}).encode("utf-8") + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8"))
    finally:
        s.close()
