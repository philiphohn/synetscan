"""Persistent state: devices, events, scan history, configuration."""
import csv
import io
import os
import threading

from . import config as config_mod
from .classify import TYPES, bogus_model, display_name
from .util import now, read_json, write_json

MAX_EVENTS = 1000
MAX_SCANS = 100
COPY_FIELDS = ("ip", "mac", "vendor", "hostname", "netbios", "workgroup", "mdns_name", "services",
               "instances", "model", "friendly", "upnp", "http", "ports", "rtt", "iface", "via",
               "random_mac", "self", "gateway", "ssdp_server")


def device_id(host):
    return host["mac"] if host.get("mac") else "ip:" + host["ip"]


class Store:
    def __init__(self, directory):
        self.dir = directory
        self.lock = threading.RLock()
        os.makedirs(directory, exist_ok=True)
        self.devices = read_json(self._p("devices.json"), {}) or {}
        self.events = read_json(self._p("events.json"), []) or []
        self.scans = read_json(self._p("scans.json"), []) or []
        self.config = config_mod.merged(read_json(self._p("config.json"), {}))
        self._migrate()

    def _migrate(self):
        for d in self.devices.values():
            if bogus_model(d.get("model"), d.get("vendor")):
                d.pop("model", None)
        from .classify import DEFAULT_PORTS, OLD_DEFAULT_PORTS
        if sorted(self.config.get("ports") or []) == OLD_DEFAULT_PORTS:
            self.config["ports"] = list(DEFAULT_PORTS)
        # 1.0.0 did not flag the devices of the first scan; they were found by the earliest scan
        if self.devices and self.scans and not any("baseline" in d for d in self.devices.values()):
            first = min(s.get("finished", 0) for s in self.scans)
            for d in self.devices.values():
                d["baseline"] = d.get("first_seen", 0) <= first

    def _p(self, name):
        return os.path.join(self.dir, name)

    # ------------------------------------------------------------- persistence
    def save_devices(self):
        write_json(self._p("devices.json"), self.devices)

    def save_events(self):
        write_json(self._p("events.json"), self.events[-MAX_EVENTS:])

    def save_scans(self):
        write_json(self._p("scans.json"), self.scans[-MAX_SCANS:])

    def save_config(self):
        write_json(self._p("config.json"), self.config)

    def _event(self, kind, dev, detail="", ts=None):
        self.events.append({"ts": ts or now(), "kind": kind, "id": dev.get("id"),
                            "name": display_name(dev), "ip": dev.get("ip", ""),
                            "mac": dev.get("mac", ""), "detail": detail})

    # ------------------------------------------------------------------ scans
    def merge_scan(self, result):
        """Merge a scan result. Returns summary dict."""
        with self.lock:
            ts = result["finished"]
            seen = set()
            new = back = changed = 0
            threshold = int(self.config.get("offline_after_scans", 1))
            first_scan = not self.devices
            # A device without MAC that now has one: re-key the record
            for host in result["hosts"]:
                did = device_id(host)
                if host.get("mac") and did not in self.devices and ("ip:" + host["ip"]) in self.devices:
                    old = self.devices.pop("ip:" + host["ip"])
                    old["id"] = did
                    self.devices[did] = old
                dev = self.devices.get(did)
                if dev is None:
                    dev = {"id": did, "first_seen": ts, "name": "", "notes": "", "type_user": "",
                           "known": first_scan, "baseline": first_scan, "ip_history": [], "online": False}
                    self.devices[did] = dev
                    is_new = True
                else:
                    is_new = False
                was_online = dev.get("online", False)
                old_ip = dev.get("ip")
                for k in COPY_FIELDS:
                    v = host.get(k)
                    if v not in (None, "", [], {}) or k in ("ports", "rtt", "via"):
                        dev[k] = v
                    elif k in ("self", "gateway"):
                        dev.pop(k, None)
                if bogus_model(dev.get("model"), dev.get("vendor")):
                    dev.pop("model", None)  # a scan leaves it empty, which would keep the old value
                dev["type_auto"] = host.get("type", "unknown")
                dev["last_seen"] = ts
                dev["online"] = True
                dev["missed"] = 0
                if old_ip and old_ip != host["ip"]:
                    hist = [h for h in dev.get("ip_history", []) if h != old_ip]
                    dev["ip_history"] = ([old_ip] + hist)[:5]
                    self._event("ip_changed", dev, "%s → %s" % (old_ip, host["ip"]), ts)
                    changed += 1
                if is_new:
                    if not first_scan:
                        self._event("new", dev, dev.get("vendor", ""), ts)
                    new += 1
                elif not was_online:
                    self._event("online", dev, "", ts)
                    back += 1
                seen.add(did)
            offline = 0
            for did, dev in self.devices.items():
                if did in seen:
                    continue
                if not self._in_scope(dev, result):
                    continue
                dev["missed"] = dev.get("missed", 0) + 1
                if dev.get("online") and dev["missed"] >= threshold:
                    dev["online"] = False
                    self._event("offline", dev, "", ts)
                    offline += 1
            forget = int(self.config.get("forget_after_days", 0))
            if forget:
                limit = ts - forget * 86400
                for did in [d for d, v in self.devices.items() if not v.get("online") and v.get("last_seen", 0) < limit]:
                    del self.devices[did]
            summary = {"started": result["started"], "finished": ts, "duration": result["duration"],
                       "targets": result["targets"], "target_count": result["target_count"],
                       "found": len(result["hosts"]), "new": new, "offline": offline,
                       "online_again": back, "ip_changed": changed}
            if first_scan and result["hosts"]:
                self.events.append({"ts": ts, "kind": "baseline", "id": None, "name": "",
                                    "ip": "", "mac": "", "detail": str(len(result["hosts"]))})
            self.scans.append(summary)
            self.save_devices()
            self.save_events()
            self.save_scans()
            return summary

    def _in_scope(self, dev, result):
        """Only mark a device offline if its last IP was part of this scan's targets."""
        ips = result.get("_target_ips")
        return ips is None or dev.get("ip") in ips

    # ---------------------------------------------------------------- devices
    def list_devices(self):
        with self.lock:
            out = []
            for dev in self.devices.values():
                d = dict(dev)
                d["type"] = dev.get("type_user") or dev.get("type_auto") or "unknown"
                d["display_name"] = display_name(dev)
                d["detected_name"] = display_name(dict(dev, name=""))
                out.append(d)
            return out

    def update_device(self, did, fields):
        with self.lock:
            dev = self.devices.get(did)
            if dev is None:
                raise KeyError(did)
            if "name" in fields:
                dev["name"] = str(fields["name"]).strip()[:64]
            if "notes" in fields:
                dev["notes"] = str(fields["notes"])[:1000]
            if "type_user" in fields:
                t = str(fields["type_user"] or "")
                dev["type_user"] = t if t in TYPES else ""
            if "known" in fields:
                dev["known"] = bool(fields["known"])
            self.save_devices()
            return dev

    def set_known(self, ids, known=True):
        with self.lock:
            for did in ids:
                if did in self.devices:
                    self.devices[did]["known"] = bool(known)
            self.save_devices()

    def delete_devices(self, ids):
        with self.lock:
            n = 0
            for did in ids:
                if self.devices.pop(did, None) is not None:
                    n += 1
            self.save_devices()
            return n

    def clear_offline(self):
        with self.lock:
            ids = [d for d, v in self.devices.items() if not v.get("online")]
            return self.delete_devices(ids)

    def clear_events(self):
        with self.lock:
            self.events = []
            self.save_events()

    def reset(self):
        with self.lock:
            self.devices, self.events, self.scans = {}, [], []
            self.save_devices()
            self.save_events()
            self.save_scans()

    def export_csv(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Name", "Status", "Type", "IP", "MAC", "Vendor", "Hostname", "Model",
                    "Open ports", "Known", "First seen", "Last seen", "Notes"])
        import time as _t
        fmt = lambda ts: _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(ts)) if ts else ""  # noqa: E731
        for d in sorted(self.list_devices(), key=lambda x: tuple(int(p) for p in x.get("ip", "0.0.0.0").split("."))):
            w.writerow([d["display_name"], "online" if d.get("online") else "offline", d["type"],
                        d.get("ip", ""), d.get("mac", ""), d.get("vendor", ""),
                        d.get("hostname") or d.get("mdns_name") or d.get("netbios") or "",
                        d.get("model", ""), " ".join(str(p) for p in d.get("ports", [])),
                        "yes" if d.get("known") else "no", fmt(d.get("first_seen")),
                        fmt(d.get("last_seen")), d.get("notes", "")])
        return buf.getvalue()
