import os
import struct
import sys
import tempfile
import unittest

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
        self.assertEqual(s["new"], 2)
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
        dev = {"friendly": "Xq7PzK2mW9tBBB", "mdns_name": "Android_ABCDEFGH.local", "ip": "1.2.3.4"}
        self.assertEqual(classify.display_name(dev), "Android_ABCDEFGH")
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
        st.config["ports"] = list(classify.OLD_DEFAULT_PORTS)
        st.save_config()
        st2 = Store(d)
        self.assertTrue(st2.devices["00:11:32:00:00:01"]["baseline"])
        self.assertEqual(st2.config["ports"], classify.DEFAULT_PORTS)


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


if __name__ == "__main__":
    unittest.main()
