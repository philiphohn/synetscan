import json
import re
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "lib"))

from synetscan import classify, config, dnsmsg, oui, probes, targets  # noqa: E402
from synetscan.store import Store  # noqa: E402
from synetscan.util import is_random_mac, normalize_mac  # noqa: E402


class TargetTests(unittest.TestCase):
    def test_cidr(self):
        self.assertEqual(len(targets.parse_target("192.168.1.0/24")), 254)
        self.assertEqual(targets.parse_target("10.0.0.5"), ["10.0.0.5"])

    def test_ranges(self):
        self.assertEqual(targets.parse_target("10.0.0.1-3"), ["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        self.assertEqual(len(targets.parse_target("10.0.0.250-10.0.1.5")), 12)
        with self.assertRaises(targets.TargetError):
            targets.parse_target("10.0.0.9-3")
        with self.assertRaises(targets.TargetError):
            targets.parse_target("nonsense")
        with self.assertRaises(targets.TargetError):
            targets.parse_target("10.0.0.0/8")

    def test_clamp(self):
        net = targets.clamp_network("172.16.40.7", 16, 1024)
        self.assertEqual(str(net), "172.16.40.0/22")
        self.assertEqual(str(targets.clamp_network("192.168.1.7", 24, 1024)), "192.168.1.0/24")

    def test_build_targets_skips_virtual(self):
        ifaces = [
            {"name": "eth0", "ip": "192.168.1.10", "prefix": 24, "virtual": False, "up": True},
            {"name": "docker0", "ip": "172.17.0.1", "prefix": 16, "virtual": True, "up": True},
        ]
        items, desc = targets.build_targets({"auto_subnets": True, "custom_targets": ["10.1.1.1-2"]}, ifaces)
        ips = [ip for ip, _ in items]
        self.assertEqual(len(ips), 256)
        self.assertNotIn("172.17.0.2", ips)
        self.assertIn("10.1.1.2", ips)
        items, _ = targets.build_targets({"auto_subnets": True, "excluded_interfaces": ["eth0"]}, ifaces)
        self.assertEqual(items, [])


class ConfigTests(unittest.TestCase):
    def test_validate(self):
        cfg = config.validate({"ports": "22, 80 8000-8002", "custom_targets": "10.0.0.0/24\n\n",
                               "use_ping": "false", "schedule_interval": "30"}, {})
        self.assertEqual(cfg["ports"], [22, 80, 8000, 8001, 8002])
        self.assertEqual(cfg["custom_targets"], ["10.0.0.0/24"])
        self.assertFalse(cfg["use_ping"])
        self.assertEqual(cfg["schedule_interval"], 30)

    def test_invalid(self):
        for bad in ({"ports": "70000"}, {"custom_targets": "abc"}, {"timeout": 99}, {"threads": 1}):
            with self.assertRaises(config.ConfigError):
                config.validate(bad, {})

    def test_unknown_keys_ignored(self):
        self.assertNotIn("evil", config.validate({"evil": 1}, {}))


class MacTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_mac("00-11-32-AA-BB-CC"), "00:11:32:aa:bb:cc")
        self.assertEqual(normalize_mac("00:00:00:00:00:00"), "")
        self.assertTrue(is_random_mac("da:28:89:2d:cd:40"))
        self.assertFalse(is_random_mac("00:11:32:aa:bb:cc"))

    def test_oui(self):
        self.assertEqual(oui.lookup("00:11:32:01:02:03"), "Synology")
        self.assertIn("Raspberry", oui.lookup("b8:27:eb:00:00:01"))
        self.assertEqual(oui.lookup(""), "")


class DnsTests(unittest.TestCase):
    def test_roundtrip_query(self):
        q = dnsmsg.build_query([("_http._tcp.local", dnsmsg.T_PTR)], txid=7)
        self.assertEqual(struct.unpack("!H", q[:2])[0], 7)
        self.assertIn(b"\x05_http\x04_tcp\x05local\x00", q)

    def test_parse_response_with_compression(self):
        name = dnsmsg.encode_name("_ipp._tcp.local")
        hdr = struct.pack("!HHHHHH", 0, 0x8400, 0, 2, 0, 0)
        # PTR _ipp._tcp.local -> "Office Printer._ipp._tcp.local" (compressed suffix)
        inst = b"\x0eOffice Printer\xc0\x0c"
        rr1 = name + struct.pack("!HHIH", dnsmsg.T_PTR, 1, 120, len(inst)) + inst
        a_name = b"\x07printer\x05local\x00"
        rr2 = a_name + struct.pack("!HHIH", dnsmsg.T_A, 1, 120, 4) + bytes([192, 168, 1, 50])
        msg = dnsmsg.parse_message(hdr + rr1 + rr2)
        self.assertEqual(msg["records"][0]["value"], "Office Printer._ipp._tcp.local")
        self.assertEqual(msg["records"][1]["value"], "192.168.1.50")

    def test_reverse_name(self):
        self.assertEqual(dnsmsg.reverse_name("192.168.1.2"), "2.1.168.192.in-addr.arpa")


class NetbiosTests(unittest.TestCase):
    def test_parse(self):
        qname = probes._nb_encode("*")
        names = b""
        for nm, suffix, flags in (("DESKTOP-ABC", 0x00, 0x0400), ("WORKGROUP", 0x00, 0x8400), ("DESKTOP-ABC", 0x20, 0x0400)):
            names += nm.ljust(15).encode() + bytes([suffix]) + struct.pack("!H", flags)
        rdata = bytes([3]) + names + bytes.fromhex("001122334455")
        pkt = struct.pack("!HHHHHH", 1, 0x8400, 0, 1, 0, 0) + qname + struct.pack("!HHIH", 0x21, 1, 0, len(rdata)) + rdata
        r = probes.parse_netbios_status(pkt)
        self.assertEqual(r, {"name": "DESKTOP-ABC", "workgroup": "WORKGROUP", "mac": "00:11:22:33:44:55"})


class ClassifyTests(unittest.TestCase):
    def t(self, **dev):
        dev.setdefault("ip", "192.168.1.50")
        return classify.classify(dev, gateways={"192.168.1.1"}, own_ips={"192.168.1.10"})

    def test_types(self):
        self.assertEqual(self.t(ip="192.168.1.1"), "router")
        self.assertEqual(self.t(ip="192.168.1.10"), "nas")
        self.assertEqual(self.t(vendor="Synology"), "nas")
        self.assertEqual(self.t(ports=[80, 9100]), "printer")
        self.assertEqual(self.t(services=["_ipp._tcp"]), "printer")
        self.assertEqual(self.t(ports=[554, 80]), "camera")
        self.assertEqual(self.t(ports=[62078]), "phone")
        self.assertEqual(self.t(mdns_name="Johns-iPad.local"), "tablet")
        self.assertEqual(self.t(services=["_googlecast._tcp"]), "media")
        self.assertEqual(self.t(vendor="Sonos"), "speaker")
        self.assertEqual(self.t(vendor="Espressif"), "iot")
        self.assertEqual(self.t(ports=[3389, 445]), "computer")
        self.assertEqual(self.t(vendor="VMware"), "virtual")
        self.assertEqual(self.t(vendor="Ubiquiti"), "network")
        self.assertEqual(self.t(ports=[22, 80]), "server")
        self.assertEqual(self.t(), "unknown")
        self.assertEqual(self.t(http={"title": "FRITZ!Box 7590"}), "router")

    def test_telephony(self):
        """Phone systems, desk phones, DECT bases and VoIP adapters (1.1.9)."""
        self.assertEqual(self.t(vendor="Mitel", ports=[80, 443]), "voip")
        self.assertEqual(self.t(vendor="Xiamen Yealink Network Technology", ports=[80]), "voip")
        self.assertEqual(self.t(vendor="snom technology"), "voip")
        self.assertEqual(self.t(vendor="Poly"), "voip")
        self.assertEqual(self.t(vendor="Litton/Poly-Scientific"), "unknown")  # not Poly the phone maker
        self.assertEqual(self.t(vendor="ARMITEL"), "unknown")  # not Mitel
        self.assertEqual(self.t(vendor="Netrake an AudioCodes Company"), "voip")
        self.assertEqual(self.t(http={"title": "MiVoice Office 400"}, ports=[443]), "voip")
        self.assertEqual(self.t(http={"title": "FreePBX Administration"}, ports=[22, 80]), "voip")
        self.assertEqual(self.t(ports=[5060]), "voip")
        self.assertEqual(self.t(ports=[22, 80, 5061]), "voip")
        # routers and NAS with a SIP registrar stay what they are
        self.assertEqual(self.t(ip="192.168.1.1", ports=[53, 80, 5060]), "router")
        self.assertEqual(self.t(vendor="AVM GmbH", ports=[80, 443, 5060]), "router")
        self.assertEqual(self.t(http={"title": "FRITZ!Box 7590"}, ports=[80, 5060]), "router")
        self.assertEqual(self.t(ip="192.168.1.10", ports=[5000, 5060]), "nas")
        self.assertIn("voip", classify.TYPES)
        self.assertIn(5060, classify.DEFAULT_PORTS)
        self.assertIn(5061, classify.DEFAULT_PORTS)

    def test_display_name(self):
        self.assertEqual(classify.display_name({"name": "Mine", "hostname": "x"}), "Mine")
        self.assertEqual(classify.display_name({"hostname": "pc.fritz.box"}), "pc")
        self.assertEqual(classify.display_name({"ip": "1.2.3.4", "http": {"title": "Login"}}), "1.2.3.4")
        self.assertEqual(classify.display_name({"ip": "1.2.3.4", "http": {"title": "Pi-hole"}}), "Pi-hole")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)

    def scan(self, hosts, ts, ips=None):
        return self.store.merge_scan({"started": ts - 5, "finished": ts, "duration": 5, "targets": ["x"],
                                      "target_count": 10, "hosts": hosts,
                                      "_target_ips": ips or {h["ip"] for h in hosts} | {"10.0.0.2", "10.0.0.3"}})

    def test_lifecycle(self):
        a = {"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "type": "nas", "ports": [5000]}
        b = {"ip": "10.0.0.3", "mac": "aa:bb:cc:00:00:02", "type": "unknown", "ports": []}
        s = self.scan([a, b], 1000)
        self.assertEqual(s["new"], 0)  # the first scan's devices are the known baseline
        self.assertTrue(all(d["known"] for d in self.store.devices.values()))  # baseline
        s = self.scan([a], 2000)
        self.assertEqual(s["offline"], 1)
        self.assertFalse(self.store.devices[b["mac"]]["online"])
        c = {"ip": "10.0.0.9", "mac": "aa:bb:cc:00:00:03", "type": "phone", "ports": []}
        b2 = dict(b, ip="10.0.0.4")
        s = self.scan([a, b2, c], 3000)
        self.assertEqual((s["new"], s["online_again"], s["ip_changed"]), (1, 1, 1))
        self.assertFalse(self.store.devices[c["mac"]]["known"])
        self.assertEqual(self.store.devices[b["mac"]]["ip_history"], ["10.0.0.3"])
        kinds = [e["kind"] for e in self.store.events]
        self.assertEqual(kinds, ["baseline", "offline", "ip_changed", "online", "new"])
        # persisted
        again = Store(self.dir)
        self.assertEqual(len(again.devices), 3)
        csv = again.export_csv()
        self.assertIn("00:11:32:00:00:01", csv)

    def test_update_and_delete(self):
        self.scan([{"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "type": "nas", "ports": []}], 1000)
        did = "00:11:32:00:00:01"
        self.store.update_device(did, {"name": " NAS ", "type_user": "server", "notes": "n", "known": False})
        d = self.store.list_devices()[0]
        self.assertEqual((d["display_name"], d["type"], d["known"]), ("NAS", "server", False))
        self.store.update_device(did, {"type_user": "bogus"})
        self.assertEqual(self.store.list_devices()[0]["type"], "nas")
        self.assertEqual(self.store.delete_devices([did, "nope"]), 1)

    def test_rekey_ip_only_device(self):
        self.scan([{"ip": "10.0.0.2", "type": "unknown", "ports": []}], 1000)
        self.assertIn("ip:10.0.0.2", self.store.devices)
        self.scan([{"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "type": "nas", "ports": []}], 2000)
        self.assertEqual(list(self.store.devices), ["00:11:32:00:00:01"])


class FeedbackRound1Tests(unittest.TestCase):
    """Findings from the first test on a real DS220+ (DSM 7.4.1)."""

    def test_config_error_carries_field_and_value(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.validate({"custom_targets": "10.0.0.0/24\n999.1.1.1/40"}, {})
        self.assertEqual((cm.exception.field, cm.exception.value), ("custom_targets", "999.1.1.1/40"))
        with self.assertRaises(config.ConfigError) as cm:
            config.validate({"ports": "80, 70000"}, {})
        self.assertEqual((cm.exception.field, cm.exception.value), ("ports", "70000"))

    def test_junk_names_are_not_shown(self):
        for junk in ("Xq7PzK2mW9tBBB", "nearby-presence-nsd-0a1b2c3d", "0a1b2c3d-1234-abcd"):
            self.assertTrue(classify.junk_name(junk), junk)
        for good in ("MACBOOKPRO-1234", "Living Room", "Office-NAS"):
            self.assertFalse(classify.junk_name(good), good)
        dev = {"friendly": "Xq7PzK2mW9tBBB", "mdns_name": "Living-Room-Pad.local", "ip": "1.2.3.4"}
        self.assertEqual(classify.display_name(dev), "Living-Room-Pad")
        # Android's made-up host names, with or without a digit in them
        for junk in ("Android_ABCDEFGH", "Android_K7QX2M4P", "android-0a1b2c3d4e5f6789"):
            self.assertTrue(classify.junk_name(junk), junk)
        for good in ("Android_Tablet", "android-kitchen", "Android_TV"):
            self.assertFalse(classify.junk_name(good), good)
        phone = {"mdns_name": "Android_ABCDEFGH.local", "ip": "1.2.3.4", "random_mac": True}
        self.assertEqual(classify.display_name(phone), "1.2.3.4")
        self.assertEqual(classify.classify(phone), "phone")  # the name still tells the type
        gw = {"friendly": "UPNP IGD (ZTE ZTE H1600)", "model": "ZTE H1600", "gateway": True, "vendor": "ZTE"}
        self.assertEqual(classify.display_name(gw), "ZTE H1600")
        self.assertEqual(classify.join_model("ZTE", "ZTE H1600"), "ZTE H1600")

    def test_samsung_tv_is_media(self):
        tv = {"ip": "192.168.1.50", "mac": "e8:aa:cb:00:00:01", "vendor": "Samsung Electronics", "ports": []}
        self.assertEqual(classify.classify(tv), "media")
        self.assertEqual(classify.classify(dict(tv, ports=[8001, 8002])), "media")
        phone = dict(tv, mac="56:00:00:00:00:01", random_mac=True)
        self.assertEqual(classify.classify(phone), "phone")
        self.assertEqual(classify.classify({"ip": "1.1.1.9", "vendor": "Sonos, Inc.", "ports": [1400]}), "speaker")

    def test_lowercase_vendor_is_prettified(self):
        self.assertEqual(oui.lookup("28:77:77:00:00:01"), "ZTE")

    def test_baseline_devices_are_not_new_and_migration(self):
        d = tempfile.mkdtemp()
        st = Store(d)
        st.merge_scan({"started": 1, "finished": 100, "duration": 1, "targets": [], "target_count": 1,
                       "hosts": [{"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "type": "nas", "ports": []}]})
        self.assertTrue(st.devices["00:11:32:00:00:01"]["baseline"])
        # data written by 1.0.0: no baseline flags, old default ports
        del st.devices["00:11:32:00:00:01"]["baseline"]
        st.save_devices()
        st.config["ports"] = list(classify.OLD_DEFAULT_PORTS[0])
        st.save_config()
        st2 = Store(d)
        self.assertTrue(st2.devices["00:11:32:00:00:01"]["baseline"])
        self.assertEqual(st2.config["ports"], classify.DEFAULT_PORTS)
        # the defaults up to 1.1.8 gain the SIP ports; a list of one's own stays as it is
        for old, expected in ((list(reversed(classify.OLD_DEFAULT_PORTS[1])), classify.DEFAULT_PORTS),
                              ([443, 22, 80], [443, 22, 80])):
            st2.config["ports"] = list(old)
            st2.save_config()
            self.assertEqual(Store(d).config["ports"], expected)


class ClientLocationTests(unittest.TestCase):
    def test_relay_public_and_lan(self):
        from synetscan import netinfo
        orig = netinfo.interfaces
        netinfo.interfaces = lambda: [
            {"name": "eth0", "network": "192.168.1.0/24", "virtual": False, "up": True},
            {"name": "eth1", "network": "169.254.0.0/16", "virtual": False, "up": False},  # unplugged, APIPA
            {"name": "eth2", "network": "10.9.0.0/24", "virtual": False, "up": False},
            {"name": "tun1000", "network": "169.254.184.0/21", "virtual": True, "up": True},  # QuickConnect relay
            {"name": "docker0", "network": "172.17.0.0/16", "virtual": True, "up": True}]
        try:
            loc = netinfo.client_location
            self.assertEqual(loc("127.0.0.1")["via"], "relay")      # QuickConnect relay tunnel
            self.assertFalse(loc("127.0.0.1")["local"])
            self.assertFalse(loc("84.10.20.30")["local"])            # DDNS / port forwarding
            self.assertTrue(loc("192.168.1.100")["local"])           # browser in the LAN
            self.assertTrue(loc("::ffff:192.168.1.100")["local"])
            self.assertFalse(loc("172.17.0.5")["local"])             # docker bridge is not the LAN
            # DS220+ / DSM 7.4.1 over QuickConnect (round 3): relay tunnel, not the APIPA eth1
            self.assertEqual(loc("169.254.184.1"), {"ip": "169.254.184.1", "local": False, "via": "relay"})
            self.assertFalse(loc("169.254.10.10")["local"])
            self.assertFalse(loc("10.9.0.5")["local"])               # interface is down
            self.assertFalse(loc("fe80::1")["local"])
            self.assertIsNone(loc("")["local"])
        finally:
            netinfo.interfaces = orig

    def test_bogus_xserve_model(self):
        self.assertTrue(classify.bogus_model("Xserve", "Synology"))
        self.assertFalse(classify.bogus_model("Xserve", "Apple"))
        d = tempfile.mkdtemp()
        st = Store(d)
        host = {"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "vendor": "Synology", "type": "nas", "ports": [], "model": "Xserve"}
        st.merge_scan({"started": 1, "finished": 100, "duration": 1, "targets": [], "target_count": 1, "hosts": [host]})
        self.assertNotIn("model", st.devices["00:11:32:00:00:01"])


class IPv6Tests(unittest.TestCase):
    def test_parse_ip_neigh(self):
        from synetscan import ipv6
        text = """fe80::1 dev eth0 lladdr 3c:a6:2f:10:20:01 router REACHABLE
2001:db8::5 dev eth0 lladdr 64:4e:d7:00:00:61 STALE
fe80::9 dev eth0 FAILED
fe80::8 dev eth0 lladdr 64:4e:d7:00:00:62 INCOMPLETE
ff02::fb dev eth0 lladdr 33:33:00:00:00:fb NOARP"""
        n = ipv6.parse_neighbors(text)
        self.assertEqual([(x["ip"], x["mac"], x["router"]) for x in n],
                         [("fe80::1", "3c:a6:2f:10:20:01", True), ("2001:db8::5", "64:4e:d7:00:00:61", False)])

    def test_parse_netlink(self):
        import socket as so
        from synetscan import ipv6

        def neigh(ip, mac, state, flags=0):
            attrs = struct.pack("=HH", 20, 1) + so.inet_pton(so.AF_INET6, ip)
            attrs += struct.pack("=HH", 10, 2) + bytes.fromhex(mac.replace(":", "")) + b"\0\0"
            body = struct.pack("=BxxxiHBB", so.AF_INET6, 2, state, flags, 0) + attrs
            return struct.pack("=IHHII", 16 + len(body), 28, 2, 1, 0) + body
        data = neigh("fe80::1", "3c:a6:2f:10:20:01", 0x02, 0x80) + neigh("fe80::2", "3c:a6:2f:10:20:02", 0x20) \
            + struct.pack("=IHHII", 20, 3, 2, 1, 0) + b"\0" * 4
        entries, done = ipv6.parse_netlink_neighbors(data)
        self.assertTrue(done)
        self.assertEqual([(e["ip"], e["mac"], e["router"], e["ifindex"]) for e in entries],
                         [("fe80::1", "3c:a6:2f:10:20:01", True, 2)])

    def test_addresses(self):
        from synetscan import ipv6
        self.assertEqual(ipv6.eui64_link_local("00:11:32:10:20:10"), "fe80::211:32ff:fe10:2010")
        self.assertEqual([ipv6.kind(a) for a in ("fe80::1", "fd00::1", "2001:db8::1")], ["link", "ula", "global"])
        self.assertEqual(ipv6.sort_addresses(["fe80::1", "fd00::1", "2001:db8::1", "fd00::1"]),
                         ["2001:db8::1", "fd00::1", "fe80::1"])

    def test_aaaa_record(self):
        import socket as so
        q = dnsmsg.build_query([("host.local", dnsmsg.T_AAAA)], txid=1)
        name = b"\x04host\x05local\x00"
        rr = name + struct.pack("!HHIH", dnsmsg.T_AAAA, 1, 120, 16) + so.inet_pton(so.AF_INET6, "fd00::42")
        msg = struct.pack("!HHHHHH", 1, 0x8400, 0, 1, 0, 0) + rr
        recs = dnsmsg.parse_message(msg)["records"]
        self.assertEqual((recs[0]["type"], recs[0]["value"]), (dnsmsg.T_AAAA, "fd00::42"))
        self.assertTrue(q)

    def test_ipv6_only_device_lifecycle(self):
        d = tempfile.mkdtemp()
        st = Store(d)
        v4 = {"ip": "10.0.0.2", "mac": "00:11:32:00:00:01", "type": "nas", "ports": [], "ipv6": ["fd00::2"], "iface": "eth0"}
        v6 = {"ip": "", "mac": "64:4e:d7:00:00:61", "type": "printer", "ports": [80], "ipv6": ["fd00::61", "fe80::1"],
              "iface": "eth0", "via": ["ndp"]}
        scan = lambda hosts, ts, v6i=("eth0",): st.merge_scan({"started": ts, "finished": ts, "duration": 1, "targets": [],
                                                               "target_count": 1, "hosts": hosts, "_target_ips": {"10.0.0.2"},
                                                               "_v6_ifaces": set(v6i)})
        scan([v4, v6], 100)
        p = st.devices["64:4e:d7:00:00:61"]
        self.assertEqual((p.get("ip") or "", p["ipv6"][0]), ("", "fd00::61"))
        dev = [x for x in st.list_devices() if x["id"] == p["id"]][0]
        self.assertEqual((dev["address"], dev["display_name"]), ("fd00::61", "fd00::61"))
        # the dual-stack NAS seen only over IPv6 once: no "IP changed", IPv4 kept
        scan([dict(v4, ip=""), v6], 200)
        self.assertEqual(st.devices["00:11:32:00:00:01"]["ip"], "10.0.0.2")
        self.assertNotIn("ip_changed", [e["kind"] for e in st.events])
        # IPv6 not scanned on its interface: the printer is out of scope, stays online
        scan([v4], 300, v6i=())
        self.assertTrue(st.devices["64:4e:d7:00:00:61"]["online"])
        scan([v4], 400)
        self.assertFalse(st.devices["64:4e:d7:00:00:61"]["online"])
        self.assertIn("fd00::61", st.export_csv())


class FieldTestRound5Tests(unittest.TestCase):
    """Findings from the IPv6 tests on three NAS (1.1.0)."""

    def test_proxy_arp_split(self):
        from synetscan.scanner import split_proxy_arp
        r = "00:1d:aa:00:00:01"
        arp = {"192.168.50.1": (r, "eth0"), "192.168.50.198": (r, "eth0"), "192.168.50.202": (r, "eth0"),
               "192.168.50.12": ("34:5a:06:00:00:12", "eth0")}
        targets = set(arp)
        self.assertEqual(split_proxy_arp(arp, targets, {}, {"192.168.50.1"}),
                         {"192.168.50.198": r, "192.168.50.202": r})
        # without the gateway among them, the lowest address keeps the MAC
        no_gw = {k: v for k, v in arp.items() if k != "192.168.50.1"}
        self.assertEqual(sorted(split_proxy_arp(no_gw, set(no_gw), {}, set())), ["192.168.50.202"])

    def test_non_ipv6_and_stale_prefixes(self):
        from synetscan import ipv6
        self.assertEqual(ipv6.sort_addresses(["192.168.0.50", "fe80::1", "2001:db8::1"]), ["2001:db8::1", "fe80::1"])
        addrs = ["2001:db8:1:61:1111:2222:3333:4444", "2001:db8:1:eb:5555:6666:7777:8888", "fe80::1234:5678:9abc:def0"]
        self.assertEqual(ipv6.on_link_filter(addrs, ["2001:db8:1:61:211:32ff:fe00:1/64"]),
                         ["2001:db8:1:61:1111:2222:3333:4444", "fe80::1234:5678:9abc:def0"])
        self.assertEqual(ipv6.on_link_filter(addrs, []), addrs)
        self.assertEqual(ipv6.sort_addresses(["2003::2", "2003::1"], deprecated={"2003::1"}), ["2003::2", "2003::1"])

    def test_names(self):
        from synetscan import scanner
        self.assertTrue(classify.junk_name("0"))
        self.assertFalse(classify.junk_name("pc"))
        self.assertEqual(scanner._RAOP_PREFIX.sub("", "0A1B2C3D4E5F@Living Room Mac"), "Living Room Mac")
        self.assertTrue(scanner._NUMBER_LIST.match("0,1,2"))

    def test_one_nas_entry(self):
        d = tempfile.mkdtemp()
        st = Store(d)
        a = {"ip": "192.168.50.10", "mac": "90:09:d0:00:00:11", "type": "nas", "ports": [], "self": True}
        b = {"ip": "192.168.100.10", "mac": "90:09:d0:00:00:12", "type": "nas", "ports": [], "self": True}
        res = lambda hosts, ts: {"started": ts, "finished": ts, "duration": 1, "targets": [], "target_count": 1, "hosts": hosts}
        st.merge_scan(res([a], 100))
        st.devices[b["mac"]] = dict(b, id=b["mac"], online=True, known=True)   # as 1.1.0 stored it
        self.assertEqual(len(st.devices), 2)
        st.merge_scan(res([dict(a, other_ips=["192.168.100.10 (eth1)"])], 200))
        self.assertEqual(list(st.devices), ["90:09:d0:00:00:11"])
        self.assertEqual(st.devices["90:09:d0:00:00:11"]["other_ips"], ["192.168.100.10 (eth1)"])


class Retest1111Tests(unittest.TestCase):
    """Findings from the 1.1.1 re-tests."""

    def test_proxy_owner_forgets_merged_clients(self):
        d = tempfile.mkdtemp()
        st = Store(d)
        r = "00:1d:aa:00:00:01"
        res = lambda hosts, ts: {"started": ts, "finished": ts, "duration": 1, "targets": [], "target_count": 1,
                                 "hosts": hosts, "trigger": "schedule"}
        # what 1.1.0 left behind: a VPN client's name and IPs merged into the router
        st.merge_scan(res([{"ip": "192.168.50.202", "mac": r, "type": "network", "ports": [5000],
                            "netbios": "MACBOOKPRO-1234", "http": {"title": "", "server": "AirTunes"}}], 100))
        st.devices[r]["ip_history"] = ["192.168.50.201", "192.168.50.1"]
        st.merge_scan(res([{"ip": "192.168.50.1", "mac": r, "type": "router", "ports": [80], "gateway": True,
                            "proxy_arp_for": ["192.168.50.201", "192.168.50.202"]},
                           {"ip": "192.168.50.202", "type": "computer", "ports": [], "netbios": "MACBOOKPRO-1234",
                            "proxy_arp": r}], 200))
        router = st.devices[r]
        self.assertNotIn("netbios", router)
        self.assertNotIn("http", router)
        self.assertEqual(router["ip_history"], ["192.168.50.1"])
        self.assertEqual(classify.display_name(router), "192.168.50.1")
        self.assertNotIn("ip_changed", [e["kind"] for e in st.events])
        self.assertEqual(st.devices["ip:192.168.50.202"]["netbios"], "MACBOOKPRO-1234")
        self.assertEqual(st.scans[-1]["trigger"], "schedule")
        self.assertEqual(Store(d).scans[-1]["trigger"], "schedule")    # persisted, not only in memory


class MdnsDevice:
    """A device answering DNS questions sent to it on 127.0.0.1: `records(name, qtype)` returns
    the resource records for one question."""

    def __init__(self, records):
        self.records, self.asked = records, []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(9000)
            except OSError:
                return
            txid, _, count = struct.unpack("!HHH", data[:6])
            off, rrs = 12, []
            for _ in range(count):
                name, off = dnsmsg._read_name(data, off)
                self.asked.append((name, struct.unpack("!H", data[off:off + 2])[0]))
                rrs += self.records(*self.asked[-1])
                off += 4
            if rrs:
                self.sock.sendto(struct.pack("!HHHHHH", txid, 0x8400, 0, len(rrs), 0, 0) + b"".join(rrs), addr)

    def close(self):
        self.sock.close()


def rr(name, rtype, value):
    if rtype == dnsmsg.T_PTR:
        data = dnsmsg.encode_name(value)
    elif rtype == dnsmsg.T_SRV:
        data = struct.pack("!HHH", 0, 0, 443) + dnsmsg.encode_name(value)
    else:
        data = socket.inet_pton(socket.AF_INET6 if rtype == dnsmsg.T_AAAA else socket.AF_INET, value)
    return dnsmsg.encode_name(name) + struct.pack("!HHIH", rtype, 1, 120, len(data)) + data


class ReviewTests(unittest.TestCase):
    """Found by reviewing 1.1.5 before its NAS test."""

    def test_the_schedule_survives_a_bad_interval_and_any_error(self):
        from synetscan import daemon
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        svc = daemon.Service(d)
        svc.store.config.update(schedule_enabled=True, schedule_interval="soon", scan_on_start=False)
        self.assertEqual(svc.next_scan_at(), svc.started_at + 3600)
        calls = []

        def broken():
            calls.append(1)
            if len(calls) == 2:
                svc.stop_event.set()
            raise IndexError("list index out of range")

        svc.next_scan_at = broken
        with mock.patch.object(svc.stop_event, "wait", side_effect=lambda t: svc.stop_event.is_set()):
            svc.scheduler()   # logs and carries on instead of ending the thread
        self.assertEqual(len(calls), 2)

    def test_state_files_reach_the_disk_before_they_replace_the_old_ones(self):
        from synetscan import util
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        synced = []
        real = os.fsync
        with mock.patch.object(os, "fsync", side_effect=lambda fd: synced.append(fd) or real(fd)):
            util.write_json(os.path.join(d, "devices.json"), {"a": 1})
        self.assertEqual(len(synced), 1)
        with open(os.path.join(d, "devices.json")) as f:
            self.assertEqual(json.load(f), {"a": 1})


class Retest114Tests(unittest.TestCase):
    """Findings from the 1.1.4 tests."""

    HOST, INSTANCE = "aabbcc000021.local", "Bridge - 000021._hue._tcp.local"
    V6 = ["2001:db8::21", "fe80::a8bb:ccff:fe00:21"]

    def bridge(self, deaf_for):
        """Answers like a Hue bridge, but ignores the first `deaf_for` questions for its type."""
        def records(name, qtype):
            if name == "_services._dns-sd._udp.local":
                return [rr(name, dnsmsg.T_PTR, "_hue._tcp.local")]
            if name != "_hue._tcp.local" or dev.asked.count((name, qtype)) <= deaf_for:
                return []
            return [rr(name, dnsmsg.T_PTR, self.INSTANCE), rr(self.INSTANCE, dnsmsg.T_SRV, self.HOST)] + \
                [rr(self.HOST, dnsmsg.T_AAAA, a) for a in self.V6]

        dev = MdnsDevice(records)
        self.addCleanup(dev.close)
        return dev

    def test_a_question_left_unanswered_is_asked_again(self):
        dev = self.bridge(deaf_for=1)
        self.assertEqual(probes.mdns_host("127.0.0.1", ["_hue._tcp"], 0.6, dev.port), (self.HOST, self.V6))
        self.assertEqual(dev.asked.count(("_hue._tcp.local", dnsmsg.T_PTR)), 2)

    def test_the_browse_asks_every_type_twice_and_gives_the_scan_its_head_start(self):
        dev = self.bridge(deaf_for=1)   # misses the first question for its type
        ready, seen = threading.Event(), []
        threading.Thread(target=lambda: seen.append(ready.wait(5) and time.monotonic()), daemon=True).start()
        start = time.monotonic()
        with mock.patch.object(probes, "MDNS_ADDR", ("127.0.0.1", dev.port)):
            found = probes.mdns_browse(None, duration=1.0, ready=ready)
        took = time.monotonic() - start
        self.assertEqual(found["127.0.0.1"]["hostname"], self.HOST)
        self.assertEqual(found["127.0.0.1"]["ipv6"], self.V6)
        self.assertEqual(dev.asked.count(("_hue._tcp.local", dnsmsg.T_PTR)), 2)
        time.sleep(0.05)
        self.assertTrue(0.3 < seen[0] - start < 0.6, seen[0] - start)   # set while the browse goes on
        self.assertLess(took, 1.3)

    def test_a_slow_device_still_gives_its_addresses(self):
        # each answer comes 0.9 s late, after the question was already sent again: the late
        # answer to the first sending must not cut short the wait for the next question
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        self.addCleanup(sock.close)
        asked = []

        def answer(data, addr):
            time.sleep(0.9)
            name, off = dnsmsg._read_name(data, 12)
            qtype = struct.unpack("!H", data[off:off + 2])[0]
            if name.endswith(".arpa"):
                rrs = [rr(name, dnsmsg.T_PTR, self.HOST)]
            elif (name, qtype) == (self.HOST, dnsmsg.T_AAAA):
                rrs = [rr(self.HOST, dnsmsg.T_AAAA, a) for a in self.V6]
            else:
                return
            try:
                sock.sendto(data[:2] + struct.pack("!HHHHH", 0x8400, 0, len(rrs), 0, 0) + b"".join(rrs), addr)
            except OSError:
                pass

        def serve():
            while True:
                try:
                    data, addr = sock.recvfrom(9000)
                except OSError:
                    return
                asked.append(data)
                threading.Thread(target=answer, args=(data, addr), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()
        self.assertEqual(probes.mdns_host("127.0.0.1", (), 1.5, sock.getsockname()[1]), (self.HOST, self.V6))
        self.assertEqual(len({d[:2] for d in asked}), len(asked))  # every sending has an ID of its own

    def test_a_device_whose_name_is_known_is_asked_for_its_addresses_only(self):
        dev = MdnsDevice(lambda name, qtype: [rr(self.HOST, dnsmsg.T_AAAA, a) for a in self.V6]
                         if (name, qtype) == (self.HOST, dnsmsg.T_AAAA) else [])
        self.addCleanup(dev.close)
        self.assertEqual(probes.mdns_host("127.0.0.1", ["_hue._tcp"], 0.6, dev.port, name=self.HOST + "."), (self.HOST, self.V6))
        self.assertEqual(dev.asked, [(self.HOST, dnsmsg.T_AAAA)])

    def test_the_head_start_ends_when_the_browse_fails(self):
        ready = threading.Event()
        with mock.patch.object(probes, "_open_mcast", return_value=[(None, None)]), self.assertRaises(AttributeError):
            probes.mdns_browse(None, duration=0.2, ready=ready)
        self.assertTrue(ready.is_set())


class Retest113Tests(unittest.TestCase):
    """Findings from the 1.1.3 tests."""

    HOST, INSTANCE = "aabbcc000021.local", "Bridge - 000021._hue._tcp.local"
    V6 = ["2001:db8::21", "fe80::a8bb:ccff:fe00:21"]

    def ask(self, records, services=("_hue._tcp",)):
        dev = MdnsDevice(records)
        self.addCleanup(dev.close)
        start = time.monotonic()
        result = probes.mdns_host("127.0.0.1", services, 0.4, dev.port)
        return result, dev.asked, time.monotonic() - start

    def addresses(self, name, qtype):
        return [rr(self.HOST, dnsmsg.T_AAAA, a) for a in self.V6] if (name, qtype) == (self.HOST, dnsmsg.T_AAAA) else []

    def test_device_asked_directly_answers_in_one_go(self):
        # as most devices answer a question for their service: with host name and addresses
        def records(name, qtype):
            if name != "_hue._tcp.local":
                return []
            return [rr(name, dnsmsg.T_PTR, self.INSTANCE), rr(self.INSTANCE, dnsmsg.T_SRV, self.HOST),
                    rr(self.HOST, dnsmsg.T_A, "127.0.0.1")] + self.addresses(self.HOST, dnsmsg.T_AAAA)

        result, asked, took = self.ask(records)
        self.assertEqual(result, (self.HOST, self.V6))
        self.assertEqual(asked, [("1.0.0.127.in-addr.arpa", dnsmsg.T_PTR), ("_hue._tcp.local", dnsmsg.T_PTR)])
        self.assertLess(took, 0.35)  # does not wait out the time once the answer is there

    def test_device_asked_directly_answers_step_by_step(self):
        # only what was asked, nothing along with it: type -> instance -> host name -> addresses
        def records(name, qtype):
            if (name, qtype) == ("_hue._tcp.local", dnsmsg.T_PTR):
                return [rr(name, dnsmsg.T_PTR, self.INSTANCE)]
            if (name, qtype) == (self.INSTANCE, dnsmsg.T_SRV):
                return [rr(name, dnsmsg.T_SRV, self.HOST)]
            return self.addresses(name, qtype)

        result, asked, _ = self.ask(records)
        self.assertEqual(result, (self.HOST, self.V6))
        self.assertEqual(asked[2:], [(self.INSTANCE, dnsmsg.T_SRV), (self.HOST, dnsmsg.T_AAAA)])

    def test_device_asked_directly_knows_its_name_only(self):
        def records(name, qtype):
            return [rr(name, dnsmsg.T_PTR, "Android_ABCDEFGH.local")] if name.endswith(".arpa") else []

        result, asked, _ = self.ask(records, ())
        self.assertEqual(result, ("Android_ABCDEFGH.local", []))
        self.assertEqual(asked, [("1.0.0.127.in-addr.arpa", dnsmsg.T_PTR)] + [("Android_ABCDEFGH.local", dnsmsg.T_AAAA)] * 2)

    def test_device_asked_directly_stays_silent(self):
        result, asked, took = self.ask(lambda name, qtype: [])
        self.assertEqual(result, ("", []))
        self.assertEqual(len(asked), 4)   # asked twice, then given up
        self.assertLess(took, 0.8)
        gone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        gone.bind(("127.0.0.1", 0))
        port = gone.getsockname()[1]
        gone.close()
        self.assertEqual(probes.mdns_host("127.0.0.1", ["_hue._tcp"], 0.4, port), ("", []))

    def test_answers_of_another_sender_are_not_read(self):
        dev = MdnsDevice(lambda name, qtype: [])
        self.addCleanup(dev.close)
        other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        other.bind(("127.0.0.2", 0))
        self.addCleanup(other.close)
        seen = []

        def collect(sock, duration, handler, quiet=None):
            # the moment the question is out, another machine answers it
            seen.append(sock.getsockname())
            other.sendto(struct.pack("!HHHHHH", 0x2B2B, 0x8400, 0, 1, 0, 0) +
                         rr("1.0.0.127.in-addr.arpa", dnsmsg.T_PTR, "nas.local"), sock.getsockname())
            return real(sock, duration, handler, quiet)

        real = probes._collect
        with mock.patch.object(probes, "_collect", collect):
            self.assertEqual(probes.mdns_host("127.0.0.1", (), 0.3, dev.port), ("", []))
        self.assertEqual(len(seen), 2)  # the other machine's answer counts for nothing: asked again

    def test_every_upnp_stack_of_a_device_is_kept(self):
        # a router whose provider agent answers before its gateway service
        def answer(server, location, st):
            return ("HTTP/1.1 200 OK\r\nSERVER: %s\r\nLOCATION: %s\r\nST: %s\r\n\r\n" % (server, location, st)).encode()

        agent, igd = "http://192.168.50.1:40001/agent.xml", "http://192.168.50.1:5000/rootDesc.xml"
        datagrams = [(answer("Linux UPnP/1.1 Agent/3.4", agent, "upnp:rootdevice"), ("192.168.50.1", 1900)),
                     (answer("Linux UPnP/1.1 Agent/3.4", agent, "uuid:1"), ("192.168.50.1", 1900)),
                     (answer("Linux UPnP/1.1 MiniUPnPd/1.8", igd, "upnp:rootdevice"), ("192.168.50.1", 1900))]
        datagrams += [(answer("x", "http://192.168.50.9/%d.xml" % i, "upnp:rootdevice"), ("192.168.50.9", 1900))
                      for i in range(10)]

        def collect(sock, duration, handler, quiet=None):
            for data, addr in datagrams:
                handler(data, addr)

        with mock.patch.object(probes, "_open_mcast", lambda *a: [(mock.Mock(), None)]), \
                mock.patch.object(probes, "_collect", collect):
            found = probes.ssdp_discover(["192.168.50.2"])
        self.assertEqual(found["192.168.50.1"]["locations"], [agent, igd])
        self.assertEqual(found["192.168.50.1"]["server"], "Linux UPnP/1.1 Agent/3.4")
        self.assertEqual(len(found["192.168.50.9"]["locations"]), probes.MAX_LOCATIONS)


class Retest115Tests(unittest.TestCase):
    """Findings from the 1.1.5 tests and the older minor issues, fixed in 1.1.8 (1.1.6 and 1.1.7 were test builds only)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = Store(self.dir)

    def scan(self, hosts, ts):
        for h in hosts:
            h.setdefault("type", classify.classify(h))
        return self.store.merge_scan({"started": ts - 5, "finished": ts, "duration": 5, "targets": ["x"],
                                      "target_count": 10, "hosts": hosts,
                                      "_target_ips": {h["ip"] for h in hosts}})

    MAC = "3c:22:fb:00:00:42"

    def awake(self):
        return {"ip": "192.168.50.42", "mac": self.MAC, "vendor": "Apple", "ports": [], "mdns_name": "office.local",
                "model": "iMac19,2", "services": ["_companion-link._tcp"], "friendly": "Office"}

    def test_a_sleeping_mac_stays_a_computer(self):
        self.scan([self.awake()], 1000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "computer")
        asleep = {"ip": "192.168.50.42", "mac": self.MAC, "vendor": "Apple", "ports": []}
        self.assertEqual(classify.classify(asleep), "phone")  # what the scan alone says
        self.scan([asleep], 2000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "computer")
        # the router still knows its DNS name while it sleeps
        self.scan([dict(asleep, hostname="office-desk")], 3000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "computer")

    def test_a_device_that_answers_fully_keeps_the_type_of_its_scan(self):
        for host in ({"ip": "192.168.50.2", "mac": "00:11:32:00:00:02", "vendor": "Synology", "ports": [5000, 5001]},
                     {"ip": "192.168.50.3", "mac": "aa:bb:cc:00:00:03", "ports": [9100], "model": "Laser"},
                     {"ip": "192.168.50.4", "mac": "aa:bb:cc:00:00:04", "ports": [], "hostname": "pixel-7"}):
            self.scan([dict(host)], 1000)
            self.assertEqual(self.store.devices[host["mac"]]["type_auto"], classify.classify(host))

    def test_unknown_from_the_record_never_overrules_the_scan(self):
        # a scan may have seen something the record does not keep
        self.scan([{"ip": "192.168.50.5", "mac": "aa:bb:cc:00:00:05", "ports": [], "type": "camera"}], 1000)
        self.assertEqual(self.store.devices["aa:bb:cc:00:00:05"]["type_auto"], "camera")
        self.scan([{"ip": "192.168.50.6", "mac": "aa:bb:cc:00:00:06", "ports": [], "type": "<x>"}], 1000)
        self.assertEqual(self.store.devices["aa:bb:cc:00:00:06"]["type_auto"], "unknown")

    def test_odd_stored_data_never_costs_the_scan(self):
        self.scan([self.awake()], 1000)
        self.store.devices[self.MAC]["type_shown"] = "<x>"  # what no version writes, but a damaged file might hold
        self.scan([{"ip": "192.168.50.42", "mac": self.MAC, "vendor": "Apple", "ports": [], "type": "phone"}], 2000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "phone")

    def test_a_dns_name_that_tells_the_type_lets_the_scan_decide(self):
        mac = "8c:79:f5:00:00:71"
        self.scan([{"ip": "192.168.50.71", "mac": mac, "vendor": "Samsung Electronics", "ports": [],
                    "ssdp_server": "Linux UPnP/1.0"}], 1000)
        self.assertEqual(self.store.devices[mac]["type_auto"], "media")
        self.scan([{"ip": "192.168.50.71", "mac": mac, "vendor": "Samsung Electronics", "ports": [],
                    "hostname": "galaxy-s21"}], 2000)
        self.assertEqual(self.store.devices[mac]["type_auto"], "phone")

    def test_shared_macs_and_the_gateway_follow_the_scan(self):
        mac = "aa:bb:cc:00:00:72"
        for extra, scanned in (({"proxy_arp_for": ["192.168.50.73"]}, "unknown"), ({"gateway": True}, "router")):
            self.scan([{"ip": "192.168.50.72", "mac": mac, "ports": [631], "services": ["_ipp._tcp"]}], 1000)
            self.assertEqual(self.store.devices[mac]["type_auto"], "printer")
            self.scan([dict({"ip": "192.168.50.72", "mac": mac, "ports": [], "type": scanned}, **extra)], 2000)
            self.assertEqual(self.store.devices[mac]["type_auto"], scanned)

    def test_a_record_from_an_older_version_follows_the_scan_until_the_device_shows_itself(self):
        self.scan([self.awake()], 1000)
        del self.store.devices[self.MAC]["type_shown"]  # as 1.1.5 left it
        asleep = {"ip": "192.168.50.42", "mac": self.MAC, "vendor": "Apple", "ports": [], "via": ["arp", "tcp"]}
        self.scan([dict(asleep)], 2000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "phone")  # as 1.1.5
        self.scan([self.awake()], 3000)
        self.scan([dict(asleep)], 4000)
        self.assertEqual(self.store.devices[self.MAC]["type_auto"], "computer")

    def test_a_device_that_answers_bonjour_or_ssdp_is_not_silent(self):
        self.scan([self.awake()], 1000)
        for extra in ({"via": ["arp", "mdns"]}, {"via": ["arp", "ssdp"], "ssdp_server": "Linux UPnP/1.0"}):
            self.scan([dict({"ip": "192.168.50.42", "mac": self.MAC, "vendor": "Apple", "ports": [], "type": "phone"}, **extra)], 2000)
            self.assertEqual(self.store.devices[self.MAC]["type_auto"], "phone")
            self.scan([self.awake()], 3000)

    def test_the_gateway_and_the_nas_keep_their_type(self):
        self.scan([{"ip": "192.168.50.1", "mac": "aa:bb:cc:00:00:01", "ports": [], "gateway": True, "type": "router"},
                   {"ip": "192.168.50.10", "mac": "aa:bb:cc:00:00:10", "ports": [], "self": True, "type": "nas"}], 1000)
        self.assertEqual(self.store.devices["aa:bb:cc:00:00:01"]["type_auto"], "router")
        self.assertEqual(self.store.devices["aa:bb:cc:00:00:10"]["type_auto"], "nas")

    def test_the_first_scan_counts_no_new_devices(self):
        s = self.scan([self.awake(), {"ip": "192.168.50.7", "mac": "aa:bb:cc:00:00:07", "ports": []}], 1000)
        self.assertEqual((s["new"], s["online_again"]), (0, 0))
        self.assertEqual([e["kind"] for e in self.store.events], ["baseline"])
        s = self.scan([self.awake(), {"ip": "192.168.50.8", "mac": "aa:bb:cc:00:00:08", "ports": []}], 2000)
        self.assertEqual(s["new"], 1)
        self.assertEqual([e["kind"] for e in self.store.events][-1], "new")

    def test_new_in_24_hours_is_what_the_tile_counts_and_the_filter_shows(self):
        with mock.patch("synetscan.store.now", return_value=1000):
            self.scan([self.awake()], 1000)  # the first scan: baseline
        with mock.patch("synetscan.store.now", return_value=2000):
            self.scan([{"ip": "192.168.50.8", "mac": "aa:bb:cc:00:00:08", "ports": []}], 2000)
        with mock.patch("synetscan.store.now", return_value=2000 + 86400 - 1):
            flags = {d["id"]: d["new24h"] for d in self.store.list_devices()}
        self.assertEqual(flags, {self.MAC: False, "aa:bb:cc:00:00:08": True})
        with mock.patch("synetscan.store.now", return_value=2000 + 86400 + 1):
            self.assertFalse(any(d["new24h"] for d in self.store.list_devices()))

    def test_the_scan_decides_whenever_the_device_showed_something(self):
        # a PC that once shared a printer (_ipp) and now shows only its ports: the scan decides
        mac = "aa:bb:cc:00:00:09"
        self.scan([{"ip": "192.168.50.9", "mac": mac, "ports": [631], "services": ["_ipp._tcp"]}], 1000)
        self.assertEqual(self.store.devices[mac]["type_auto"], "printer")
        self.scan([{"ip": "192.168.50.9", "mac": mac, "ports": [3389, 445]}], 2000)
        self.assertEqual(self.store.devices[mac]["type_auto"], "computer")

    def test_an_address_without_mac_taken_over_by_another_device(self):
        # routed networks: records are kept by address, and the address may go to another device
        self.scan([{"ip": "10.1.0.50", "ports": [9100, 80], "http": {"title": "HP LaserJet"}}], 1000)
        self.assertEqual(self.store.devices["ip:10.1.0.50"]["type_auto"], "printer")
        self.scan([{"ip": "10.1.0.50", "ports": [3389, 445], "netbios": "DESKTOP-ABC"}], 2000)
        self.assertEqual(self.store.devices["ip:10.1.0.50"]["type_auto"], "computer")
        self.scan([{"ip": "10.1.0.50", "ports": [], "type": "phone"}], 3000)  # silent, no MAC: still the scan
        self.assertEqual(self.store.devices["ip:10.1.0.50"]["type_auto"], "phone")

    def test_a_record_taken_over_by_a_mac_follows_the_scan(self):
        self.scan([{"ip": "10.1.0.60", "ports": [554], "friendly": "Garage camera"}], 1000)
        self.assertEqual(self.store.devices["ip:10.1.0.60"]["type_auto"], "camera")
        # a phone with a private MAC gets the address and shows nothing: the old record is not its own
        for ts in (2000, 3000, 4000):
            self.scan([{"ip": "10.1.0.60", "mac": "da:00:00:00:00:60", "random_mac": True, "ports": []}], ts)
            self.assertEqual(self.store.devices["da:00:00:00:00:60"]["type_auto"], "phone")

    def test_a_split_off_record_taken_over_by_a_tv_follows_the_scan(self):
        # a VPN client's record (no MAC, kept by address) with a Mac's name; a TV gets the address
        self.scan([{"ip": "192.168.50.70", "ports": [], "mdns_name": "Annas-MacBook-Air.local"}], 1000)
        tv = {"ip": "192.168.50.70", "mac": "8c:79:f5:00:00:70", "vendor": "Samsung Electronics", "ports": []}
        for ts in (2000, 3000):
            self.scan([dict(tv)], ts)
            self.assertEqual(self.store.devices[tv["mac"]]["type_auto"], "media")
        # once the TV shows itself, its own type is what a silent scan falls back to
        self.scan([dict(tv, ports=[8001, 8002], services=["_samsungmsf._tcp"])], 4000)
        self.scan([dict(tv)], 5000)
        self.assertEqual(self.store.devices[tv["mac"]]["type_auto"], "media")

    def test_a_damaged_first_seen_does_not_break_the_list(self):
        self.scan([self.awake()], 1000)
        self.store.devices[self.MAC]["first_seen"] = "yesterday"
        self.assertFalse(self.store.list_devices()[0]["new24h"])
        del self.store.devices[self.MAC]["first_seen"]
        self.assertFalse(self.store.list_devices()[0]["new24h"])

class PackageCenterTests(unittest.TestCase):
    """What Synology's package review asks for (developer guide, Appendix C), since 1.1.8."""

    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    def service(self, scans=None):
        from synetscan import daemon
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        if scans is not None:
            with open(os.path.join(d, "scans.json"), "w") as f:
                json.dump(scans, f)
        svc = daemon.Service(d)
        svc.started = []
        svc.start_scan = lambda trigger="manual": svc.started.append(trigger) or True
        return svc

    def run_scheduler(self, svc, rounds=3):
        svc.next_scan_at = lambda: 0  # always due
        waits = []

        def wait(t):
            waits.append(t)
            return len(waits) > rounds
        with mock.patch.object(svc.stop_event, "wait", side_effect=wait):
            svc.scheduler()

    def test_a_fresh_installation_scans_nothing_until_the_app_is_opened(self):
        svc = self.service()
        svc.store.config.update(schedule_enabled=True, scan_on_start=True)
        self.assertTrue(svc.api_status({}, "")["awaiting_open"])
        self.run_scheduler(svc)
        self.assertEqual(svc.started, [])   # neither the start-up scan nor the schedule
        st = svc.api_opened({}, "admin")
        self.assertEqual(svc.started, ["open"])
        self.assertFalse(svc.awaiting_open)
        self.assertFalse(st["awaiting_open"])
        svc.api_opened({}, "admin")          # every later opening changes nothing
        self.assertEqual(svc.started, ["open"])
        svc.store.config["scan_on_start"] = False  # only the loop: the start-up part runs once per service
        self.run_scheduler(svc)
        self.assertEqual(svc.started, ["open", "schedule", "schedule", "schedule"])

    def test_with_data_from_an_earlier_scan_the_service_starts_as_before(self):
        svc = self.service(scans=[{"started": 1, "finished": 2, "found": 1, "new": 0}])
        self.assertFalse(svc.awaiting_open)
        svc.store.config.update(scan_on_start=True)
        self.run_scheduler(svc, rounds=0)
        self.assertEqual(svc.started, ["startup"])
        svc.api_opened({}, "admin")
        self.assertEqual(svc.started, ["startup"])

    def test_emptied_or_damaged_data_keeps_the_schedule_running(self):
        from synetscan import daemon
        for name, content in (("scans.json", "[]"), ("devices.json", "not json"), ("config.json", "{}")):
            d = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, d, True)
            with open(os.path.join(d, name), "w") as f:
                f.write(content)
            self.assertFalse(daemon.Service(d).awaiting_open, name)
        svc = self.service(scans=[{"started": 1, "finished": 2}])
        svc.store.reset()                    # Delete All Data, then the NAS restarts
        self.assertFalse(daemon.Service(svc.var_dir).awaiting_open)

    def test_uninstalling_with_the_data_makes_the_next_installation_wait_again(self):
        var, link = self.data_dir()
        self.postuninst(link, "UNINSTALL", "true")
        from synetscan import daemon
        self.assertTrue(daemon.Service(var).awaiting_open)

    def test_scan_on_start_off_is_respected_and_the_schedule_counts_from_the_opening(self):
        svc = self.service()
        svc.store.config.update(scan_on_start=False, schedule_enabled=True)
        svc.started_at -= 86400
        svc.api_opened({}, "admin")
        self.assertEqual(svc.started, [])
        self.assertFalse(svc.awaiting_open)
        self.assertGreater(svc.next_scan_at(), time.time() + 3000)

    def test_a_manual_scan_ends_the_waiting_too(self):
        from synetscan import daemon
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        svc = daemon.Service(d)
        with mock.patch.object(svc, "_scan"):
            self.assertTrue(svc.api_scan({}, "admin")["started"])
            svc.scan_thread.join()
        self.assertFalse(svc.awaiting_open)

    def test_opened_needs_a_post(self):
        from synetscan import cgi_main
        self.assertIn("opened", cgi_main.ACTIONS)
        self.assertNotIn("opened", cgi_main.READ_ACTIONS)

    def info(self):
        with open(os.path.join(self.ROOT, "spk", "INFO.in"), encoding="utf-8") as f:
            return dict(re.findall(r'^(\w+)="(.*)"$', f.read(), re.M))

    def test_deleting_devices_or_data_is_logged(self):
        svc = self.service()
        svc.store.devices = {"a": {"id": "a", "online": True}, "b": {"id": "b", "online": False},
                             "c": {"id": "c", "online": False}}
        with self.assertLogs("synetscan", "INFO") as logs:
            self.assertEqual(svc.api_device_delete({"ids": ["a"]}, "admin")["deleted"], 1)
            self.assertEqual(svc.api_clear_offline({}, "admin")["deleted"], 2)
            svc.api_reset({}, "admin")
        self.assertEqual([r.getMessage() for r in logs.records],
                         ["1 device(s) deleted by admin", "2 offline device(s) removed by admin",
                          "all data deleted by admin"])

    def test_info_has_the_required_fields_and_no_deprecated_ones(self):
        info = self.info()
        for key in ("package", "version", "os_min_ver", "description", "arch", "maintainer",
                    "maintainer_url", "support_url", "helpurl"):
            self.assertTrue(info.get(key), key)
        for key in ("startable", "thirdparty"):
            self.assertNotIn(key, info)

    def test_the_app_name_is_the_same_everywhere(self):
        name = self.info()["dsmappname"]
        self.assertEqual(name, "SYNO.SDS.App.SynetScan.Instance")
        with open(os.path.join(self.ROOT, "src", "ui", "config"), encoding="utf-8") as f:
            cfg = json.load(f)["synetscan.js"]
        self.assertEqual(cfg[name]["appWindow"], "SYNO.SDS.App.SynetScan.MainWindow")
        self.assertIn("SYNO.SDS.App.SynetScan.MainWindow", cfg)
        for rel, text in (("src/ui/synetscan.js", 'Ext.define("%s"' % name),
                          ("src/ui/synetscan.js", 'Ext.define("SYNO.SDS.App.SynetScan.MainWindow"'),
                          ("src/ui/js/app.js", 'APP_ID = "%s"' % name)):
            with open(os.path.join(self.ROOT, rel), encoding="utf-8") as f:
                self.assertIn(text, f.read(), rel)

    def test_the_uninstall_dialog_asks_for_the_key_the_script_reads(self):
        with open(os.path.join(self.ROOT, "spk", "scripts", "postuninst"), encoding="utf-8") as f:
            script = f.read()
        for lang in ("", "_ger"):
            with open(os.path.join(self.ROOT, "spk", "WIZARD_UIFILES", "uninstall_uifile" + lang), encoding="utf-8") as f:
                steps = json.load(f)
            sub = steps[0]["items"][0]["subitems"][0]
            self.assertEqual(sub["key"], "wizard_delete_data")
            self.assertIs(sub["defaultValue"], False)   # keeping the data is what happens unless asked
            self.assertIn("$" + sub["key"], script)

    def postuninst(self, var, status, delete, logfile=""):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SYNOPKG_PKG_STATUS": status,
               "SYNOPKG_PKGVAR": var, "wizard_delete_data": delete, "SYNOPKG_TEMP_LOGFILE": logfile}
        r = subprocess.run(["sh", os.path.join(self.ROOT, "spk", "scripts", "postuninst")], env=env,
                           cwd=tempfile.gettempdir(), capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)

    def data_dir(self, name="SynetScan"):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        var = os.path.join(root, "@appdata", name)
        os.makedirs(os.path.join(var, "sub"))
        for n in ("devices.json", ".tmp-x", "..odd", "sub/a"):
            open(os.path.join(var, n), "w").close()
        link = os.path.join(root, "var")   # DSM's /var/packages/SynetScan/var is such a link
        os.symlink(var, link)
        return var, link

    def test_uninstall_deletes_the_data_only_when_asked(self):
        var, link = self.data_dir()
        self.postuninst(link, "UNINSTALL", "false")
        self.postuninst(link, "UPGRADE", "true")
        self.postuninst(link, "", "true")
        self.assertEqual(len(os.listdir(var)), 4)
        self.postuninst(link, "UNINSTALL", "true")
        self.assertEqual(os.listdir(var), [])
        self.assertTrue(os.path.isdir(var))   # the folder itself is DSM's

    def test_uninstall_never_deletes_anything_but_the_package_folder(self):
        var, link = self.data_dir("Other")
        log = os.path.join(var, "..", "pkglog")
        self.postuninst(link, "UNINSTALL", "true", log)
        self.postuninst(os.path.join(var, "missing"), "UNINSTALL", "true", log)
        self.assertEqual(len(os.listdir(var)), 4)
        with open(log) as f:   # Package Center shows why, instead of saying nothing
            self.assertEqual(f.read().count("SynetScan's data was not deleted"), 2)


if __name__ == "__main__":
    unittest.main()
