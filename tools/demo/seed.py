"""Write a made-up home network into a SynetScan data directory (for the README demo).

    python3 tools/demo/seed.py .devvar
"""
import json
import os
import sys
import time

NOW = int(time.time())
MIN, HOUR, DAY = 60, 3600, 86400


def device(ip, mac, vendor, typ, ports=(), **kw):
    d = {"id": mac, "ip": "192.168.1.%d" % ip, "mac": mac, "vendor": vendor, "type_auto": typ,
         "ports": list(ports), "first_seen": NOW - 14 * DAY, "last_seen": NOW - 9 * MIN, "online": True,
         "known": True, "baseline": True, "name": "", "notes": "", "type_user": "", "ip_history": [],
         "via": ["arp", "tcp"], "iface": "eth0", "rtt": None}
    d.update(kw)
    return d


DEVICES = [
    device(1, "3c:a6:2f:10:20:01", "AVM", "router", (53, 80, 443), friendly="FRITZ!Box 7590", model="AVM FRITZ!Box 7590",
           gateway=True, via=["arp", "ndp", "ssdp", "tcp"], services=["_http._tcp", "_fritzbox._tcp"],
           ipv6=["2001:db8:4a1c:100::1", "fd00::3ea6:2fff:fe10:2001", "fe80::3ea6:2fff:fe10:2001"]),
    device(2, "5c:62:8b:10:20:02", "TP-Link Systems", "network", (80, 443), friendly="Deco X60 (Hallway)", model="TP-Link Deco X60"),
    device(3, "5c:62:8b:10:20:03", "TP-Link Systems", "network", (80, 443), friendly="Deco X60 (Upstairs)", model="TP-Link Deco X60"),
    device(10, "00:11:32:10:20:10", "Synology", "nas", (80, 139, 443, 445, 5000, 5001), mdns_name="DiskStation.local",
           model="DS923+", self=True, via=["self"], services=["_smb._tcp", "_http._tcp", "_afpovertcp._tcp"],
           ipv6=["2001:db8:4a1c:100:211:32ff:fe10:2010", "fe80::211:32ff:fe10:2010"]),
    device(20, "e8:aa:cb:10:20:20", "Samsung Electronics", "media", (7676, 8001, 8002, 9197), friendly="Living Room TV",
           model="Samsung QE55LS03 The Frame", via=["arp", "ssdp", "tcp"]),
    device(21, "f4:f5:d8:10:20:21", "Google", "media", (8008, 8009), friendly="Kitchen Display", model="Google Nest Hub",
           via=["arp", "mdns", "tcp"], services=["_googlecast._tcp"]),
    device(22, "d4:a3:3d:10:20:22", "Apple", "speaker", (7000,), friendly="HomePod mini", via=["arp", "mdns", "tcp"],
           services=["_airplay._tcp", "_raop._tcp"]),
    device(23, "48:a6:b8:10:20:23", "Sonos", "speaker", (1400,), friendly="Sonos One (Bedroom)", model="Sonos One"),
    device(30, "ec:b5:fa:10:20:30", "Philips Lighting", "iot", (80, 443), friendly="Philips Hue Bridge", model="Philips hue bridge 2015",
           via=["arp", "mdns", "tcp"], services=["_hue._tcp", "_hap._tcp"]),
    device(31, "c8:c9:a3:10:20:31", "Shelly", "iot", (80,), hostname="shellyplug-s-1020", friendly="Shelly Plug S (Office)"),
    device(32, "70:ee:50:10:20:32", "Netatmo", "iot", (), friendly="Netatmo Weather Station", via=["arp"]),
    device(40, "88:66:5a:10:20:40", "Apple", "computer", (445, 5900), mdns_name="MacBook-Pro.local", model="MacBookPro18,3",
           services=["_smb._tcp", "_companion-link._tcp"], via=["arp", "mdns", "ndp", "tcp"],
           ipv6=["2001:db8:4a1c:100:8c2e:41ff:9a0b:77d1", "2001:db8:4a1c:100:1c3f:9e21:5b7a:c2e4", "fe80::14be:3a9c:66d2:80f1"]),
    device(41, "a4:bb:6d:10:20:41", "Dell", "computer", (135, 139, 445, 3389), netbios="DESKTOP-OFFICE", workgroup="WORKGROUP"),
    device(42, "54:e1:ad:10:20:42", "Lenovo", "computer", (22,), hostname="thinkpad-x1.lan"),
    device(50, "56:10:20:00:00:50", "", "phone", (62078,), mdns_name="iPhone.local", random_mac=True),
    device(51, "6a:10:20:00:00:51", "", "phone", (), mdns_name="Galaxy-S24.local", random_mac=True, via=["arp"]),
    device(52, "9e:10:20:00:00:52", "", "tablet", (62078,), mdns_name="iPad.local", random_mac=True,
           ip_history=["192.168.1.47"]),
    device(60, "64:4e:d7:10:20:60", "HP", "printer", (80, 443, 631, 9100), friendly="HP LaserJet M234sdw", model="HP LaserJet M234sdw",
           via=["arp", "mdns", "tcp"], services=["_ipp._tcp", "_pdl-datastream._tcp", "_uscan._tcp"]),
    device(70, "ec:71:db:10:20:70", "Reolink", "camera", (80, 443, 554), friendly="Front Door Camera", model="Reolink Video Doorbell"),
    device(80, "00:d9:d1:10:20:80", "Sony Interactive Entertainment", "console", (), friendly="PlayStation 5", via=["arp", "ssdp"]),
    device(81, "98:41:5c:10:20:81", "Nintendo", "console", (), via=["arp"]),
    device(90, "dc:a6:32:10:20:90", "Raspberry Pi", "server", (22, 8123), hostname="homeassistant.lan",
           friendly="Home Assistant", services=["_home-assistant._tcp"]),
    device(100, "24:0a:c4:10:21:00", "Espressif", "iot", (80,), known=False, baseline=False, first_seen=NOW - 26 * MIN,
           hostname="esp32-c3f1a0.lan"),
    dict(device(0, "70:b3:d5:10:20:99", "Bosch Thermotechnik", "iot", (80, 443), friendly="Heat Pump Controller",
                via=["ndp", "mdns"], ipv6=["2001:db8:4a1c:100:72b3:d5ff:fe10:2099", "fe80::72b3:d5ff:fe10:2099"]), ip=""),
    device(45, "f0:de:f1:10:20:45", "Lenovo", "computer", (139, 445), netbios="OLD-LAPTOP", online=False,
           last_seen=NOW - 2 * DAY - 3 * HOUR, missed=40),
]


def event(ago, kind, d=None, detail=""):
    return {"ts": NOW - ago, "kind": kind, "id": d and d["id"], "name": d and (d.get("friendly") or d.get("mdns_name", "").replace(".local", "")
            or d.get("netbios") or d.get("hostname", "").replace(".lan", "")) or "", "ip": d and d["ip"] or "",
            "mac": d and d["mac"] or "", "detail": detail}


def main(var):
    os.makedirs(var, exist_ok=True)
    by_ip = {d["ip"].rsplit(".", 1)[1]: d for d in DEVICES if d["ip"]}
    devices = {d["id"]: d for d in DEVICES}
    events = sorted([
        event(14 * DAY, "baseline", detail=str(len(DEVICES) - 1)),
        event(5 * DAY, "new", by_ip["70"], "Reolink"),
        event(2 * DAY + 3 * HOUR, "offline", by_ip["45"]),
        event(9 * HOUR, "ip_changed", by_ip["52"], "192.168.1.47 → 192.168.1.52"),
        event(3 * HOUR, "online", by_ip["51"]),
        event(26 * MIN, "new", by_ip["100"], "Espressif"),
    ], key=lambda e: e["ts"])
    scans = []
    for i in range(12, 0, -1):
        fin = NOW - 9 * MIN - (i - 1) * HOUR
        scans.append({"started": fin - 11, "finished": fin, "duration": 10.6 + (i % 4) * 0.4,
                      "targets": ["192.168.1.0/24 (eth0)"], "target_count": 254, "found": 23,
                      "new": 1 if i == 1 else 0, "offline": 0, "online_again": 0, "ip_changed": 0,
                      "trigger": "schedule"})
    config = {"scan_on_start": False, "schedule_enabled": True, "schedule_interval": 60}
    for name, data in (("devices.json", devices), ("events.json", events), ("scans.json", scans), ("config.json", config)):
        with open(os.path.join(var, name), "w") as f:
            json.dump(data, f, ensure_ascii=False)
    print("seeded %d devices into %s" % (len(devices), var))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".devvar")
