"""The scan engine: discovery, enrichment and classification."""
import concurrent.futures as cf
import ipaddress
import re
import threading
import time

from . import ipv6, netinfo, oui, probes
from .classify import DEFAULT_PORTS, bogus_model, classify, join_model, junk_name, generic_upnp_name
from .targets import build_targets
from .util import error_text, is_random_mac, log, normalize_mac, now

DISCOVERY_PORTS = [80, 443, 22, 445, 62078, 8080, 1400, 8001, 8009]
ARP_SETTLE = 8.0  # seconds until a stale ARP entry of a vanished host is purged


_NUMBER_LIST = re.compile(r"^[\d,.\s]+$")
_RAOP_PREFIX = re.compile(r"^[0-9A-Fa-f]{12}@")


def split_proxy_arp(arp, target_set, own, gateway_ips):
    """{ip: mac} for addresses whose ARP answer came from a MAC that answers for several IPs.

    The MAC stays with one address: the gateway if it is among them, else the lowest."""
    mac_ips = {}
    for a, (m, _d) in arp.items():
        if a in target_set and a not in own:
            mac_ips.setdefault(m, []).append(a)
    out = {}
    for m, ips in mac_ips.items():
        if len(ips) > 1:
            keep = next((a for a in ips if a in gateway_ips), min(ips, key=lambda a: int(ipaddress.IPv4Address(a))))
            out.update({a: m for a in ips if a != keep})
            log.info("proxy ARP: %s answers for %s; kept on %s", m, ", ".join(sorted(ips)), keep)
    return out


def _host_order(key):
    """IPv4 devices by address, then IPv6-only devices ("v6:<mac>")."""
    if key.startswith("v6:"):
        return (1, 0, key)
    return (0, int(ipaddress.IPv4Address(key)), "")


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
        browse_ready = threading.Event()

        def run_mcast():
            if cfg.get("use_mdns", True):
                try:
                    mcast["mdns"] = probes.mdns_browse(mcast_ips, ready=browse_ready)
                except Exception as e:  # noqa: BLE001
                    log.warning("mDNS browse failed: %s", e)
            browse_ready.set()
            if cfg.get("use_ssdp", True):
                try:
                    mcast["ssdp"] = probes.ssdp_discover(mcast_ips)
                except Exception as e:  # noqa: BLE001
                    log.warning("SSDP discovery failed: %s", e)

        mthread = threading.Thread(target=run_mcast, name="mcast", daemon=True)
        mthread.start()
        # The browse gets a head start: a device that is being probed may answer it late,
        # without its host name or not at all (seen with a Hue bridge).
        browse_ready.wait(2.0)

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

        # ---- IPv6 (in the background, while IPv4 devices are identified)
        v6 = {}
        v6_thread = None
        if cfg.get("use_ipv6", True):
            def run_v6():
                try:
                    names = ipv6.candidate_interfaces(cfg.get("excluded_interfaces") or ())
                    known = [(m, d) for m, d in arp.values() if not netinfo.is_virtual(d)]
                    v6.update(ipv6.discover(names, known,
                                            use_mdns=cfg.get("use_mdns", True), use_ssdp=cfg.get("use_ssdp", True)))
                except Exception as e:  # noqa: BLE001
                    log.warning("IPv6 discovery failed: %s", e)
                    v6.clear()
                    v6["error"] = error_text(e)
            v6_thread = threading.Thread(target=run_v6, name="ipv6", daemon=True)
            v6_thread.start()

        # A router doing proxy ARP (e.g. for VPN clients) answers with its own MAC for other
        # hosts' addresses. Such a MAC belongs to one device only: the gateway address if it is
        # one of them, else the lowest. The other addresses become devices of their own, known
        # by IP (NetBIOS may still tell their real MAC).
        proxy_arp = split_proxy_arp(arp, target_set, own, set(gateways.values()))

        # ---- phase 2: enrichment
        ports = sorted({int(p) for p in cfg.get("ports", DEFAULT_PORTS) if 0 < int(p) < 65536})
        hosts = {}
        asked_directly = []

        def apply_mdns(dev, md):
            if md.get("hostname"):
                dev["mdns_name"] = md["hostname"]
            dev["services"] = sorted(set(dev.get("services") or []) | set(md["services"]))
            dev["instances"] = md["instances"][:10]
            txt = md["txt"]
            model = next((v for v in (txt.get("md"), txt.get("model"), txt.get("ty"), txt.get("usb_mdl"), txt.get("am"))
                          if v and not _NUMBER_LIST.match(v)), "")  # RAOP "md=0,1,2" lists metadata types
            if model:
                dev["model"] = model
            # AirPlay/RAOP instances are "<MAC>@<name>"
            names = [_RAOP_PREFIX.sub("", n) for n in [txt.get("fn")] + md["instances"] if n]
            names = [n for n in names if n and not junk_name(n)]
            if names:
                dev["friendly"] = names[0]

        def apply_ssdp(dev, sd, addr):
            # `addr` is where the announcement came from; the description is only ever
            # fetched from there, whatever host the announced LOCATION names
            dev["ssdp_server"] = sd["server"]
            desc = probes.upnp_first_description(sd["locations"], addr)
            if not desc:
                return
            dev["upnp"] = desc
            model = join_model(desc.get("manufacturer"), desc.get("modelName"))
            if model and not dev.get("model"):
                dev["model"] = model
            fn = desc.get("friendlyName", "")
            if fn and not junk_name(fn) and not generic_upnp_name(fn):
                dev["friendly"] = fn
            elif model and not dev.get("friendly"):
                dev["friendly"] = model

        def apply_http(dev, addr, open_ports):
            if not cfg.get("use_http", True):
                return
            budget = time.monotonic() + 8  # per device, however slowly its web servers answer
            for p in (80, 8080, 443, 5000):
                left = budget - time.monotonic()
                if p in open_ports and left > 0.5:
                    info_http = probes.http_info(addr, p, min(4.0, left))
                    if info_http and (info_http["title"] or info_http["server"]):
                        dev["http"] = info_http
                        return

        def port_scan(addr, already=()):
            open_ports = set(already)
            for i in range(0, len(ports), 32):
                self._check()
                chunk = [p for p in ports[i:i + 32] if p not in open_ports]
                res = probes.tcp_probe(addr, chunk, timeout + 0.3)
                open_ports.update(p for p, st in res.items() if st == "open")
            return open_ports

        def finish(dev):
            mac = dev.get("mac", "")
            dev["vendor"] = oui.lookup(mac) if mac else ""
            if bogus_model(dev.get("model"), dev["vendor"]):
                dev["model"] = ""
            dev["random_mac"] = is_random_mac(mac)

        def enrich(ip):
            info = alive[ip]
            dev = {"ip": ip, "via": sorted(set(info["via"])), "rtt": info["rtt"],
                   "iface": source.get(ip, "")}
            if ip in own:
                dev["mac"] = own[ip]["mac"]
                dev["self"] = True
                dev["iface"] = own[ip]["name"]
            elif ip in proxy_arp:
                dev["proxy_arp"] = proxy_arp[ip]
                dev["iface"] = arp[ip][1]
            elif ip in arp:
                dev["mac"] = arp[ip][0]
                dev["iface"] = arp[ip][1]
                shared = sorted(a for a, m in proxy_arp.items() if m == dev["mac"])
                if shared:
                    dev["proxy_arp_for"] = shared
            md = mdns.get(ip)
            if md and ip not in own and (not md.get("hostname") or not md.get("ipv6") and cfg.get("use_ipv6", True)):
                # its answers to the browse came without its host name or addresses: ask the
                # device itself, before the port scan disturbs it
                had_name = bool(md.get("hostname"))
                name, addrs = probes.mdns_host(ip, md["services"], name=md.get("hostname") or "")
                md["hostname"] = md.get("hostname") or name
                md["ipv6"] = addrs or md.get("ipv6") or []
                asked_directly.append((had_name, bool(name), bool(addrs)))
            open_ports = port_scan(ip, info["open"])
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
            if md:
                apply_mdns(dev, md)
            elif cfg.get("use_mdns", True) and ip not in own:
                name = probes.mdns_reverse(ip, 0.6)
                if name:
                    dev["mdns_name"] = name
            sd = ssdp.get(ip)
            if sd:
                apply_ssdp(dev, sd, ip)
            apply_http(dev, ip, open_ports)
            finish(dev)
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

        nameless = [a for a in asked_directly if not a[0]]
        if nameless:
            log.info("mDNS: %d device(s) answered the browse without a host name; asked directly, %d gave it "
                     "and %d their IPv6 addresses", len(nameless), sum(1 for a in nameless if a[1]),
                     sum(1 for a in nameless if a[2]))
        if len(nameless) < len(asked_directly):
            log.info("mDNS: %d device(s) answered the browse without IPv6 addresses; %d gave them when asked directly",
                     len(asked_directly) - len(nameless), sum(1 for a in asked_directly if a[0] and a[2]))
        self._merge_self(hosts, gateways)
        v6_status = {"enabled": bool(cfg.get("use_ipv6", True))}
        if v6_thread is not None:
            v6_thread.join(timeout=20)
            if "error" in v6 or not v6:
                v6_status["error"] = v6.get("error") or "timeout"
            else:
                try:
                    self._merge_ipv6(v6, hosts, ifaces, mdns, ports, port_scan, apply_mdns, apply_ssdp, apply_http, finish, workers)
                except ScanCancelled:
                    raise
                except Exception as e:  # noqa: BLE001 - IPv6 must never cost the IPv4 results
                    log.exception("IPv6 merge failed")
                    v6_status["error"] = error_text(e)
            v6_status.update(ifaces=list(v6.get("ifaces") or []), routable=bool(v6.get("routable")),
                             with_ipv6=sum(1 for d in hosts.values() if d.get("ipv6")),
                             only=sum(1 for d in hosts.values() if d.get("ipv6") and not d.get("ip")))

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
            "_v6_ifaces": set(v6.get("ifaces") or []) if "error" not in v6 else None,
            "ipv6": v6_status,
            "hosts": [hosts[k] for k in sorted(hosts, key=_host_order)],
        }
        log.info("scan finished: %d hosts in %.1fs", len(hosts), result["duration"])
        return result

    def _merge_self(self, hosts, gateways):
        """A NAS with several connected ports is one device: keep the port with the default
        gateway (else the first) and list the other addresses on it."""
        selfs = [k for k, d in hosts.items() if d.get("self")]
        if len(selfs) < 2:
            return
        gw_ifaces = set(gateways)
        selfs.sort(key=lambda k: (hosts[k].get("iface") not in gw_ifaces, _host_order(k)))
        main = hosts[selfs[0]]
        main["other_ips"] = []
        for k in selfs[1:]:
            d = hosts.pop(k)
            main["other_ips"].append("%s (%s)" % (d["ip"], d.get("iface", "")))
            main["ports"] = sorted(set(main.get("ports") or []) | set(d.get("ports") or []))

    def _merge_ipv6(self, v6, hosts, ifaces, mdns, ports, port_scan, apply_mdns, apply_ssdp, apply_http, finish, workers):
        """Attach IPv6 addresses to the devices found over IPv4 and identify IPv6-only ones."""
        own_v6, deprecated = {}, set()
        for a in ipv6.own_addresses():
            own_v6.setdefault(a["dev"], []).append(a["ip"])
            if a.get("deprecated"):
                deprecated.add(a["ip"])
        prefixes = v6.get("prefixes") or {}
        own_macs = {i["mac"] for i in ifaces if i.get("mac")}
        by_mac = {d["mac"]: d for d in hosts.values() if d.get("mac")}
        # host names announced over mDNS (on IPv4 and IPv6) with their AAAA records
        aaaa = {}
        for md in list(mdns.values()) + list(v6.get("mdns", {}).values()):
            if md.get("hostname") and md.get("ipv6"):
                aaaa.setdefault(md["hostname"].lower(), set()).update(md["ipv6"])
        for d in hosts.values():
            extra = set()
            if d.get("self"):
                for dev_name in [d.get("iface")] + [o.rsplit("(", 1)[-1].rstrip(")") for o in d.get("other_ips") or []]:
                    extra.update(own_v6.get(dev_name, []))
            if d.get("mdns_name"):
                found = [a for a in aaaa.get(d["mdns_name"].lower(), ()) if ipv6.is_ipv6(a)]
                extra.update(ipv6.on_link_filter(found, prefixes.get(d.get("iface"), ())))
            if extra:
                d["ipv6"] = ipv6.sort_addresses(set(d.get("ipv6") or []) | extra, deprecated)
            if d.get("self") and deprecated & set(d.get("ipv6") or []):
                d["ipv6_deprecated"] = sorted(deprecated & set(d["ipv6"]))
        only = []
        for mac, n in v6.get("neighbors", {}).items():
            if mac in own_macs:
                continue
            d = by_mac.get(mac)
            if d is not None:
                d["ipv6"] = ipv6.sort_addresses(set(d.get("ipv6") or []) | set(n["addrs"]))
                if "ndp" not in d["via"]:
                    d["via"] = sorted(d["via"] + ["ndp"])
            else:
                only.append((mac, n))
        mdns6, ssdp6, wsd6 = v6.get("mdns", {}), v6.get("ssdp", {}), v6.get("wsd", {})

        neigh = dict(only)

        def enrich6(mac):
            n = neigh[mac]
            addrs = n["addrs"]
            best = addrs[0]
            target = best if ipv6.kind(best) != "link" else "%s%%%s" % (best, n["dev"])
            dev = {"ip": "", "ipv6": addrs, "mac": mac, "via": ["ndp"], "rtt": None, "iface": n["dev"]}
            if n["router"]:
                dev["ipv6_router"] = True
            dev["ports"] = sorted(port_scan(target))
            if self.cfg.get("use_dns", True):
                for a in addrs:
                    if ipv6.kind(a) != "link":
                        name = probes.reverse_dns(a)
                        if name:
                            dev["hostname"] = name
                            break
            for a in addrs:
                if a in mdns6:
                    apply_mdns(dev, mdns6[a])
                    dev["via"] = sorted(set(dev["via"]) | {"mdns"})
                    break
            for a in addrs:
                if a in wsd6:
                    dev["via"] = sorted(set(dev["via"]) | {"wsd"})
                    types = wsd6[a]["types"].lower()
                    if "print" in types:
                        dev["services"] = sorted(set(dev.get("services") or []) | {"_wsd._printer"})
                    elif "computer" in types:
                        dev["services"] = sorted(set(dev.get("services") or []) | {"_wsd._workstation"})
                    break
            for a in addrs:
                if a in ssdp6:
                    apply_ssdp(dev, ssdp6[a], a if ipv6.kind(a) != "link" else "%s%%%s" % (a, n["dev"]))
                    dev["via"] = sorted(set(dev["via"]) | {"ssdp"})
                    break
            web = next((a for a in addrs if ipv6.kind(a) != "link"), "")
            if web:
                apply_http(dev, web, set(dev["ports"]))
            finish(dev)
            hosts["v6:" + mac] = dev

        if only:
            self._map(enrich6, sorted(neigh), max(8, workers // 2), "identify", lambda: len(hosts))
            log.info("IPv6: %d device(s) without IPv4", len(only))
