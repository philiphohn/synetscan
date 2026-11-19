#!/usr/bin/env python3
"""Convert Wireshark's `manuf` file into SynetScan's compact OUI database.

Output format (gzip, one entry per line):  <hex prefix>/<bits>\t<vendor>
"""
import gzip
import re
import sys

SUFFIXES = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|ltd|limited|llc|gmbh|ag|"
    r"s\.?a|b\.?v|oy|ab|plc|pty|s\.?r\.?l|kg|co\.?,?\s*ltd)\.?$",
    re.I,
)


def clean(name):
    name = name.strip().strip('"')
    for _ in range(3):
        new = SUFFIXES.sub("", name).strip().rstrip(",")
        if new == name:
            break
        name = new
    return name


def main(src, dst):
    count = 0
    with open(src, encoding="utf-8", errors="replace") as f, \
            gzip.open(dst, "wt", encoding="utf-8", compresslevel=9) as out:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            prefix = parts[0].strip()
            vendor = clean(parts[2] if len(parts) > 2 and parts[2].strip() else parts[1])
            bits = 24
            if "/" in prefix:
                prefix, b = prefix.split("/")
                bits = int(b)
            hexp = prefix.replace(":", "").replace("-", "").upper()
            hexp = hexp[: bits // 4]
            if not hexp or not vendor:
                continue
            out.write("%s/%d\t%s\n" % (hexp, bits, vendor))
            count += 1
    print("wrote %d entries to %s" % (count, dst))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
