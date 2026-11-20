"""Persistent state: devices, events, scan history, configuration."""
import csv
import io
import os
import threading

from . import config as config_mod
from .classify import TYPES, bogus_model, display_name
from .util import clean_text, log, now, read_json, write_json

MAX_EVENTS = 1000
MAX_SCANS = 100
# More than a network that fits the scan limits has. A device that answers under ever new
# addresses cannot fill the volume: beyond this, the least valuable records go (see _trim).
MAX_DEVICES = 8192
_LIST_MAX = {"ports": 4096, "proxy_arp_for": 1024}  # entries kept per list; 64 for the others
COPY_FIELDS = ("ip", "mac", "vendor", "hostname", "netbios", "workgroup", "mdns_name", "services",
               "instances", "model", "friendly", "upnp", "http", "ports", "rtt", "iface", "via",
               "random_mac", "self", "gateway", "ssdp_server", "ipv6", "ipv6_router", "proxy_arp", "other_ips",
               "proxy_arp_for", "ipv6_deprecated")


def primary_address(dev):
    """The address to show and to open: IPv4, else the first (most global) IPv6 address."""
    return dev.get("ip") or (dev.get("ipv6") or [""])[0]


def device_id(host):
    return host["mac"] if host.get("mac") else "ip:" + host["ip"]


def safe_value(value, key="", depth=0):
    """A value found by a scan, made fit to keep and to show. Most of what a scan learns is
    what the devices say about themselves, and they can say anything: text is cleaned of
    invisible characters and cut to a sane length, lists and dicts are bounded."""
    if key == "ports" and depth == 0:
        ports = value if isinstance(value, (list, tuple, set)) else ()
        return sorted(p for p in ports if type(p) is int and 0 < p < 65536)[:_LIST_MAX["ports"]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return clean_text(value, 255)
    if depth < 2 and isinstance(value, (list, tuple, set)):
        return [safe_value(v, key, depth + 1) for v in list(value)[:_LIST_MAX.get(key, 64)]]
    if depth < 2 and isinstance(value, dict):
        return {clean_text(k, 40): safe_value(v, key, depth + 1) for k, v in list(value.items())[:16]}
    return clean_text(value, 255)


def csv_cell(value):
    """Spreadsheet programs run a cell that starts with = + - or @ as a formula. A leading
    apostrophe makes it plain text, so a device cannot name itself into the admin's Excel."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class Store:
    def __init__(self, directory):
        self.dir = directory
        self.lock = threading.RLock()
        os.makedirs(directory, exist_ok=True)
        self.devices = self._load("devices.json", dict)
        self.events = self._load("events.json", list)[-MAX_EVENTS:]
        self.scans = self._load("scans.json", list)[-MAX_SCANS:]
        self.config = config_mod.merged(read_json(self._p("config.json"), {}))
        self._migrate()

    def _load(self, name, kind):
        """A state file, or an empty one if it is missing or not what this version wrote."""
        data = read_json(self._p(name))
        if not isinstance(data, kind):
            return kind()
        if kind is dict:
            return {k: v for k, v in data.items() if isinstance(v, dict)}
        return [v for v in data if isinstance(v, dict)]

    def _migrate(self):
        for did, d in self.devices.items():
            d["id"] = did
            # older versions stored the devices' strings as they came in
            for k in COPY_FIELDS:
                if k in d:
                    d[k] = safe_value(d[k], k)
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
        del self.events[:-MAX_EVENTS]
        write_json(self._p("events.json"), self.events)

    def save_scans(self):
        del self.scans[:-MAX_SCANS]
        write_json(self._p("scans.json"), self.scans)

    def save_config(self):
        write_json(self._p("config.json"), self.config)

    def _event(self, kind, dev, detail="", ts=None):
        self.events.append({"ts": ts or now(), "kind": kind, "id": dev.get("id"),
                            "name": display_name(dev), "ip": primary_address(dev),
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
                if host.get("self"):
                    # 1.1.0 listed a NAS with several ports once per port: keep one entry
                    for other in [k for k, v in self.devices.items() if v.get("self") and k != did]:
                        del self.devices[other]
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
                    v = safe_value(host.get(k), k)
                    if v not in (None, "", [], {}) or k in ("ports", "rtt", "via"):
                        dev[k] = v
                    elif k in ("self", "gateway", "ipv6_router", "proxy_arp", "other_ips", "proxy_arp_for", "ipv6_deprecated"):
                        dev.pop(k, None)
                if "ipv6" in host and not host["ipv6"]:  # the scan looked at IPv6 and found none
                    dev.pop("ipv6", None)
                if bogus_model(dev.get("model"), dev.get("vendor")):
                    dev.pop("model", None)  # a scan leaves it empty, which would keep the old value
                if host.get("proxy_arp_for"):
                    # this MAC also answers for other hosts (proxy ARP): drop what earlier
                    # versions merged into it from them – names, pages, their IPs
                    for k in ("netbios", "workgroup", "hostname", "mdns_name", "friendly", "model",
                              "http", "services", "instances", "upnp"):
                        if not host.get(k):
                            dev.pop(k, None)
                    dev["ip_history"] = [a for a in dev.get("ip_history", []) if a not in host["proxy_arp_for"]]
                dev["type_auto"] = host["type"] if host.get("type") in TYPES else "unknown"
                dev["last_seen"] = ts
                dev["online"] = True
                dev["missed"] = 0
                if old_ip and host.get("ip") and old_ip != host["ip"] and old_ip not in (host.get("proxy_arp_for") or ()):
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
            self._trim()
            summary = {"started": result["started"], "finished": ts, "duration": result["duration"],
                       "targets": result["targets"], "target_count": result["target_count"],
                       "found": len(result["hosts"]), "new": new, "offline": offline,
                       "online_again": back, "ip_changed": changed}
            if result.get("ipv6"):
                summary["ipv6"] = result["ipv6"]
            if result.get("trigger"):
                summary["trigger"] = result["trigger"]
            if first_scan and result["hosts"]:
                self.events.append({"ts": ts, "kind": "baseline", "id": None, "name": "",
                                    "ip": "", "mac": "", "detail": str(len(result["hosts"]))})
            self.scans.append(summary)
            self.save_devices()
            self.save_events()
            self.save_scans()
            return summary

    def _trim(self):
        """Keep at most MAX_DEVICES records. What the admin has worked on – devices marked as
        known or given a name, type or note – goes last, and the NAS itself never. Of the rest,
        offline devices go first (longest unseen first), then the most recently discovered."""
        extra = len(self.devices) - MAX_DEVICES
        if extra <= 0:
            return

        def value(item):
            d = item[1]
            kept = bool(d.get("known") or d.get("name") or d.get("notes") or d.get("type_user"))
            return bool(d.get("self")), kept, bool(d.get("online")), d.get("last_seen", 0), -d.get("first_seen", 0)

        for did, _ in sorted(self.devices.items(), key=value)[:extra]:
            del self.devices[did]
        log.warning("device list is full: removed %d records (limit %d)", extra, MAX_DEVICES)

    def _in_scope(self, dev, result):
        """Only mark a device offline if its last IP was part of this scan's targets. A device
        known only by IPv6 is in scope when IPv6 discovery ran on its interface."""
        if not dev.get("ip"):
            v6 = result.get("_v6_ifaces")
            return v6 is None or dev.get("iface") in v6
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
                d["address"] = primary_address(dev)
                d["detected_name"] = display_name(dict(dev, name=""))
                out.append(d)
            return out

    def update_device(self, did, fields):
        with self.lock:
            dev = self.devices.get(did)
            if dev is None:
                raise KeyError(did)
            if "name" in fields:
                dev["name"] = clean_text(fields["name"], 64)
            if "notes" in fields:
                dev["notes"] = clean_text(fields["notes"], 1000, multiline=True)
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
        w.writerow(["Name", "Status", "Type", "IP", "IPv6", "MAC", "Vendor", "Hostname", "Model",
                    "Open ports", "Known", "First seen", "Last seen", "Notes"])
        import time as _t
        fmt = lambda ts: _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(ts)) if ts else ""  # noqa: E731
        def order(x):
            ip = x.get("ip") or ""
            return (0, tuple(int(p) for p in ip.split("."))) if ip else (1, (primary_address(x),))
        for d in sorted(self.list_devices(), key=order):
            row = [d["display_name"], "online" if d.get("online") else "offline", d["type"],
                   d.get("ip", ""), " ".join(d.get("ipv6") or []), d.get("mac", ""), d.get("vendor", ""),
                   d.get("hostname") or d.get("mdns_name") or d.get("netbios") or "",
                   d.get("model", ""), " ".join(str(p) for p in d.get("ports", [])),
                   "yes" if d.get("known") else "no", fmt(d.get("first_seen")),
                   fmt(d.get("last_seen")), d.get("notes", "")]
            w.writerow([csv_cell(c) for c in row])
        return buf.getvalue()
