"""Unprivileged network probes used by the scanner."""
import errno
import html
import ipaddress
import os
import re
import selectors
import socket
import ssl
import struct
import subprocess
import time
import urllib.parse
from xml.parsers import expat

from . import dnsmsg
from .util import clean_text

ALIVE_ERRNOS = {errno.ECONNREFUSED, errno.ECONNRESET}
# Answers to multicast queries are unauthenticated datagrams; any device on the LAN can send
# as many as it likes under as many sender addresses as it likes. Everything collected from
# them is bounded.
MAX_SENDERS = 4096
MAX_LOCATIONS = 4  # UPnP descriptions tried per device


# --------------------------------------------------------------------------- TCP
def _sockaddr(ip, port, kind=socket.SOCK_STREAM):
    """(family, sockaddr) for an IPv4 or IPv6 address; link-local IPv6 may carry "%iface"."""
    if ":" not in ip:
        return socket.AF_INET, (ip, port)
    info = socket.getaddrinfo(ip, port, socket.AF_INET6, kind, 0, socket.AI_NUMERICHOST)
    return socket.AF_INET6, info[0][4]


def tcp_probe(ip, ports, timeout=0.6):
    """Connect to many ports in parallel. Return {port: 'open'|'closed'|'filtered'}."""
    sel = selectors.DefaultSelector()
    result = {}
    socks = []
    try:
        for port in ports:
            family, addr = _sockaddr(ip, port)
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setblocking(False)
            socks.append(s)
            rc = s.connect_ex(addr)
            if rc == 0:
                result[port] = "open"
            elif rc in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN):
                sel.register(s, selectors.EVENT_WRITE, port)
            elif rc in ALIVE_ERRNOS:
                result[port] = "closed"
            else:
                result[port] = "filtered"
        deadline = time.monotonic() + timeout
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for key, _ in sel.select(remaining):
                s, port = key.fileobj, key.data
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0:
                    result[port] = "open"
                elif err in ALIVE_ERRNOS:
                    result[port] = "closed"
                else:
                    result[port] = "filtered"
                sel.unregister(s)
        for key in list(sel.get_map().values()):
            result[key.data] = "filtered"
    finally:
        sel.close()
        for s in socks:
            s.close()
    return result


def udp_poke(ip, port=9):
    """Send a tiny datagram – forces the kernel to resolve `ip` (ARP, or neighbour discovery
    for IPv6)."""
    try:
        family, addr = _sockaddr(ip, port, socket.SOCK_DGRAM)
        s = socket.socket(family, socket.SOCK_DGRAM)
    except (OSError, ValueError):
        return
    try:
        s.sendto(b"\x00", addr)
    except OSError:
        pass
    finally:
        s.close()


# -------------------------------------------------------------------------- ping
_PING = {"checked": False, "cmd": None}


def ping_available():
    if not _PING["checked"]:
        _PING["checked"] = True
        for path in ("/bin/ping", "/usr/bin/ping", "/sbin/ping", "/usr/sbin/ping"):
            if os.access(path, os.X_OK):
                try:
                    r = subprocess.run([path, "-c", "1", "-W", "1", "127.0.0.1"],
                                       capture_output=True, timeout=3)
                    if r.returncode == 0:
                        _PING["cmd"] = path
                        break
                except (OSError, subprocess.SubprocessError):
                    pass
    return _PING["cmd"] is not None


def ping(ip, timeout=1):
    if not ping_available():
        return None
    try:
        r = subprocess.run([_PING["cmd"], "-c", "1", "-W", str(max(1, int(timeout))), ip],
                           capture_output=True, text=True, timeout=timeout + 2)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"time[=<]([\d.]+)\s*ms", r.stdout)
    return float(m.group(1)) if m else 0.0


# ---------------------------------------------------------------- reverse DNS
def reverse_dns(ip):
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError, UnicodeError):
        return ""
    return "" if name == ip else name.rstrip(".")


# ------------------------------------------------------------------- NetBIOS
def _nb_encode(name):
    name = name.ljust(16, "\x00") if name == "*" else name.upper().ljust(15)[:15] + "\x00"
    out = b""
    for c in name.encode("latin-1"):
        out += bytes([0x41 + (c >> 4), 0x41 + (c & 0x0F)])
    return b"\x20" + out + b"\x00"


def parse_netbios_status(data):
    """Parse an NBSTAT response -> {'name', 'workgroup', 'mac'}."""
    off = 12
    # question name echoed in the answer: length-prefixed labels
    while off < len(data) and data[off] != 0:
        off += 1 + data[off]
    off += 1 + 2 + 2 + 4  # null, type, class, ttl
    rdlen = struct.unpack("!H", data[off:off + 2])[0]
    off += 2
    end = off + rdlen
    count = data[off]
    off += 1
    name = workgroup = ""
    for _ in range(count):
        raw = data[off:off + 15].decode("latin-1", "replace").rstrip(" \x00")
        suffix = data[off + 15]
        flags = struct.unpack("!H", data[off + 16:off + 18])[0]
        off += 18
        group = bool(flags & 0x8000)
        if suffix == 0x00 and not group and not name:
            name = raw
        elif suffix == 0x00 and group and not workgroup:
            workgroup = raw
    mac = ""
    if off + 6 <= end:
        mac = ":".join("%02x" % b for b in data[off:off + 6])
    return {"name": name, "workgroup": workgroup, "mac": mac}


def netbios_status(ip, timeout=1.0):
    pkt = struct.pack("!HHHHHH", 0x5353, 0, 1, 0, 0, 0) + _nb_encode("*") + struct.pack("!HH", 0x21, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (ip, 137))
        data, _ = s.recvfrom(2048)
        return parse_netbios_status(data)
    except (OSError, IndexError, struct.error, ValueError):
        return None
    finally:
        s.close()


# ---------------------------------------------------------------------- mDNS
MDNS_ADDR = ("224.0.0.251", 5353)
MAX_SERVICE_TYPES = 128
_SERVICE_TYPE = re.compile(r"^_[A-Za-z0-9_-]{1,62}\._(tcp|udp)\.local$", re.I)


def mdns_reverse(ip, timeout=0.8):
    """Ask the host itself (unicast to :5353) for its .local name."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(dnsmsg.build_query([(dnsmsg.reverse_name(ip), dnsmsg.T_PTR)], txid=0x2A2A), (ip, 5353))
        data, _ = s.recvfrom(9000)
        for rec in dnsmsg.parse_message(data)["records"]:
            if rec["type"] == dnsmsg.T_PTR and rec["value"]:
                return rec["value"].rstrip(".")
    except (OSError, ValueError, struct.error, IndexError):
        pass
    finally:
        s.close()
    return ""


def mdns_host(ip, services=(), timeout=1.5, port=5353, name=""):
    """Ask a device itself (unicast to :5353) for its .local name and the IPv6 addresses it
    announces for it: (name, [address, ..]).

    For a device that answered the browse without the records that carry them. `services`
    are the types it offers ("_hue._tcp"); with `name` known, only its addresses are asked
    for. Asked like a DNS-SD client resolves a service: type -> instance -> host name ->
    addresses, in at most three exchanges. A question that gets no answer within half of
    `timeout` is sent once more (a Hue bridge answered slowly, or not at all, while a scan
    was probing it). Every sending has an ID of its own: a late answer to an earlier one
    still delivers its records, but does not count as the answer to the current one."""
    found = {"name": name.rstrip(".")}
    instances, addresses = [], {}
    current = set()  # IDs of the questions of the current exchange
    answered = [False]

    def handle(data, _addr):
        for rec in dnsmsg.parse_message(data)["records"]:
            t, rname, val = rec["type"], rec["name"].lower(), rec["value"]
            if not val:
                continue
            if t == dnsmsg.T_PTR and rname.endswith(".arpa"):
                found["name"] = val.rstrip(".")
            elif t == dnsmsg.T_PTR and val not in instances and len(instances) < 2:
                instances.append(val)
            elif t == dnsmsg.T_SRV and val["target"] and not found["name"]:
                found["name"] = val["target"].rstrip(".")
            elif t == dnsmsg.T_A and val == ip and not found["name"]:
                found["name"] = rec["name"].rstrip(".")
            elif t == dnsmsg.T_AAAA and (rname in addresses or len(addresses) < 8):
                lst = addresses.setdefault(rname, [])
                if val not in lst and len(lst) < 8:
                    lst.append(val)
        if struct.unpack("!H", data[:2])[0] in current:
            answered[0] = True
            return True
        return False  # a late answer to an earlier question: no reason to stop listening

    asked = set()
    if found["name"]:
        ask = [(found["name"], dnsmsg.T_AAAA)]
    else:
        ask = [(dnsmsg.reverse_name(ip), dnsmsg.T_PTR)] + [(t + ".local", dnsmsg.T_PTR) for t in list(services)[:3]]
    txid = 0x2B00
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, port))  # answers from any other address are not read
        for _ in range(3):
            ask = [q for q in ask if q not in asked]
            if not ask:
                break
            asked.update(ask)
            current.clear()
            answered[0] = False
            for _attempt in range(2):
                for question in ask:  # one each: not every responder answers several in one packet
                    txid += 1
                    current.add(txid)
                    s.send(dnsmsg.build_query([question], txid=txid))
                _collect(s, timeout / 2.0, handle, quiet=0.25)
                if answered[0]:
                    break
            if not found["name"]:
                ask = [(i, dnsmsg.T_SRV) for i in instances]
            elif found["name"].lower() not in addresses:
                ask = [(found["name"], dnsmsg.T_AAAA)]
            else:
                break
    except OSError:
        pass
    finally:
        s.close()
    return found["name"], addresses.get(found["name"].lower(), [])


def _collect(sock, duration, handler, quiet=None):
    """Hand every datagram that arrives within `duration` to `handler`. With `quiet`, stop
    as soon as that many seconds have passed since the last one."""
    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        sock.settimeout(remaining)
        try:
            data, addr = sock.recvfrom(9000)
        except socket.timeout:
            return
        except OSError:
            return
        try:
            counted = handler(data, addr)
        except (ValueError, struct.error, IndexError):
            continue
        if quiet is not None and counted is not False:
            deadline = min(deadline, time.monotonic() + quiet)


def _mcast_socket(iface_ip=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    if iface_ip:
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
        except OSError:
            pass
    s.bind(("", 0))
    return s


def _mcast_socket6(ifindex, source=None):
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 2)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, ifindex)
    try:
        s.bind((source or "::", 0))
    except OSError:
        s.bind(("::", 0))
    return s


def _open_mcast(iface_ips, ifindexes, sources=None):
    """Sockets with their multicast destination factory: IPv4 (by interface address) or
    IPv6 (by interface index)."""
    socks = []
    if ifindexes is not None:
        for idx in ifindexes:
            try:
                socks.append((_mcast_socket6(idx, (sources or {}).get(idx)), idx))
            except OSError:
                pass
    else:
        for ip in (iface_ips or [None]):
            try:
                socks.append((_mcast_socket(ip), None))
            except OSError:
                pass
    return socks


def _host_addr(addr):
    """The sender address of a datagram without its IPv6 zone ("fe80::1%eth0" -> "fe80::1")."""
    return addr[0].split("%")[0]


def mdns_browse(iface_ips, duration=2.5, ifindexes=None, sources=None, ready=None):
    """DNS-SD browse via legacy-unicast multicast queries, over IPv4 or (with `ifindexes`) IPv6.

    `ready` (a threading.Event) is set once the questions have been out for a moment: a scan
    holds its probes back until then, so devices answer the browse undisturbed.

    Returns {ip: {"services": [..], "instances": [..], "hostname": str, "txt": {}, "ipv4": str,
    "ipv6": [..]}}. "ipv4"/"ipv6" are the addresses the device announces for its host name.
    """
    hosts = {}
    host_ips = {}   # hostname.local -> IPv4 (A records)
    host_ips6 = {}  # hostname.local -> [IPv6] (AAAA records)

    def entry(ip):
        return hosts.setdefault(ip, {"services": set(), "instances": set(), "hostname": "", "txt": {}})

    def add(items, value, most):
        if len(items) < most:
            items.add(value[:100])

    def handle(data, addr):
        msg = dnsmsg.parse_message(data)
        sender = _host_addr(addr)
        if sender not in hosts and len(hosts) >= MAX_SENDERS:
            return
        e = entry(sender)
        for rec in msg["records"]:
            t, name, val = rec["type"], rec["name"], rec["value"]
            if t == dnsmsg.T_PTR and val:
                if name == "_services._dns-sd._udp.local":
                    # only well-formed types are kept, and no more are queried in the
                    # second round than a real network has
                    if not _SERVICE_TYPE.match(val):
                        continue
                    if len(service_types) < MAX_SERVICE_TYPES:
                        service_types.add(val)
                    add(e["services"], val.replace(".local", ""), 40)
                elif name.endswith(".local") and name.startswith("_"):
                    if _SERVICE_TYPE.match(name):
                        add(e["services"], name.replace(".local", ""), 40)
                    inst = val[: -len(name) - 1] if val.endswith(name) else val
                    if inst:
                        add(e["instances"], inst, 20)
            elif t == dnsmsg.T_A and val:
                if name in host_ips or len(host_ips) < MAX_SENDERS:
                    host_ips[name] = val
                if val == addr[0]:
                    e["hostname"] = name.rstrip(".")
            elif t == dnsmsg.T_AAAA and val:
                if name not in host_ips6 and len(host_ips6) >= MAX_SENDERS:
                    continue
                lst = host_ips6.setdefault(name, [])
                if val not in lst and len(lst) < 8:
                    lst.append(val)
                if val == _host_addr(addr):
                    e["hostname"] = name.rstrip(".")
            elif t == dnsmsg.T_SRV and val:
                target = val["target"].rstrip(".")
                if target and not e["hostname"]:
                    e["hostname"] = target
            elif t == dnsmsg.T_TXT and isinstance(val, dict):
                for k in ("md", "model", "ty", "usb_mfg", "usb_mdl", "fn", "am", "vendor", "manufacturer"):
                    if val.get(k) and k not in e["txt"]:
                        e["txt"][k] = val[k][:80]

    service_types = set()
    socks = _open_mcast(iface_ips, ifindexes, sources)
    common = {"_http._tcp.local", "_workstation._tcp.local", "_smb._tcp.local",
              "_airplay._tcp.local", "_googlecast._tcp.local", "_ipp._tcp.local",
              "_printer._tcp.local", "_raop._tcp.local", "_device-info._tcp.local",
              "_companion-link._tcp.local", "_hap._tcp.local", "_spotify-connect._tcp.local",
              "_ssh._tcp.local", "_sonos._tcp.local", "_homekit._tcp.local"}
    start = time.monotonic()

    def send(names, txid):
        for i in range(0, len(names), 12):
            q = dnsmsg.build_query([(n, dnsmsg.T_PTR) for n in names[i:i + 12]], txid=txid + i)
            for s, idx in socks:
                try:
                    s.sendto(q, ("ff02::fb", 5353, 0, idx) if idx is not None else MDNS_ADDR)
                except OSError:
                    pass

    def listen(until):
        for k, (s, _) in enumerate(socks):
            _collect(s, max(0.0, (start + duration * until - time.monotonic()) / (len(socks) - k)), handle)

    try:
        send(["_services._dns-sd._udp.local"], 0x1111)
        listen(0.24)
        send(sorted(service_types | common), 0x2222)
        listen(0.34)
        # everything once more, still before the scan starts probing: one lost datagram must
        # not cost a device its name, and types announced late get asked too
        send(["_services._dns-sd._udp.local"] + sorted(service_types | common), 0x3333)
        listen(0.44)
        if ready is not None:
            ready.set()
        listen(1.0)
    finally:
        if ready is not None:
            ready.set()
        for s, _ in socks:
            s.close()
    for name, ip in host_ips.items():
        e = entry(ip)
        if not e["hostname"]:
            e["hostname"] = name.rstrip(".")
    for e in hosts.values():
        e["services"] = sorted(e["services"])
        e["instances"] = sorted(e["instances"])
        key = (e["hostname"] + ".") if e["hostname"] and not e["hostname"].endswith(".") else e["hostname"]
        names = [n for n in (e["hostname"], key) if n]
        e["ipv4"] = next((host_ips[n] for n in names if n in host_ips), "")
        e["ipv6"] = next((host_ips6[n] for n in names if n in host_ips6), [])
    return {ip: e for ip, e in hosts.items() if e["services"] or e["hostname"] or e["instances"]}


# ---------------------------------------------------------------------- SSDP
def parse_ssdp(data):
    headers = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        k, sep, v = line.partition(":")
        if sep:
            headers[k.strip().lower()] = v.strip()
    return headers


def ssdp_discover(iface_ips, duration=2.5, ifindexes=None):
    """Return {ip: {"locations": [url, ..], "server": str, "st": [..]}} (IPv6 with `ifindexes`).

    A device may run several UPnP stacks, each announcing a description of its own: the
    locations are kept in the order they arrived, "server" is that of the first answer."""
    found = {}
    host = "[FF02::C]:1900" if ifindexes is not None else "239.255.255.250:1900"
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: %s\r\n"
           "MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n" % host).encode()

    def handle(data, addr):
        h = parse_ssdp(data)
        sender = _host_addr(addr)
        if sender not in found and len(found) >= MAX_SENDERS:
            return
        e = found.setdefault(sender, {"locations": [], "server": "", "st": []})
        location = h.get("location", "")[:1024]
        if location and location not in e["locations"] and len(e["locations"]) < MAX_LOCATIONS:
            e["locations"].append(location)
        if h.get("server") and not e["server"]:
            e["server"] = h["server"][:120]
        st = (h.get("st") or h.get("nt") or "")[:200]
        if st and st not in e["st"] and len(e["st"]) < 12:
            e["st"].append(st)

    socks = _open_mcast(iface_ips, ifindexes)
    try:
        for s, idx in socks:
            for _ in range(2):
                try:
                    s.sendto(msg, ("ff02::c", 1900, 0, idx) if idx is not None else ("239.255.255.250", 1900))
                except OSError:
                    pass
        for s, _ in socks:
            _collect(s, duration / max(1, len(socks)), handle)
    finally:
        for s, _ in socks:
            s.close()
    return found


# --------------------------------------------------------------- WS-Discovery
_WSD_PROBE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
    '<soap:Header><wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>'
    '<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>'
    '<wsa:MessageID>urn:uuid:%s</wsa:MessageID></soap:Header>'
    '<soap:Body><wsd:Probe/></soap:Body></soap:Envelope>')


_WSD_TYPES = re.compile(rb"<(?:[\w.-]+:)?Types>([^<]*)<")


def wsd_discover(iface_ips, duration=2.0, ifindexes=None, sources=None):
    """WS-Discovery probe (Windows PCs, printers, scanners, many NAS).

    Returns {ip: {"types": str}}; with `ifindexes` over IPv6 (ff02::c), else IPv4."""
    import uuid
    found = {}
    msg = (_WSD_PROBE % uuid.uuid4()).encode()

    def handle(data, addr):
        sender = _host_addr(addr)
        if sender in found or len(found) >= MAX_SENDERS:
            return
        m = _WSD_TYPES.search(data)
        found[sender] = {"types": (m.group(1)[:200].decode("utf-8", "replace") if m else "")}

    socks = _open_mcast(iface_ips, ifindexes, sources)
    try:
        for s, idx in socks:
            for _ in range(2):
                try:
                    s.sendto(msg, ("ff02::c", 3702, 0, idx) if idx is not None else ("239.255.255.250", 3702))
                except OSError:
                    pass
        for s, _ in socks:
            _collect(s, duration / max(1, len(socks)), handle)
    finally:
        for s, _ in socks:
            s.close()
    return found


# ---------------------------------------------------------------------- HTTP
# A deliberately small HTTP client instead of urllib. The scanner only ever connects to the
# address it is looking at: no proxies, no other URL schemes (urllib also opens file:// and
# ftp://), and redirects stay on the device. Every exchange has one overall deadline, so a
# device cannot hold up a scan by sending its answer byte by byte. Certificates are not
# verified: devices on a LAN use self-signed ones, and nothing confidential is sent.
MAX_HEADER = 32768
_HEADER_END = re.compile(rb"\r?\n\r?\n")
_STATUS = re.compile(r"^HTTP/1\.[01] (\d{3})(?: |$)")
_HEX = re.compile(rb"^[0-9A-Fa-f]{1,8}$")
_PATH_OK = re.compile(r"^/[\x21-\x7e]{0,1023}$")
_MOVED = re.compile(r"\b(moved|found|redirect\w*|see other)\b", re.I)  # "301 Moved Permanently", "Object moved"
_HOST_OK = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_tls = []


class _Deadline:
    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def left(self, cap=None):
        left = self.end - time.monotonic()
        if left <= 0:
            raise socket.timeout("deadline reached")
        return min(left, cap) if cap else left


def _tls_context():
    if not _tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _tls.append(ctx)
    return _tls[0]


class _Chunked:
    """Incremental decoder for "Transfer-Encoding: chunked"."""

    def __init__(self):
        self.buf = b""
        self.need = 0  # bytes still missing from the current chunk
        self.done = False

    def feed(self, data):
        self.buf += data
        out = []
        while not self.done and self.buf:
            if self.need:
                out.append(self.buf[:self.need])
                self.need -= len(out[-1])
                self.buf = self.buf[len(out[-1]):]
                continue
            eol = self.buf.find(b"\n")
            if eol < 0:
                self.done = len(self.buf) > 64  # no size line: not chunked after all
                break
            line, self.buf = self.buf[:eol].split(b";")[0].strip(), self.buf[eol + 1:]
            if not line:
                continue  # the line break that ends a chunk
            if not _HEX.match(line):
                self.done = True
                break
            self.need = int(line, 16)
            self.done = self.need == 0
        return b"".join(out)


def _http_get(addr, port, tls, host, path, deadline, max_body, agent):
    """One GET request to `addr`:`port`. Returns (status, headers, body). The body may be cut
    short: by `max_body`, by the deadline or by the device closing the connection."""
    ipaddress.ip_address(addr.split("%")[0])  # an address, never a name that would be resolved
    family, sockaddr = _sockaddr(addr, port)
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(deadline.left(2.0))
        sock.connect(sockaddr)
        if tls:
            sock.settimeout(deadline.left())
            sock = _tls_context().wrap_socket(sock)
        sock.settimeout(deadline.left())
        sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nAccept: */*\r\n"
                      "Accept-Encoding: identity\r\nConnection: close\r\n\r\n" % (path, host, agent)).encode("ascii"))
        buf, scanned, interim = b"", 0, 0
        while True:
            m = _HEADER_END.search(buf, max(0, scanned - 3))
            if not m:
                if len(buf) > MAX_HEADER:
                    raise ValueError("HTTP header too large")
                scanned = len(buf)
                sock.settimeout(deadline.left())
                chunk = sock.recv(8192)
                if chunk:
                    buf += chunk
                    continue
                if not _STATUS.match(buf.decode("latin-1").strip()):
                    raise ValueError("no HTTP header")
                buf += b"\r\n\r\n"  # tiny servers end the header with the connection
                continue
            lines = buf[:m.start()].decode("latin-1").split("\n")
            st = _STATUS.match(lines[0].strip())
            if not st:
                raise ValueError("not an HTTP answer")
            status = int(st.group(1))
            if 100 <= status < 200 and status != 101 and interim < 4:
                # "100 Continue" and the like: the real answer follows
                buf, scanned, interim = buf[m.end():], 0, interim + 1
                continue
            break
        headers = {}
        for line in lines[1:]:
            k, sep, v = line.partition(":")
            if sep:
                headers.setdefault(k.strip().lower(), v.strip())
        if status < 200 or status in (204, 304):
            return status, headers, b""
        chunked = _Chunked() if "chunked" in headers.get("transfer-encoding", "").lower() else None
        want = max_body
        if not chunked and headers.get("content-length", "").isdigit():
            want = min(max_body, int(headers["content-length"]))
        body = bytearray()
        data = buf[m.end():]
        try:
            while True:
                body += chunked.feed(data) if chunked else data
                if len(body) >= want or (chunked and chunked.done):
                    break
                sock.settimeout(deadline.left())
                data = sock.recv(16384)
                if not data:
                    break
        except OSError:  # deadline or connection reset: what has arrived is still useful
            pass
        return status, headers, bytes(body[:want])
    finally:
        sock.close()


def _url_host(ip):
    return "[%s]" % ip if ":" in ip else ip


def _request_path(u):
    """Path and query of a parsed URL for the request line: printable ASCII only, so nothing
    in it can end the line and start a request of its own. None if it is unusable."""
    path = urllib.parse.quote((u.path or "/") + ("?" + u.query if u.query else ""), safe="/?:@!$&'()*+,;=%~-._")
    return path if _PATH_OK.match(path) else None


def _redirect(headers, tls, host, port, path, ip):
    """Where a redirect leads, as (tls, host, port, path) – or None if it is not followed.

    The connection always goes to `ip` again; the host name of the redirect is only sent as
    Host header (routers redirect to names like "fritz.box"). A redirect to another IP address
    is another machine and is not followed."""
    location = headers.get("location", "")
    if not location or len(location) > 2048:
        return None
    base = "%s://%s:%d%s" % ("https" if tls else "http", host, port, path)
    try:
        u = urllib.parse.urlsplit(urllib.parse.urljoin(base, location))
        new_port = u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or u.username is not None or u.password is not None:
        return None
    new_host = u.hostname or ""
    try:
        if ipaddress.ip_address(new_host) != ipaddress.ip_address(ip):
            return None
        new_host = _url_host(ip)
    except ValueError:
        new_host = new_host.rstrip(".")
        if not _HOST_OK.match(new_host):
            return None
    if new_port is None:
        new_port = 443 if u.scheme == "https" else 80
    new_path = _request_path(u)
    if not 0 < new_port < 65536 or not new_path:
        return None
    return u.scheme == "https", new_host, new_port, new_path


def _html_title(body):
    low = body.lower()
    start = low.find(b"<title")
    start = low.find(b">", start) if start >= 0 else -1
    end = low.find(b"</title", start) if start >= 0 else -1
    if end < 0:
        return ""
    return clean_text(html.unescape(body[start + 1:end][:2000].decode("utf-8", "replace")), 100)


def http_info(ip, port, timeout=4.0):
    """Title and Server header of the web page on `ip`:`port`, within `timeout` seconds in
    total. Redirects are followed on the device itself only."""
    if "%" in ip:
        return None
    deadline = _Deadline(timeout)
    tls, host, cur_port, path = port in (443, 5001, 8443), _url_host(ip), port, "/"
    server = title = ""
    answered = False
    try:
        for _hop in range(10):  # as many as urllib followed; the deadline bounds the time
            default = 443 if tls else 80
            status, headers, body = _http_get(ip, cur_port, tls, host if cur_port == default else "%s:%d" % (host, cur_port),
                                              path, deadline, 65536, "Mozilla/5.0 SynetScan")
            answered = True
            server = headers.get("server", "") or server
            title = _html_title(body)
            if status not in (301, 302, 303, 307, 308):
                break
            if _MOVED.search(title):
                title = ""  # the page of a redirect that is not followed names nothing
            target = _redirect(headers, tls, host, cur_port, path, ip)
            if not target:
                break
            tls, host, cur_port, path = target
    except (OSError, ValueError, UnicodeError):
        if not answered:
            return None
    return {"port": port, "server": clean_text(server, 100), "title": title}


# ---------------------------------------------------------------------- UPnP
_UPNP_FIELDS = ("friendlyName", "manufacturer", "modelName", "modelNumber", "deviceType", "modelDescription")


def parse_upnp(body):
    """The identifying fields of a UPnP device description (first occurrence = root device).

    Read as a stream, without building a tree. A document that declares entities is
    refused: entity expansion ("billion laughs") is the classic way to exhaust the memory of
    whoever parses it. A plain DOCTYPE is fine. Returns None for those, else a dict."""
    out = {}
    cur = {"tag": None, "text": [], "size": 0}

    def refuse(*_args):
        raise ValueError("DTD in a device description")

    def close(_name=None):
        if cur["tag"]:
            text = clean_text("".join(cur["text"]), 120)
            if text and cur["tag"] not in out:
                out[cur["tag"]] = text
        cur["tag"], cur["text"], cur["size"] = None, [], 0

    def start(name, _attrs):
        close()
        tag = name.rsplit(":", 1)[-1]
        if tag in _UPNP_FIELDS and tag not in out:
            cur["tag"] = tag

    def chars(data):
        if cur["tag"] and cur["size"] < 1024:
            cur["text"].append(data)
            cur["size"] += len(data)

    parser = expat.ParserCreate()
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = close
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(body, True)
    except ValueError:
        return None
    except expat.ExpatError:
        pass  # many devices send sloppy XML: keep what was readable up to the error
    return out


def upnp_description(location, sender, timeout=4.0):
    """Fetch the UPnP device description announced over SSDP -> friendlyName, manufacturer, model…

    `location` comes out of an unauthenticated datagram. Only its scheme, port and path are
    used; the request always goes to `sender`, the address the announcement came from
    (link-local IPv6 with "%iface"). A LOCATION can therefore not make the NAS read local
    files or talk to any other host."""
    try:
        u = urllib.parse.urlsplit(str(location).strip())
        port = u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https"):
        return None
    tls = u.scheme == "https"
    if port is None:
        port = 443 if tls else 80
    path = _request_path(u)
    if not 0 < port < 65536 or not path:
        return None
    deadline = _Deadline(timeout)
    addr = sender.split("%")[0]
    host = "%s:%d" % (_url_host(addr), port)
    try:
        for _hop in range(3):
            status, headers, body = _http_get(sender, port, tls, host, path, deadline, 262144, "SynetScan/1.0 UPnP/1.1")
            if status not in (301, 302, 303, 307, 308):
                break
            target = _redirect(headers, tls, _url_host(addr), port, path, addr)  # on the same device only
            if not target:
                return None
            tls, name, port, path = target
            host = name if port == (443 if tls else 80) else "%s:%d" % (name, port)
    except (OSError, ValueError, UnicodeError):
        return None
    if not 200 <= status < 300:
        return None
    return parse_upnp(body)


def upnp_first_description(locations, sender, budget=8.0):
    """The first of a device's announced descriptions that can be read, or None.

    Not every UPnP stack on a device describes it: a router may answer for its gateway
    service and for an agent of its provider, and only the first names the model. `budget`
    bounds the time for all of them together."""
    end = time.monotonic() + budget
    best = None
    for location in locations:
        left = end - time.monotonic()
        if left < 0.5:
            break
        desc = upnp_description(location, sender, min(4.0, left))
        if desc and (desc.get("friendlyName") or desc.get("modelName")):
            return desc
        if desc and len(desc) > len(best or {}):
            best = desc  # readable, but names nothing: another stack may do better
    return best


# ----------------------------------------------------------------------- WOL
def wake_on_lan(mac, broadcasts=("255.255.255.255",), port=9):
    hexs = mac.replace(":", "").replace("-", "")
    if len(hexs) != 12:
        raise ValueError("invalid MAC")
    payload = b"\xff" * 6 + bytes.fromhex(hexs) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sent = 0
    try:
        for b in broadcasts:
            for p in (port, 7):
                try:
                    s.sendto(payload, (b, p))
                    sent += 1
                except OSError:
                    pass
    finally:
        s.close()
    return sent
