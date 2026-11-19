"""Small helpers shared by the daemon, scanner and CGI."""
import json
import logging
import os
import tempfile
import time

log = logging.getLogger("synetscan")


def now():
    return int(time.time())


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data, mode=0o644):
    """Atomically replace `path` with the JSON encoding of `data`."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def setup_logging(path=None, level=logging.INFO):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("synetscan")
    root.setLevel(level)
    root.handlers[:] = []
    handler = logging.StreamHandler()
    if path:
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2)
    handler.setFormatter(fmt)
    root.addHandler(handler)
    return root


def raise_fd_limit(wanted=4096):
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(wanted, hard) if hard != resource.RLIM_INFINITY else wanted
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except (ImportError, ValueError, OSError):
        return 1024


def normalize_mac(mac):
    if not mac:
        return ""
    hexs = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(hexs) != 12 or hexs == "000000000000":
        return ""
    return ":".join(hexs[i:i + 2] for i in range(0, 12, 2))


def is_random_mac(mac):
    """Locally administered (e.g. privacy / randomised) MAC address."""
    mac = normalize_mac(mac)
    return bool(mac) and bool(int(mac[:2], 16) & 0x02)
