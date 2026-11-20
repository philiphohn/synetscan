"""Configuration defaults and validation."""
import re

from .classify import DEFAULT_PORTS
from .targets import TargetError, parse_target
from .util import clean_text

DEFAULTS = {
    "auto_subnets": True,
    "excluded_interfaces": [],
    "custom_targets": [],
    "max_hosts_per_subnet": 1024,
    "schedule_enabled": True,
    "schedule_interval": 60,          # minutes
    "scan_on_start": True,
    "ports": DEFAULT_PORTS,
    "timeout": 0.6,                   # seconds per TCP probe
    "threads": 64,
    "use_ping": True,
    "use_dns": True,
    "use_netbios": True,
    "use_mdns": True,
    "use_ssdp": True,
    "use_http": True,
    "use_ipv6": True,                 # neighbour discovery, mDNS and SSDP over IPv6
    "offline_after_scans": 1,         # missed scans before a device is shown offline
    "forget_after_days": 0,           # 0 = never remove offline devices
}

INTERVALS = [5, 10, 15, 30, 60, 120, 240, 360, 720, 1440]
MAX_CUSTOM_TARGETS = 1024  # 1.1.2 had no limit; every scan stops at targets.MAX_TARGETS anyway
_IFACE = re.compile(r"^[A-Za-z0-9_.:@-]{1,15}$")


class ConfigError(ValueError):
    """Invalid setting. `field` and `value` let the UI show a translated message."""

    def __init__(self, message, field="", value=""):
        super().__init__(message)
        self.field = field
        self.value = clean_text(value, 64)


def merged(cfg):
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        out.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    return out


def _bool(v):
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


def _int(v, lo, hi, field):
    try:
        v = int(v)
    except (TypeError, ValueError, OverflowError):
        raise ConfigError("%s: not a number" % field, field, v)
    if not lo <= v <= hi:
        raise ConfigError("%s: must be between %d and %d" % (field, lo, hi), field, v)
    return v


def validate(update, current):
    """Validate a partial update and return the new full configuration."""
    cfg = merged(current)
    if not isinstance(update, dict):
        return cfg
    for key, value in update.items():
        if key not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[key], bool):
            cfg[key] = _bool(value)
        elif key == "schedule_interval":
            cfg[key] = _int(value, 5, 1440, key)
        elif key == "max_hosts_per_subnet":
            cfg[key] = _int(value, 16, 16384, key)
        elif key == "threads":
            cfg[key] = _int(value, 4, 256, key)
        elif key in ("offline_after_scans",):
            cfg[key] = _int(value, 1, 10, key)
        elif key == "forget_after_days":
            cfg[key] = _int(value, 0, 3650, key)
        elif key == "timeout":
            try:
                v = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ConfigError("timeout: not a number", "timeout", value)
            if not 0.1 <= v <= 5:
                raise ConfigError("timeout: must be between 0.1 and 5 seconds", "timeout", value)
            cfg[key] = round(v, 2)
        elif key == "ports":
            ports = value
            if isinstance(value, str):
                ports = [p for p in value.replace(",", " ").split() if p]
            if not isinstance(ports, list) or len(ports) > 4096:
                raise ConfigError("ports: not a list of ports", "ports", "")
            out = set()
            for p in ports:
                p = str(p)[:32]
                if "-" in p:
                    a, _, b = p.partition("-")
                    try:
                        a, b = _int(a, 1, 65535, "ports"), _int(b, 1, 65535, "ports")
                    except ConfigError:
                        raise ConfigError("ports: invalid range %s" % p, "ports", p)
                    if b < a or b - a > 1024:
                        raise ConfigError("ports: invalid range %s" % p, "ports", p)
                    out.update(range(a, b + 1))
                else:
                    try:
                        out.add(_int(p, 1, 65535, "ports"))
                    except ConfigError:
                        raise ConfigError("ports: invalid port %s" % p, "ports", p)
            if len(out) > 2048:
                raise ConfigError("ports: at most 2048 ports", "ports", len(out))
            cfg[key] = sorted(out)
        elif key == "custom_targets":
            items = value
            if isinstance(value, str):
                items = value.replace(",", "\n").splitlines()
            if not isinstance(items, list):
                raise ConfigError("custom_targets: not a list", "custom_targets", "")
            clean = []
            for t in items:
                t = str(t).strip()[:80]
                if not t:
                    continue
                if len(clean) >= MAX_CUSTOM_TARGETS:
                    raise ConfigError("custom_targets: at most %d entries" % MAX_CUSTOM_TARGETS,
                                      "custom_targets_count", MAX_CUSTOM_TARGETS)
                try:
                    parse_target(t)
                except TargetError as e:
                    raise ConfigError("custom_targets: %s" % e, "custom_targets", t)
                clean.append(t)
            cfg[key] = clean
        elif key == "excluded_interfaces":
            # only ever compared with the names of the NAS's own interfaces
            names = value if isinstance(value, list) else []
            cfg[key] = [x for x in names if isinstance(x, str) and _IFACE.match(x)][:64]
    return cfg
