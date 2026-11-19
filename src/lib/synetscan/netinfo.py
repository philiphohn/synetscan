"""Discover the NAS's own network configuration without root privileges."""
import fcntl
import ipaddress
import os
import re
import socket
import struct
import subprocess

from .util import normalize_mac

SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891B

VIRTUAL_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "tun", "tap", "sit",
                    "dummy", "ip6tnl", "gre", "wg", "zt", "tailscale", "lxc", "cni",
                    "flannel", "kube", "vnet")


def is_virtual(name):
    return name.startswith(VIRTUAL_PREFIXES)


def _ioctl_ipv4(name, req):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        res = fcntl.ioctl(s.fileno(), req, struct.pack("256s", name[:15].encode()))
        return socket.inet_ntoa(res[20:24])
    except OSError:
        return None
    finally:
        s.close()


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _which(*names):
    for n in names:
        for d in ("/sbin", "/usr/sbin", "/bin", "/usr/bin"):
            p = os.path.join(d, n)
            if os.access(p, os.X_OK):
                return p
    return None


def _addresses_from_ip():
    ip = _which("ip")
    if not ip:
        return None
    try:
        out = subprocess.run([ip, "-o", "-4", "addr", "show"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    result = []
    for line in out.splitlines():
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m:
            result.append((m.group(1).split("@")[0], m.group(2), int(m.group(3))))
    return result


def _addresses_from_ioctl():
    result = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []
    for name in names:
        addr = _ioctl_ipv4(name, SIOCGIFADDR)
        mask = _ioctl_ipv4(name, SIOCGIFNETMASK)
        if addr and mask:
            prefix = ipaddress.IPv4Network("0.0.0.0/%s" % mask).prefixlen
            result.append((name, addr, prefix))
    return result


def interfaces(include_virtual=True):
    """List IPv4 interfaces: name, ip, prefix, network, mac, up, virtual."""
    addrs = _addresses_from_ip()
    if addrs is None:
        addrs = _addresses_from_ioctl()
    result = []
    for name, addr, prefix in addrs:
        virtual = is_virtual(name)
        if virtual and not include_virtual:
            continue
        net = ipaddress.IPv4Interface("%s/%d" % (addr, prefix)).network
        oper = _read("/sys/class/net/%s/operstate" % name)
        speed = _read("/sys/class/net/%s/speed" % name)
        up = oper in ("up", "unknown", "")
        try:
            speed = int(speed)
        except ValueError:
            speed = 0
        # the kernel reports -1 or 65535 (SPEED_UNKNOWN) for links without carrier
        speed = speed if up and 0 < speed < 65535 else None
        result.append({
            "name": name,
            "ip": addr,
            "prefix": prefix,
            "network": str(net),
            "mac": normalize_mac(_read("/sys/class/net/%s/address" % name)),
            "up": up,
            "speed": speed,
            "virtual": virtual or name == "lo" or addr.startswith("127."),
        })
    return result


def default_gateways():
    """Map interface -> default gateway IP from /proc/net/route."""
    gws = {}
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 4 and p[1] == "00000000" and int(p[3], 16) & 2:
                    gws[p[0]] = socket.inet_ntoa(struct.pack("<L", int(p[2], 16)))
    except (OSError, StopIteration, ValueError):
        pass
    return gws


def dns_servers():
    servers = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2 and p[0] == "nameserver":
                    servers.append(p[1])
    except OSError:
        pass
    return servers


def arp_table():
    """Return {ip: (mac, device)} for complete entries of the kernel ARP cache."""
    table = {}
    try:
        with open("/proc/net/arp") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) < 6:
                    continue
                flags = int(p[2], 16)
                mac = normalize_mac(p[3])
                if flags & 0x2 and mac:
                    table[p[0]] = (mac, p[5])
    except (OSError, StopIteration, ValueError):
        pass
    return table


def hostname():
    return socket.gethostname()


def _ipv6_prefixes():
    """(network, interface) for the global IPv6 addresses of this host (from /proc/net/if_inet6)."""
    out = []
    try:
        with open("/proc/net/if_inet6") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                addr = ipaddress.IPv6Address(int(parts[0], 16))
                plen = int(parts[2], 16)
                if addr.is_loopback or addr.is_link_local or plen >= 128:
                    continue
                out.append((ipaddress.IPv6Network("%s/%d" % (addr, plen), strict=False), parts[5]))
    except (OSError, ValueError):
        pass
    return out


def client_location(remote_addr):
    """Is a browser at `remote_addr` in one of the NAS's own networks?

    Returns {"ip", "local": True/False/None, "via"}. QuickConnect relays arrive through a local
    tunnel (loopback), DDNS/port forwarding from public addresses: both are remote. A browser in
    the LAN connects from an address inside an interface network, even when it uses a
    QuickConnect or DDNS host name that resolves to the NAS's LAN address.
    """
    try:
        ip = ipaddress.ip_address((remote_addr or "").split("%")[0])
    except ValueError:
        return {"ip": remote_addr or "", "local": None, "via": "unknown"}
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return {"ip": str(ip), "local": False, "via": "relay"}
    if ip.version == 4:
        for i in interfaces():
            if not i["virtual"] and ip in ipaddress.IPv4Network(i["network"]):
                return {"ip": str(ip), "local": True, "via": i["name"]}
    else:
        if ip.is_link_local:
            return {"ip": str(ip), "local": True, "via": "link-local"}
        for net, name in _ipv6_prefixes():
            if not is_virtual(name) and ip in net:
                return {"ip": str(ip), "local": True, "via": name}
    return {"ip": str(ip), "local": False, "via": "remote"}
