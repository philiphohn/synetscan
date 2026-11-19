"""IPv6 discovery without root.

An IPv6 LAN (/64) cannot be swept address by address, and ICMPv6 needs raw sockets. Instead:

1. Make the devices talk: an all-nodes echo (ff02::1) where unprivileged ICMP sockets or the
   system ping allow it, mDNS, SSDP and WS-Discovery queries to their IPv6 multicast groups
   (sent from each routable address too, so answers reveal routable addresses), and a datagram
   to the EUI-64 link-local address of every MAC already known from IPv4. Every answer, and
   every neighbour solicitation a device sends to reach us, puts the device into the kernel's
   neighbour table.
2. Read that table (`ip -6 neigh`, readable by any user): IPv6 address -> MAC, per interface.
3. Group addresses by MAC. Phones and PCs keep several (privacy) addresses at once; grouped by
   MAC they stay one device.
"""
import ipaddress
import os
import re
import socket
import struct
import subprocess
import threading
import time

from . import probes
from .netinfo import is_virtual
from .util import is_random_mac, log, normalize_mac

_BAD_STATES = {"FAILED", "INCOMPLETE", "NOARP", "NONE"}
_NEIGH = re.compile(r"^(?P<ip>[0-9a-fA-F:]+)\s+dev\s+(?P<dev>\S+)(?:\s+lladdr\s+(?P<mac>[0-9a-fA-F:]{17}))?"
                    r"(?P<flags>.*?)\s+(?P<state>[A-Z]+)\s*$")


def own_addresses():
    """[{ip, prefix, dev, scope}] for this host's IPv6 addresses (/proc/net/if_inet6)."""
    out = []
    try:
        with open("/proc/net/if_inet6") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                addr = ipaddress.IPv6Address(int(parts[0], 16))
                if addr.is_loopback:
                    continue
                out.append({"ip": str(addr), "prefix": int(parts[2], 16), "dev": parts[5], "scope": kind(str(addr)),
                            "deprecated": bool(int(parts[4], 16) & 0x20)})
    except (OSError, ValueError):
        pass
    return out


def candidate_interfaces(excluded=()):
    """Physical interfaces that are up and have an IPv6 link-local address (IPv4 or not)."""
    out = []
    for a in own_addresses():
        n = a["dev"]
        if a["scope"] != "link" or n in out or n in excluded or is_virtual(n):
            continue
        try:
            with open("/sys/class/net/%s/operstate" % n) as f:
                if f.read().strip() not in ("up", "unknown"):
                    continue
        except OSError:
            pass
        out.append(n)
    return out


def is_ipv6(addr):
    try:
        ipaddress.IPv6Address(str(addr).split("%")[0])
        return True
    except ValueError:
        return False


def kind(addr):
    """'global', 'ula' (fc00::/7, local only) or 'link' (fe80::/10)."""
    a = ipaddress.IPv6Address(addr.split("%")[0])
    if a.is_link_local:
        return "link"
    if a in ipaddress.IPv6Network("fc00::/7"):
        return "ula"
    return "global"


def sort_addresses(addrs, deprecated=()):
    """Global first, then unique-local, then link-local; deprecated addresses after the current
    ones of their kind. Anything that isn't an IPv6 address is dropped."""
    order = {"global": 0, "ula": 1, "link": 2}
    good = [a for a in set(addrs) if is_ipv6(a)]
    return sorted(good, key=lambda a: (order[kind(a)], a in deprecated, ipaddress.IPv6Address(a)))


def on_link_filter(addrs, prefixes):
    """Keep link-local addresses and routable ones inside the interface's current prefixes.

    The kernel keeps neighbour entries from earlier provider prefixes for a long time (one Mac
    had 24 addresses, 22 of them on old prefixes). Without routable prefixes of our own we
    can't tell, so everything is kept."""
    nets = [ipaddress.IPv6Network(p, strict=False) for p in prefixes]
    if not nets:
        return list(addrs)
    out = []
    for a in addrs:
        ip = ipaddress.IPv6Address(a)
        if ip.is_link_local or any(ip in n for n in nets):
            out.append(a)
    return out


def eui64_link_local(mac):
    """fe80:: address derived from a MAC (modified EUI-64), as many embedded devices use."""
    b = bytearray(bytes.fromhex(mac.replace(":", "")))
    b[0] ^= 0x02
    iid = bytes(b[:3]) + b"\xff\xfe" + bytes(b[3:])
    return str(ipaddress.IPv6Address(b"\xfe\x80" + b"\x00" * 6 + iid))


def parse_neighbors(text):
    """Parse `ip -6 neigh show` -> [{ip, dev, mac, router}] for usable entries."""
    out = []
    for line in text.splitlines():
        m = _NEIGH.match(line.strip())
        if not m or not m.group("mac") or m.group("state") in _BAD_STATES:
            continue
        ip = m.group("ip")
        try:
            a = ipaddress.IPv6Address(ip)
        except ValueError:
            continue
        if a.is_multicast or a.is_loopback or a.is_unspecified:
            continue
        out.append({"ip": str(a), "dev": m.group("dev"), "mac": normalize_mac(m.group("mac")),
                    "router": " router" in (m.group("flags") or "")})
    return out


_NUD_BAD = 0x01 | 0x20 | 0x40  # INCOMPLETE, FAILED, NOARP
_NTF_ROUTER = 0x80


def parse_netlink_neighbors(data):
    """Parse RTM_NEWNEIGH messages (AF_INET6) -> [{ip, ifindex, mac, router}], and whether
    the dump is complete."""
    out, off, done = [], 0, False
    while off + 16 <= len(data):
        length, mtype, _flags, _seq, _pid = struct.unpack_from("=IHHII", data, off)
        if length < 16:
            break
        if mtype == 3:  # NLMSG_DONE
            done = True
        elif mtype == 28 and length >= 28:  # RTM_NEWNEIGH
            family, ifindex, state, nflags, _ntype = struct.unpack_from("=BxxxiHBB", data, off + 16)
            attrs, ip, mac = off + 28, None, None
            while attrs + 4 <= off + length:
                alen, atype = struct.unpack_from("=HH", data, attrs)
                if alen < 4:
                    break
                val = data[attrs + 4:attrs + alen]
                if atype == 1 and len(val) == 16:
                    ip = socket.inet_ntop(socket.AF_INET6, val)
                elif atype == 2 and len(val) == 6:
                    mac = ":".join("%02x" % b for b in val)
                attrs += (alen + 3) & ~3
            if family == socket.AF_INET6 and ip and mac and not state & _NUD_BAD:
                out.append({"ip": ip, "ifindex": ifindex, "mac": mac, "router": bool(nflags & _NTF_ROUTER)})
        off += (length + 3) & ~3
    return out, done


def _neighbors_netlink():
    s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)  # NETLINK_ROUTE
    try:
        s.settimeout(2)
        s.bind((0, 0))
        req = struct.pack("=IHHII", 28, 30, 0x301, 1, 0) + struct.pack("=BxxxiHBB", socket.AF_INET6, 0, 0, 0, 0)
        s.send(req)
        out = []
        while True:
            entries, done = parse_netlink_neighbors(s.recv(65536))
            out.extend(entries)
            if done:
                break
    finally:
        s.close()
    names = {}
    result = []
    for e in out:
        if e["ifindex"] not in names:
            try:
                names[e["ifindex"]] = socket.if_indextoname(e["ifindex"])
            except OSError:
                names[e["ifindex"]] = ""
        a = ipaddress.IPv6Address(e["ip"])
        if names[e["ifindex"]] and not (a.is_multicast or a.is_loopback or a.is_unspecified):
            result.append({"ip": e["ip"], "dev": names[e["ifindex"]], "mac": e["mac"], "router": e["router"]})
    return result


def neighbors():
    """The kernel's IPv6 neighbour table. Netlink needs no privileges; `ip` is the fallback."""
    try:
        return _neighbors_netlink()
    except (OSError, AttributeError, struct.error, ValueError) as e:
        log.debug("netlink neighbour dump failed (%s), trying ip -6 neigh", e)
    for cmd in (["ip", "-6", "neigh", "show"], ["/sbin/ip", "-6", "neigh", "show"], ["/usr/sbin/ip", "-6", "neigh", "show"]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            return parse_neighbors(r.stdout.decode("utf-8", "replace"))
    return []


def _ifindex(name):
    try:
        return socket.if_nametoindex(name)
    except OSError:
        return 0


def _echo_all_nodes(dev, idx, sources=()):
    """ICMPv6 echo to ff02::1 via an unprivileged ping socket; else the system ping, if it
    works for this user. Either may be unavailable – the other methods still apply.

    Devices answer from an address of the same scope as the sender's: sent from each of our
    global/unique-local addresses too, the replies reveal the devices' routable addresses."""
    sent = False
    for src in [None] + list(sources):
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_ICMPV6)
        except (OSError, AttributeError):
            break
        try:
            if src:
                s.bind((src, 0, 0, 0))
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, idx)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
            pkt = struct.pack("!BBHHH", 128, 0, 0, os.getpid() & 0xFFFF, 1) + b"synetscan"
            for _ in range(2):
                s.sendto(pkt, ("ff02::1", 0, 0, idx))
            s.settimeout(0.3)
            end = time.monotonic() + 1.0
            while time.monotonic() < end:
                try:
                    s.recvfrom(1024)
                except (socket.timeout, OSError):
                    break
            sent = True
        except OSError:
            pass
        finally:
            s.close()
    if sent:
        return "socket"
    if probes.ping_available():
        for cmd in (["ping", "-6", "-c", "2", "-w", "2", "-I", dev, "ff02::1"], ["ping6", "-c", "2", "-w", "2", "-I", dev, "ff02::1"]):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=4)
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode in (0, 1):
                return "ping"
    return ""


def discover(ifnames, known_macs=(), use_mdns=True, use_ssdp=True, settle=2.0):
    """Run IPv6 discovery on the given interfaces.

    `known_macs`: (mac, interface) pairs from the IPv4 ARP table; each MAC's EUI-64 link-local
    address is tried on its own interface only.

    Returns {"neighbors": {mac: {"addrs": [...], "dev": str, "router": bool}},
             "mdns": {addr: entry}, "ssdp": {addr: entry}, "wsd": {addr: entry}, "echo": method}.
    """
    own = own_addresses()
    ifnames = [n for n in ifnames if not is_virtual(n) and any(a["dev"] == n and a["scope"] == "link" for a in own)]
    result = {"neighbors": {}, "mdns": {}, "ssdp": {}, "wsd": {}, "echo": "", "ifaces": ifnames,
              "routable": False}
    if not ifnames:
        log.info("IPv6: no interface with IPv6 (link-local) address, skipped")
        return result
    idx = {n: _ifindex(n) for n in ifnames}
    idx = {n: i for n, i in idx.items() if i}
    routable = {n: [a["ip"] for a in own if a["dev"] == n and a["scope"] != "link"] for n in idx}
    found = {}

    def run_mdns():
        try:
            found["mdns"] = probes.mdns_browse(None, ifindexes=list(idx.values()),
                                               sources={i: (routable[n] or [None])[0] for n, i in idx.items()})
        except Exception as e:  # noqa: BLE001
            log.warning("IPv6 mDNS failed: %s", e)

    def run_ssdp():
        try:
            found["ssdp"] = probes.ssdp_discover(None, ifindexes=list(idx.values()))
        except Exception as e:  # noqa: BLE001
            log.warning("IPv6 SSDP failed: %s", e)

    def run_wsd():
        try:
            found["wsd"] = probes.wsd_discover(None, ifindexes=list(idx.values()),
                                               sources={i: (routable[n] or [None])[0] for n, i in idx.items()})
        except Exception as e:  # noqa: BLE001
            log.warning("IPv6 WS-Discovery failed: %s", e)

    threads = [threading.Thread(target=run_wsd, daemon=True)]
    if use_mdns:
        threads.append(threading.Thread(target=run_mdns, daemon=True))
    if use_ssdp:
        threads.append(threading.Thread(target=run_ssdp, daemon=True))
    for t in threads:
        t.start()
    methods = {_echo_all_nodes(n, i, routable[n]) for n, i in idx.items()}
    result["echo"] = ",".join(sorted(m for m in methods if m))
    for item in known_macs:
        mac, dev = item if isinstance(item, (tuple, list)) else (item, None)
        if not mac or len(mac) != 17 or is_random_mac(mac):
            continue  # private MACs: their IPv6 addresses aren't derived from the MAC
        for n in ([dev] if dev in idx else ([] if dev else list(idx))):
            probes.udp_poke("%s%%%s" % (eui64_link_local(mac), n))
    for t in threads:
        t.join(timeout=6)
    # answers to unicast replies make the devices resolve us, and the kernel learns them
    # (an IPv6 mDNS answer also lists IPv4 A records; only IPv6 senders matter here)
    for key in ("mdns", "ssdp", "wsd"):
        found[key] = {a: e for a, e in found.get(key, {}).items() if is_ipv6(a)}
    # Routable senders get a datagram so the kernel resolves them; link-local senders already
    # had to resolve us to answer, which put them into the table on the right interface.
    for addr in list(found.get("mdns", {})) + list(found.get("ssdp", {})) + list(found.get("wsd", {})):
        if kind(addr) != "link":
            probes.udp_poke(addr)
    time.sleep(settle)

    own_ips = {a["ip"] for a in own}
    prefixes = {n: ["%s/%d" % (a["ip"], a["prefix"]) for a in own if a["dev"] == n and a["scope"] != "link"] for n in idx}
    result["routable"] = any(prefixes.values())
    result["prefixes"] = prefixes
    for n in neighbors():
        if n["dev"] not in idx or n["ip"] in own_ips:
            continue
        if not on_link_filter([n["ip"]], prefixes.get(n["dev"], ())):
            continue
        e = result["neighbors"].setdefault(n["mac"], {"addrs": [], "dev": n["dev"], "router": False})
        e["addrs"].append(n["ip"])
        e["router"] = e["router"] or n["router"]
    for e in result["neighbors"].values():
        e["addrs"] = sort_addresses(e["addrs"])
    result["mdns"] = found.get("mdns", {})
    result["ssdp"] = found.get("ssdp", {})
    result["wsd"] = found.get("wsd", {})
    log.info("IPv6: %d neighbour(s) on %s (echo: %s)", len(result["neighbors"]), ", ".join(idx), result["echo"] or "none")
    return result
