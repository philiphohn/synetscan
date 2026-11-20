"""Heuristic device-type classification and display-name selection."""
import re

TYPES = ["router", "nas", "computer", "server", "phone", "tablet", "printer", "camera",
         "media", "speaker", "console", "iot", "network", "virtual", "voip", "unknown"]

PORT_NAMES = {
    20: "FTP data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP",
    81: "HTTP alt", 88: "Kerberos", 110: "POP3", 111: "RPC", 135: "MS RPC", 139: "NetBIOS",
    143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS",
    515: "LPD", 548: "AFP", 554: "RTSP", 587: "SMTP sub", 631: "IPP", 873: "rsync",
    993: "IMAPS", 995: "POP3S", 1080: "SOCKS", 1400: "Sonos", 1433: "MSSQL", 1883: "MQTT",
    1900: "UPnP", 2049: "NFS", 3000: "HTTP dev", 3306: "MySQL", 3389: "RDP", 3689: "DAAP",
    5000: "DSM", 5001: "DSM HTTPS", 5060: "SIP", 5061: "SIP TLS", 5353: "mDNS", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 7000: "AirPlay", 7676: "DLNA", 8000: "HTTP alt", 8001: "TV remote",
    8002: "TV remote TLS", 8008: "Cast",
    8009: "Cast", 8080: "HTTP proxy", 8081: "HTTP alt", 8123: "Home Assistant",
    8443: "HTTPS alt", 8883: "MQTT TLS", 8888: "HTTP alt", 9000: "HTTP alt",
    9100: "JetDirect", 9197: "DIAL", 9443: "HTTPS alt", 10000: "Webmin", 32400: "Plex",
    49152: "UPnP", 62078: "iOS sync",
}

DEFAULT_PORTS = [21, 22, 23, 53, 80, 139, 443, 445, 515, 548, 554, 631, 1400, 1883, 3389,
                 5000, 5001, 5060, 5061, 5900, 7000, 7676, 8001, 8002, 8008, 8009, 8080, 8123, 8443,
                 9100, 9197, 32400, 62078]
# the defaults of earlier versions (1.0.0, and up to 1.1.8), so stored configurations that never
# changed them get the new ones
OLD_DEFAULT_PORTS = [
    [21, 22, 23, 53, 80, 139, 443, 445, 515, 548, 554, 631, 1400, 1883, 3389,
     5000, 5001, 5900, 7000, 8008, 8009, 8080, 8123, 8443, 9100, 32400, 62078],
    [21, 22, 23, 53, 80, 139, 443, 445, 515, 548, 554, 631, 1400, 1883, 3389,
     5000, 5001, 5900, 7000, 7676, 8001, 8002, 8008, 8009, 8080, 8123, 8443, 9100,
     9197, 32400, 62078],
]
TV_PORTS = {7676, 8001, 8002, 9197}
# IP phone systems, desk phones, DECT bases and VoIP adapters (as the MAC registry names them)
VOIP_VENDORS = ("mitel", "aastra", "snom", "yealink", "grandstream", "polycom", "avaya", "gigaset", "fanvil",
                "unify", "auerswald", "agfeo", "innovaphone", "obihai", "audiocodes", "patton", "sangoma",
                "digium", "escene")
_VOIP_VENDOR = re.compile(r"\b(?:%s)" % "|".join(VOIP_VENDORS))  # at a word start: not "ARMITEL"


def _has(text, *words):
    return any(w in text for w in words)


def classify(dev, gateways=(), own_ips=()):
    """Return a type from TYPES for a device record (dict)."""
    ip = dev.get("ip", "")
    ports = set(dev.get("ports") or [])
    vendor = (dev.get("vendor") or "").lower()
    names = " ".join(filter(None, [
        dev.get("hostname"), dev.get("mdns_name"), dev.get("netbios"), dev.get("friendly"),
        dev.get("model"), (dev.get("upnp") or {}).get("modelName"),
        (dev.get("http") or {}).get("title"), (dev.get("http") or {}).get("server"),
    ])).lower()
    services = " ".join(dev.get("services") or []).lower()
    upnp_type = ((dev.get("upnp") or {}).get("deviceType") or "").lower()

    nas_vendor = _has(vendor, "synology", "qnap", "asustor", "terramaster")
    storage_vendor = _has(vendor, "western digital", "buffalo", "netgear") and bool(ports & {445, 139, 548, 2049})
    if ip in own_ips or nas_vendor or storage_vendor and "nas" in names \
            or ports >= {5000, 5001} or _has(names, "diskstation", "rackstation", "synology"):
        return "nas"
    if ip in gateways or "internetgatewaydevice" in upnp_type or _has(names, "fritz!box", "fritzbox", "speedport", "easybox", "router") \
            or _has(vendor, "avm") and ports & {80, 443, 53}:
        return "router"
    if _has(vendor, "vmware", "qemu", "xensource", "parallels", "virtualbox", "proxmox") \
            or (dev.get("mac") or "").startswith("00:15:5d"):
        return "virtual"
    if _VOIP_VENDOR.search(vendor) or vendor == "poly" or ports & {5060, 5061} \
            or _has(names, "mivoice", "aastra", "snom", "yealink", "grandstream", "polycom", "gigaset", "fanvil",
                    "auerswald", "agfeo", "innovaphone", "obihai", "freepbx", "asterisk", "3cx", "pbx", "voip",
                    "sip phone", "sip-phone", "ip phone", "ip-phone"):
        return "voip"
    if ports & {9100, 515} or _has(services, "_ipp", "_printer", "_pdl-datastream", "_scanner", "_uscan") \
            or "printer" in upnp_type or _has(names, "printer", "laserjet", "officejet", "deskjet", "envy", "pixma"):
        return "printer"
    if 554 in ports or _has(vendor, "hikvision", "dahua", "axis comm", "reolink", "amcrest", "foscam", "hanwha", "mobotix") \
            or _has(names, "camera", "ipcam", "nvr", "doorbell"):
        return "camera"
    if _has(vendor, "nintendo", "sony interactive") or _has(names, "playstation", "xbox", "nintendo", "steamdeck", "steam deck"):
        return "console"
    if 1400 in ports or _has(vendor, "sonos", "bose", "harman", "denon", "yamaha", "bang & olufsen") \
            or _has(services, "_sonos", "_spotify-connect") and not _has(services, "_airplay", "_googlecast") \
            or _has(names, "homepod", "echo", "speaker", "soundbar"):
        return "speaker"
    if _has(services, "_googlecast", "_airplay", "_androidtvremote", "_roku") and not _has(names, "macbook", "imac", "mac mini", "mac-mini", "mac pro") \
            or 8009 in ports or ports & TV_PORTS or _has(services, "_samsungmsf", "_dial") or _has(vendor, "roku", "lg electronics", "tcl", "hisense", "vizio", "nvidia") \
            or "mediarenderer" in upnp_type or _has(names, "chromecast", "appletv", "apple-tv", "apple tv", "fire tv", "firetv", "shield", "bravia", "tv"):
        return "media"
    if _has(names, "ipad", "tablet", "galaxy-tab", "galaxytab", "kindle"):
        return "tablet"
    if 62078 in ports or _has(names, "iphone", "android", "galaxy", "pixel", "oneplus", "xiaomi", "redmi", "huawei-", "honor-", "-phone", "smartphone") \
            or _has(vendor, "oneplus", "oppo", "vivo mobile", "realme"):
        return "phone"
    if _has(vendor, "espressif", "tuya", "shelly", "allterco", "signify", "philips lighting", "tp-link smart", "ecobee", "nest",
            "ring", "arlo", "wemo", "belkin", "lifx", "sonoff", "itead", "xiaomi", "meross", "bosch", "homematic",
            "eq-3", "texas instruments", "silicon labs", "murata", "azurewave", "particle") \
            or 1883 in ports or 8123 in ports or _has(services, "_hap", "_homekit", "_mqtt", "_hue") \
            or _has(names, "esp-", "esp32", "esp8266", "shelly", "tasmota", "hue", "homeassistant", "home-assistant", "smartplug", "thermostat"):
        return "iot"
    if _has(vendor, "ubiquiti", "tp-link", "netgear", "cisco", "aruba", "zyxel", "mikrotik", "juniper", "d-link",
            "linksys", "lancom", "ruckus", "meraki", "draytek", "edimax", "devolo", "tenda", "openwrt", "mercusys") \
            or _has(names, "switch", "access point", "unifi", "-ap", "repeater", "mesh", "powerline", "deco"):
        return "network"
    if 3389 in ports or _has(names, "macbook", "imac", "mac mini", "mac-mini", "desktop-", "laptop", "notebook", "-pc", "workstation", "thinkpad") \
            or _has(services, "_workstation", "_companion-link", "_rdp") or (ports & {139, 445} and dev.get("netbios")):
        return "computer"
    if 22 in ports and (ports & {80, 443, 3306, 5432, 6379, 8080, 25}) or _has(names, "server", "srv", "proxmox", "ubuntu", "debian"):
        return "server"
    if _has(vendor, "raspberry pi"):
        return "server" if 22 in ports else "iot"
    if _has(vendor, "apple"):
        return "phone" if not ports else "computer"
    if _has(vendor, "samsung"):
        # Galaxy phones use a private MAC on Wi-Fi by default; a Samsung address is most often a TV
        return "phone" if 62078 in ports or dev.get("random_mac") else "media"
    if _has(vendor, "intel", "dell", "lenovo", "hewlett", "hp inc", "asustek", "micro-star", "gigabyte", "acer", "realtek", "liteon", "hon hai", "microsoft"):
        return "computer"
    if dev.get("random_mac") and not ports:
        return "phone"
    if 22 in ports:
        return "server"
    # weak signal last: Thread border routers (HomePod, Nest…) also announce IPv6 routes
    if dev.get("ipv6_router"):
        return "router"
    return "unknown"


_GENERIC_TITLE = re.compile(r"^(login|log in|sign in|index of|welcome|home|redirect|document|untitled|error|\d{3}\b)|"
                            r"unauthori[sz]ed|forbidden|not found|it works|default page|nginx|apache|iis", re.I)
_LOCAL = re.compile(r"\.(local|lan|home|fritz\.box|localdomain|intranet|internal|home\.arpa)$", re.I)


_RANDOM_ID = re.compile(r"^[A-Za-z0-9+/=_-]{10,}$")
_HEX_ID = re.compile(r"^[0-9a-f]{8,}(-[0-9a-f]{4,})*$", re.I)
# the host names Android makes up: "Android_K7QX2M4P" (mDNS), "android-0a1b2c3d4e5f6789" (DHCP)
_ANDROID_ID = re.compile(r"^(Android_[A-Z0-9]{8}|android-[0-9a-f]{16})$")
_GENERIC_UPNP = re.compile(r"^(upnp\b|igd\b|internet ?gateway ?device|wan ?(connection ?)?device|"
                           r"mediarenderer|mediaserver|basic ?device|unknown)", re.I)


def junk_name(name):
    """Names that identify nothing for a human: random service IDs, UUIDs, generic UPnP classes."""
    name = (name or "").strip()
    if len(name) < 2 or name.isdigit():  # e.g. TeamViewer announces its instance as "0"
        return True
    if name.lower().startswith("nearby-presence"):
        return True
    if _HEX_ID.match(name) or _ANDROID_ID.match(name):
        return True
    if _RANDOM_ID.match(name) and re.search(r"[a-z]", name) and re.search(r"[A-Z]", name) and re.search(r"\d", name):
        return True
    return False


def generic_upnp_name(name):
    return bool(_GENERIC_UPNP.match((name or "").strip()))


def bogus_model(model, vendor):
    """Synology (and others) announce "Xserve" in mDNS _device-info only to get a Finder icon."""
    return (model or "").lower().startswith("xserve") and "apple" not in (vendor or "").lower()


def join_model(manufacturer, model):
    """"ZTE" + "ZTE H1600" -> "ZTE H1600" (no doubled manufacturer)."""
    manufacturer, model = (manufacturer or "").strip(), (model or "").strip()
    if not model:
        return ""
    if not manufacturer or model.lower().startswith(manufacturer.lower().split()[0]):
        return model
    return "%s %s" % (manufacturer, model)


def short_host(name):
    if not name:
        return ""
    name = _LOCAL.sub("", name.rstrip("."))
    return name


def display_name(dev):
    if dev.get("name"):
        return dev["name"]
    if dev.get("friendly") and not junk_name(dev["friendly"]) and not generic_upnp_name(dev["friendly"]):
        return dev["friendly"]
    for key in ("mdns_name", "netbios", "hostname"):
        if dev.get(key) and not junk_name(short_host(dev[key])):
            return short_host(dev[key])
    if dev.get("model") and dev.get("gateway"):
        return dev["model"]
    if dev.get("vendor"):
        return dev["vendor"]
    title = (dev.get("http") or {}).get("title", "")
    if title and not _GENERIC_TITLE.search(title):
        return title
    return dev.get("ip") or (dev.get("ipv6") or [""])[0] or dev.get("mac") or "?"
