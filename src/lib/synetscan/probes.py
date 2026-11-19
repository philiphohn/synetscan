"""Unprivileged network probes used by the scanner."""
import errno
import html
import os
import re
import selectors
import socket
import ssl
import struct
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

from . import dnsmsg

ALIVE_ERRNOS = {errno.ECONNREFUSED, errno.ECONNRESET}


# --------------------------------------------------------------------------- TCP
def tcp_probe(ip, ports, timeout=0.6):
    """Connect to many ports in parallel. Return {port: 'open'|'closed'|'filtered'}."""
    sel = selectors.DefaultSelector()
    result = {}
    socks = []
    try:
        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            socks.append(s)
            rc = s.connect_ex((ip, port))
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
    """Send a tiny datagram – forces the kernel to ARP-resolve `ip`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(b"\x00", (ip, port))
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


def _collect(sock, duration, handler):
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
            handler(data, addr)
        except (ValueError, struct.error, IndexError):
            continue


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


def mdns_browse(iface_ips, duration=2.5):
    """DNS-SD browse via legacy-unicast multicast queries.

    Returns {ip: {"services": set, "instances": set, "hostname": str, "txt": {}}}.
    """
    hosts = {}
    host_ips = {}  # hostname.local -> ip (from A records)

    def entry(ip):
        return hosts.setdefault(ip, {"services": set(), "instances": set(), "hostname": "", "txt": {}})

    def handle(data, addr):
        msg = dnsmsg.parse_message(data)
        e = entry(addr[0])
        for rec in msg["records"]:
            t, name, val = rec["type"], rec["name"], rec["value"]
            if t == dnsmsg.T_PTR and val:
                if name == "_services._dns-sd._udp.local":
                    service_types.add(val)
                    e["services"].add(val.replace(".local", ""))
                elif name.endswith(".local") and name.startswith("_"):
                    e["services"].add(name.replace(".local", ""))
                    inst = val[: -len(name) - 1] if val.endswith(name) else val
                    if inst:
                        e["instances"].add(inst)
            elif t == dnsmsg.T_A and val:
                host_ips[name] = val
                if val == addr[0]:
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
    socks = []
    try:
        for ip in (iface_ips or [None]):
            try:
                socks.append(_mcast_socket(ip))
            except OSError:
                pass
        q = dnsmsg.build_query([("_services._dns-sd._udp.local", dnsmsg.T_PTR)], txid=0x1111)
        for s in socks:
            try:
                s.sendto(q, MDNS_ADDR)
            except OSError:
                pass
        for s in socks:
            _collect(s, duration / 2.0 / max(1, len(socks)), handle)
        common = {"_http._tcp.local", "_workstation._tcp.local", "_smb._tcp.local",
                  "_airplay._tcp.local", "_googlecast._tcp.local", "_ipp._tcp.local",
                  "_printer._tcp.local", "_raop._tcp.local", "_device-info._tcp.local",
                  "_companion-link._tcp.local", "_hap._tcp.local", "_spotify-connect._tcp.local",
                  "_ssh._tcp.local", "_sonos._tcp.local", "_homekit._tcp.local"}
        types = sorted((service_types | common))
        for i in range(0, len(types), 12):
            q = dnsmsg.build_query([(t, dnsmsg.T_PTR) for t in types[i:i + 12]], txid=0x2222 + i)
            for s in socks:
                try:
                    s.sendto(q, MDNS_ADDR)
                except OSError:
                    pass
        for s in socks:
            _collect(s, duration / 2.0 / max(1, len(socks)), handle)
    finally:
        for s in socks:
            s.close()
    for name, ip in host_ips.items():
        e = entry(ip)
        if not e["hostname"]:
            e["hostname"] = name.rstrip(".")
    for e in hosts.values():
        e["services"] = sorted(e["services"])
        e["instances"] = sorted(e["instances"])
    return {ip: e for ip, e in hosts.items() if e["services"] or e["hostname"] or e["instances"]}


# ---------------------------------------------------------------------- SSDP
def parse_ssdp(data):
    headers = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        k, sep, v = line.partition(":")
        if sep:
            headers[k.strip().lower()] = v.strip()
    return headers


def ssdp_discover(iface_ips, duration=2.5):
    """Return {ip: {"location": url, "server": str, "st": [..]}}."""
    found = {}
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           "MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n").encode()

    def handle(data, addr):
        h = parse_ssdp(data)
        e = found.setdefault(addr[0], {"location": "", "server": "", "st": []})
        if h.get("location") and not e["location"]:
            e["location"] = h["location"]
        if h.get("server") and not e["server"]:
            e["server"] = h["server"][:120]
        st = h.get("st") or h.get("nt")
        if st and st not in e["st"] and len(e["st"]) < 12:
            e["st"].append(st)

    socks = []
    try:
        for ip in (iface_ips or [None]):
            try:
                socks.append(_mcast_socket(ip))
            except OSError:
                pass
        for s in socks:
            for _ in range(2):
                try:
                    s.sendto(msg, ("239.255.255.250", 1900))
                except OSError:
                    pass
        for s in socks:
            _collect(s, duration / max(1, len(socks)), handle)
    finally:
        for s in socks:
            s.close()
    return found


def upnp_description(url, timeout=2.0):
    """Fetch the UPnP device description -> friendlyName, manufacturer, model..."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SynetScan/1.0 UPnP/1.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(262144)
        root = ET.fromstring(body)
    except Exception:  # noqa: BLE001 - many malformed devices out there
        return None
    out = {}
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("friendlyName", "manufacturer", "modelName", "modelNumber", "deviceType",
                   "modelDescription") and tag not in out and (el.text or "").strip():
            out[tag] = el.text.strip()[:120]
    return out


# ---------------------------------------------------------------------- HTTP
_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)


def http_info(ip, port, timeout=2.0):
    scheme = "https" if port in (443, 5001, 8443) else "http"
    url = "%s://%s:%d/" % (scheme, ip, port)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SynetScan"})
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        with opener.open(req, timeout=timeout) as r:
            server = r.headers.get("Server", "")
            body = r.read(65536)
    except urllib.error.HTTPError as e:
        server = e.headers.get("Server", "") if e.headers else ""
        try:
            body = e.read(65536)
        except Exception:  # noqa: BLE001
            body = b""
    except Exception:  # noqa: BLE001
        return None
    title = ""
    m = _TITLE.search(body or b"")
    if m:
        title = html.unescape(m.group(1).decode("utf-8", "replace"))
        title = re.sub(r"\s+", " ", title).strip()[:100]
    return {"port": port, "server": server[:100], "title": title}


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
