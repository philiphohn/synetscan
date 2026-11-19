"""MAC vendor lookup backed by a gzip'd prefix table (see tools/build_oui.py)."""
import gzip
import os
import threading

from .util import normalize_mac

_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "share", "oui.txt.gz")


class OuiDB:
    def __init__(self, path=None):
        self.path = os.path.abspath(path or _DEFAULT)
        self._tables = None
        self._lock = threading.Lock()

    def _load(self):
        tables = {}
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as f:
                for line in f:
                    prefix, _, vendor = line.rstrip("\n").partition("\t")
                    hexp, _, bits = prefix.partition("/")
                    tables.setdefault(int(bits or 24), {})[hexp] = vendor
        except OSError:
            pass
        # longest prefix first
        self._tables = sorted(tables.items(), key=lambda kv: -kv[0])

    def lookup(self, mac):
        mac = normalize_mac(mac)
        if not mac:
            return ""
        with self._lock:
            if self._tables is None:
                self._load()
        hexs = mac.replace(":", "").upper()
        for bits, table in self._tables:
            vendor = table.get(hexs[: bits // 4])
            if vendor:
                return _pretty(vendor)
        return ""


def _pretty(vendor):
    """The registry has some all-lowercase names ("zte"): show them like the others."""
    if vendor != vendor.lower():
        return vendor
    return " ".join(w.upper() if len(w) <= 4 else w.capitalize() for w in vendor.split())


_db = None


def lookup(mac):
    global _db
    if _db is None:
        _db = OuiDB()
    return _db.lookup(mac)
