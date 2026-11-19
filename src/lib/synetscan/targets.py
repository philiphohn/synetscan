"""Turn configuration into a concrete list of IPv4 addresses to scan."""
import ipaddress
import re

MAX_TARGETS = 65536


class TargetError(ValueError):
    pass


def parse_target(text):
    """Parse one target: CIDR, single IP, `a.b.c.d-e.f.g.h` or `a.b.c.d-N`."""
    text = text.strip()
    if not text:
        return []
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s*-\s*(\d+(?:\.\d+\.\d+\.\d+)?)$", text)
    try:
        if m:
            start = ipaddress.IPv4Address(m.group(1))
            end_txt = m.group(2)
            if "." in end_txt:
                end = ipaddress.IPv4Address(end_txt)
            else:
                end = ipaddress.IPv4Address(int(start) & 0xFFFFFF00 | int(end_txt))
                if int(end_txt) > 255:
                    raise TargetError("invalid range end: %s" % end_txt)
            if end < start:
                raise TargetError("range end before start: %s" % text)
            if int(end) - int(start) >= MAX_TARGETS:
                raise TargetError("range too large: %s" % text)
            return [str(ipaddress.IPv4Address(i)) for i in range(int(start), int(end) + 1)]
        net = ipaddress.IPv4Network(text, strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as e:
        if isinstance(e, TargetError):
            raise
        raise TargetError("invalid target: %s" % text)
    if net.num_addresses > MAX_TARGETS:
        raise TargetError("network too large: %s" % text)
    if net.prefixlen >= 31:
        return [str(a) for a in net]
    return [str(a) for a in net.hosts()]


def clamp_network(ip, prefix, max_hosts):
    """Return the largest sub-network around `ip` with at most `max_hosts` hosts."""
    while prefix < 30 and (2 ** (32 - prefix) - 2) > max_hosts:
        prefix += 1
    return ipaddress.IPv4Interface("%s/%d" % (ip, prefix)).network


def build_targets(cfg, ifaces):
    """Return (ordered list of (ip, source)), list of human readable descriptions."""
    seen = {}
    descriptions = []
    if cfg.get("auto_subnets", True):
        excluded = set(cfg.get("excluded_interfaces", []))
        for iface in ifaces:
            if iface["virtual"] or not iface["up"] or iface["name"] in excluded:
                continue
            if iface["ip"].startswith("169.254."):
                continue
            net = clamp_network(iface["ip"], iface["prefix"], int(cfg.get("max_hosts_per_subnet", 1024)))
            descriptions.append("%s (%s)" % (net, iface["name"]))
            for a in (net.hosts() if net.prefixlen < 31 else net):
                seen.setdefault(str(a), iface["name"])
    for t in cfg.get("custom_targets", []):
        try:
            addrs = parse_target(t)
        except TargetError:
            continue
        if addrs:
            descriptions.append(t.strip())
        for a in addrs:
            seen.setdefault(a, "custom")
        if len(seen) > MAX_TARGETS:
            break
    items = sorted(seen.items(), key=lambda kv: int(ipaddress.IPv4Address(kv[0])))
    return items[:MAX_TARGETS], descriptions
