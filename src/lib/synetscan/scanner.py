"""The scan engine: discovery, enrichment and classification."""
import concurrent.futures as cf
import ipaddress
import threading
import time

from . import netinfo, oui, probes
from .classify import DEFAULT_PORTS, bogus_model, classify, join_model, junk_name, generic_upnp_name
from .targets import build_targets
from .util import is_random_mac, log, normalize_mac, now

DISCOVERY_PORTS = [80, 443, 22, 445, 62078, 8080, 1400, 8001, 8009]
ARP_SETTLE = 8.0  # seconds until a stale ARP entry of a vanished host is purged


class ScanCancelled(Exception):
    pass


class Scanner:
    def __init__(self, cfg, progress=None, cancel=None):
        self.cfg = cfg
        self.progress_cb = progress or (lambda **kw: None)
        self.cancel = cancel or threading.Event()

    # ------------------------------------------------------------------ helpers
    def _check(self):
        if self.cancel.is_set():
            raise ScanCancelled()

    def _progress(self, phase, done, total, found=0):
        self.progress_cb(phase=phase, done=done, total=total, found=found)

    def _map(self, fn, items, workers, phase, found_fn=lambda: 0):
        results = {}
        total = len(items)
        if not total:
            return results
        with cf.ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as ex:
            futures = {ex.submit(fn, it): it for it in items}
            done = 0
            try:
                for fut in cf.as_completed(futures):
                    self._check()
                    done += 1
                    try:
                        results[futures[fut]] = fut.result()
                    except Exception as e:  # noqa: BLE001
                        log.debug("probe failed for %s: %s", futures[fut], e)
                        results[futures[fut]] = None
                    if done % 4 == 0 or done == total:
                        self._progress(phase, done, total, found_fn())
            except ScanCancelled:
                for f in futures:
                    f.cancel()
                raise
        return results

    # --------------------------------------------------------------------- run
    def run(self):
        cfg = self.cfg
        started = now()
        t0 = time.monotonic()
        ifaces = netinfo.interfaces()
        gateways = netinfo.default_gateways()
        own = {i["ip"]: i for i in ifaces if not i["ip"].startswith("127.")}
        targets, descriptions = build_targets(cfg, ifaces)
        target_set = {ip for ip, _ in targets}
        source = dict(targets)
        timeout = float(cfg.get("timeout", 0.6))
        workers = int(cfg.get("threads", 64))
        use_ping = bool(cfg.get("use_ping", True)) and probes.ping_available()
        local_ifaces = [i for i in ifaces if not i["virtual"] and i["up"]]
        mcast_ips = [i["ip"] for i in local_ifaces] or None
        log.info("scan started: %d targets (%s), ping=%s", len(targets), ", ".join(descriptions), use_ping)

        # multicast discovery runs in the background during the sweep
        mcast = {}

        def run_mcast():
            if cfg.get("use_mdns", True):
                try:
                    mcast["mdns"] = probes.mdns_browse(mcast_ips)
                except Exception as e:  # noqa: BLE001
                    log.warning("mDNS browse failed: %s", e)
            if cfg.get("use_ssdp", True):
                try:
                    mcast["ssdp"] = probes.ssdp_discover(mcast_ips)
                except Exception as e:  # noqa: BLE001
                    log.warning("SSDP discovery failed: %s", e)

        mthread = threading.Thread(target=run_mcast, name="mcast", daemon=True)
        mthread.start()

        # ---- phase 1: discovery sweep
        alive = {}
        lock = threading.Lock()

        def discover(ip):
            if ip in own:
                return
            probes.udp_poke(ip)
            res = probes.tcp_probe(ip, DISCOVERY_PORTS, timeout)
            hit = [p for p, st in res.items() if st in ("open", "closed")]
            rtt = None
            if not hit and use_ping:
                rtt = probes.ping(ip, 1)
            if hit or rtt is not None:
                with lock:
                    alive[ip] = {"via": ["tcp"] if hit else ["icmp"], "rtt": rtt,
                                 "open": [p for p, st in res.items() if st == "open"]}

        self._map(discover, [ip for ip, _ in targets], workers, "discover", lambda: len(alive))
        poked_at = time.monotonic()
        self._check()
        mthread.join(timeout=8)
        mdns = mcast.get("mdns", {})
        ssdp = mcast.get("ssdp", {})

        arp = netinfo.arp_table()
        for ip, (mac, dev) in arp.items():
            if ip in target_set and ip not in alive:
                alive[ip] = {"via": ["arp"], "rtt": None, "open": []}
            elif ip in alive:
                alive[ip]["via"].append("arp")
        for ip in list(mdns) + list(ssdp):
            if ip in target_set and ip not in own:
                entry = alive.setdefault(ip, {"via": [], "rtt": None, "open": []})
                entry["via"].append("mdns" if ip in mdns else "ssdp")
        for ip in own:
            if ip in target_set:
                alive[ip] = {"via": ["self"], "rtt": 0.0, "open": []}

        # Devices in Wi-Fi power saving (speakers, TVs in standby) often miss the first ARP
        # requests. Poke the silent addresses once more; their ARP entries are read after the
        # enrichment, which takes long enough for slow sleepers to answer.
        missing = [ip for ip, _ in targets if ip not in alive and ip not in own]
        for ip in missing:
            probes.udp_poke(ip)
        second_poke = time.monotonic()

        # ---- phase 2: enrichment
        ports = sorted({int(p) for p in cfg.get("ports", DEFAULT_PORTS) if 0 < int(p) < 65536})
        hosts = {}

        def enrich(ip):
            info = alive[ip]
            dev = {"ip": ip, "via": sorted(set(info["via"])), "rtt": info["rtt"],
                   "iface": source.get(ip, "")}
            if ip in own:
                dev["mac"] = own[ip]["mac"]
                dev["self"] = True
                dev["iface"] = own[ip]["name"]
            elif ip in arp:
                dev["mac"] = arp[ip][0]
                dev["iface"] = arp[ip][1]
            open_ports = set(info["open"])
            for i in range(0, len(ports), 32):
                self._check()
                chunk = [p for p in ports[i:i + 32] if p not in open_ports]
                res = probes.tcp_probe(ip, chunk, timeout + 0.3)
                open_ports.update(p for p, st in res.items() if st == "open")
            dev["ports"] = sorted(open_ports)
            if cfg.get("use_dns", True):
                dev["hostname"] = probes.reverse_dns(ip)
            if cfg.get("use_netbios", True) and (ip not in own):
                nb = probes.netbios_status(ip, 0.8)
                if nb:
                    dev["netbios"] = nb["name"]
                    dev["workgroup"] = nb["workgroup"]
                    if not dev.get("mac") and normalize_mac(nb["mac"]):
                        dev["mac"] = normalize_mac(nb["mac"])
            md = mdns.get(ip)
            if md:
                dev["mdns_name"] = md["hostname"]
                dev["services"] = md["services"]
                dev["instances"] = md["instances"][:10]
                txt = md["txt"]
                dev["model"] = txt.get("md") or txt.get("model") or txt.get("ty") or txt.get("usb_mdl") or txt.get("am") or ""
                names = [n for n in [txt.get("fn")] + md["instances"] if n and not junk_name(n)]
                if names:
                    dev["friendly"] = names[0]
            elif cfg.get("use_mdns", True) and ip not in own:
                name = probes.mdns_reverse(ip, 0.6)
                if name:
                    dev["mdns_name"] = name
            sd = ssdp.get(ip)
            if sd:
                dev["ssdp_server"] = sd["server"]
                if sd["location"]:
                    desc = probes.upnp_description(sd["location"])
                    if desc:
                        dev["upnp"] = desc
                        model = join_model(desc.get("manufacturer"), desc.get("modelName"))
                        if model and not dev.get("model"):
                            dev["model"] = model
                        fn = desc.get("friendlyName", "")
                        if fn and not junk_name(fn) and not generic_upnp_name(fn):
                            dev["friendly"] = fn
                        elif model and not dev.get("friendly"):
                            dev["friendly"] = model
            if cfg.get("use_http", True):
                for p in (80, 8080, 443, 5000):
                    if p in open_ports:
                        info_http = probes.http_info(ip, p)
                        if info_http and (info_http["title"] or info_http["server"]):
                            dev["http"] = info_http
                            break
            mac = dev.get("mac", "")
            dev["vendor"] = oui.lookup(mac) if mac else ""
            if bogus_model(dev.get("model"), dev["vendor"]):
                dev["model"] = ""
            dev["random_mac"] = is_random_mac(mac)
            hosts[ip] = dev
            return dev

        order = sorted(alive, key=lambda a: int(ipaddress.IPv4Address(a)))
        self._map(enrich, order, max(8, workers // 2), "identify", lambda: len(hosts))

        late = [ip for ip in netinfo.arp_table() if ip in target_set and ip not in alive and ip not in own]
        if late:
            if time.monotonic() - second_poke < 3:
                time.sleep(3 - (time.monotonic() - second_poke))
            for ip in late:
                alive[ip] = {"via": ["arp"], "rtt": None, "open": []}
            log.info("second ARP round found %d more host(s)", len(late))
            self._map(enrich, sorted(late, key=lambda a: int(ipaddress.IPv4Address(a))),
                      max(8, workers // 2), "identify", lambda: len(hosts))

        # ---- verification of ARP-only hosts (purge stale cache entries)
        arp_only = [ip for ip, d in hosts.items() if d["via"] == ["arp"] and not d["ports"]]
        if arp_only:
            self._progress("verify", 0, 1, len(hosts))
            wait = ARP_SETTLE - (time.monotonic() - poked_at)
            end = time.monotonic() + max(0.0, wait)
            while time.monotonic() < end:
                self._check()
                time.sleep(0.25)
            fresh = netinfo.arp_table()
            for ip in arp_only:
                if ip not in fresh:
                    log.info("dropping stale ARP entry %s", ip)
                    hosts.pop(ip, None)

        gw_ips = set(gateways.values())
        for dev in hosts.values():
            dev["type"] = classify(dev, gateways=gw_ips, own_ips=set(own))
            if dev["ip"] in gw_ips:
                dev["gateway"] = True

        finished = now()
        result = {
            "started": started,
            "finished": finished,
            "duration": round(time.monotonic() - t0, 1),
            "targets": descriptions,
            "target_count": len(targets),
            "ping": use_ping,
            "_target_ips": target_set,
            "hosts": [hosts[ip] for ip in sorted(hosts, key=lambda a: int(ipaddress.IPv4Address(a)))],
        }
        log.info("scan finished: %d hosts in %.1fs", len(hosts), result["duration"])
        return result
