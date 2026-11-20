"""Minimal DNS message encoder/decoder (enough for mDNS / DNS-SD)."""
import socket
import struct

T_A, T_PTR, T_TXT, T_AAAA, T_SRV, T_ANY = 1, 12, 16, 28, 33, 255


def encode_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")[:63]
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def build_query(questions, txid=0, unicast_response=True):
    """questions: list of (name, qtype)."""
    msg = struct.pack("!HHHHHH", txid, 0, len(questions), 0, 0, 0)
    qclass = 0x8001 if unicast_response else 0x0001
    for name, qtype in questions:
        msg += encode_name(name) + struct.pack("!HH", qtype, qclass)
    return msg


def _read_name(data, offset, depth=0):
    labels = []
    jumped = False
    end = offset
    size = 0
    while True:
        if offset >= len(data) or depth > 20:
            raise ValueError("bad name")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            ptr = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            if not jumped:
                end = offset + 2
            jumped = True
            offset = ptr
            depth += 1
            continue
        if length == 0:
            if not jumped:
                end = offset + 1
            break
        # RFC 1035 limits: 63 bytes per label, 255 per name. Without them a name built from
        # compression pointers could be made to expand to many times the size of its packet.
        size += 1 + length
        if length > 63 or size > 255:
            raise ValueError("bad name")
        labels.append(data[offset + 1:offset + 1 + length].decode("utf-8", "replace"))
        offset += 1 + length
    return ".".join(labels), end


def parse_message(data):
    """Return dict with id, flags and a flat list of all resource records."""
    if len(data) < 12:
        raise ValueError("short message")
    txid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
    off = 12
    for _ in range(qd):
        _, off = _read_name(data, off)
        off += 4
    records = []
    for _ in range(an + ns + ar):
        name, off = _read_name(data, off)
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        rec = {"name": name, "type": rtype, "ttl": ttl}
        try:
            if rtype == T_A and rdlen == 4:
                rec["value"] = socket.inet_ntoa(rdata)
            elif rtype == T_AAAA and rdlen == 16:
                rec["value"] = socket.inet_ntop(socket.AF_INET6, rdata)
            elif rtype == T_PTR:
                rec["value"] = _read_name(data, off)[0]
            elif rtype == T_SRV:
                prio, weight, port = struct.unpack("!HHH", rdata[:6])
                rec["value"] = {"port": port, "target": _read_name(data, off + 6)[0]}
            elif rtype == T_TXT:
                items, i = {}, 0
                while i < len(rdata):
                    ln = rdata[i]
                    entry = rdata[i + 1:i + 1 + ln].decode("utf-8", "replace")
                    k, _, v = entry.partition("=")
                    if k:
                        items[k.lower()] = v
                    i += 1 + ln
                rec["value"] = items
            else:
                rec["value"] = None
        except (ValueError, struct.error):
            rec["value"] = None
        records.append(rec)
        off += rdlen
    return {"id": txid, "flags": flags, "records": records}


def reverse_name(ip):
    return ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
