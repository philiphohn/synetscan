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
            {"name": "eth0", "network": "192.168.1.0/24", "virtual": False},
            {"name": "docker0", "network": "172.17.0.0/16", "virtual": True}]
        try:
            loc = netinfo.client_location
            self.assertEqual(loc("127.0.0.1")["via"], "relay")      # QuickConnect relay tunnel
            self.assertFalse(loc("127.0.0.1")["local"])
            self.assertFalse(loc("84.10.20.30")["local"])            # DDNS / port forwarding
            self.assertTrue(loc("192.168.1.100")["local"])           # browser in the LAN
            self.assertTrue(loc("::ffff:192.168.1.100")["local"])
            self.assertFalse(loc("172.17.0.5")["local"])             # docker bridge is not the LAN
            self.assertTrue(loc("fe80::1")["local"])
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


if __name__ == "__main__":
    unittest.main()
