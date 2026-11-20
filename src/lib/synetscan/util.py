"""Small helpers shared by the daemon, scanner and CGI."""
import json
import logging
import os
import re
import tempfile
import time

log = logging.getLogger("synetscan")

# Characters that are invisible or reorder the text around them: control characters, bidi
# controls, zero-width space, word joiner, BOM, line/paragraph separators, private-use and
# tag characters, surrogates and non-characters. Names announced by devices on the network are
# shown in DSM (and may be read by tools and AI assistants working on that page); what the
# admin sees must be all there is. Zero-width (non-)joiners stay: several scripts and emoji
# need them.
_INVISIBLE = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u061c\u180b-\u180f\u200b\u200e\u200f\u2028-\u202e\u2060-\u206f"
    "\ufeff\ufff0-\ufffb\ufffe\uffff\ud800-\udfff\ue000-\uf8ff\U0001bca0-\U0001bca3"
    "\U0001d173-\U0001d17a\U000e0000-\U000e0fff\U000f0000-\U0010ffff]")
_LINE_BREAKS = re.compile("\r\n?|[\x0b\x0c\x85\u2028\u2029]")
_BLANKS = re.compile("[\t \xa0\u1680\u2000-\u200a\u202f\u205f\u3000]+")


def _clean_line(line):
    return _BLANKS.sub(" ", _INVISIBLE.sub("", line.replace("\t", " "))).strip()


def clean_text(value, limit=255, multiline=False):
    """Text from the network or a form, made safe to store, log and show: no control or
    invisible characters, runs of blanks collapsed, at most `limit` characters. Line breaks
    become blanks unless `multiline` is set."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = _LINE_BREAKS.sub("\n", value[:limit * 4 + 64])
    if multiline:
        return "\n".join(_clean_line(line) for line in value.split("\n")).strip("\n")[:limit].rstrip()
    return _clean_line(value.replace("\n", " "))[:limit].rstrip()


def now():
    return int(time.time())


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def error_text(exc):
    """An exception as one short line for the UI; the traceback belongs in the log."""
    return clean_text("%s: %s" % (type(exc).__name__, exc), 200)


def write_json(path, data, mode=0o600):
    """Atomically replace `path` with the JSON encoding of `data`. The files hold the network
    inventory and are private to the package user."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
            # on disk before the rename: after a power cut the file is the old or the new one,
            # never empty (an empty devices.json would make the next scan a new baseline)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _OneLine(logging.Filter):
    """Keeps a log record on one line: text from the network cannot forge log entries."""

    def filter(self, record):
        try:
            record.msg = clean_text(record.getMessage(), 2000)
            record.args = None
        except Exception:  # noqa: BLE001 - a broken message must not stop the service
            pass
        return True


def setup_logging(path=None, level=logging.INFO):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("synetscan")
    root.setLevel(level)
    root.handlers[:] = []
    handler = logging.StreamHandler()
    if path:
        from logging.handlers import RotatingFileHandler
        old = os.umask(0o077)  # the log names the devices on the network: package user only
        try:
            handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2)
        finally:
            os.umask(old)
        make_private(path, path + ".1", path + ".2")
    handler.setFormatter(fmt)
    handler.addFilter(_OneLine())
    root.addHandler(handler)
    return root


def make_private(*paths):
    """Files written by earlier versions were readable by every local user."""
    for path in paths:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


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
