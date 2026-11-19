# SynetScan – network scanner for Synology DSM 7

SynetScan is a Synology package that finds and monitors the devices on the NAS's
local network. It opens as a regular window on the DSM desktop and is styled
like DSM 7's own apps: the left navigation, toolbars, grids, dialogs and forms
all follow DSM's look.

| | |
|---|---|
| **Overview** | Health banner, counters, recent activity, device types, network interfaces |
| **Devices** | Sortable/filterable grid, search, right-click menu, Edit dialog (name, type, notes), Wake-on-LAN, open web UI, CSV export |
| **Activity** | Event log (new device, offline, back online, IP changed) and scan history |
| **Settings** | Scan targets (interfaces + custom ranges/VLANs), schedule, port list, detection methods, performance, data maintenance |

The UI is available in English and German and follows the DSM session language.

## Installation

1. Build the package (or use a prebuilt `dist/*.spk`):
   ```sh
   ./build.sh            # -> dist/SynetScan-1.0.2-0001-noarch.spk
   ```
2. In DSM, open **Package Center → Manual Install** and choose the `.spk`.
   DSM will warn that the package is from an unknown publisher (it isn't signed
   by Synology). Confirm to continue.
3. Open **SynetScan** from the DSM main menu. After an update, reload the DSM page (F5)
   so the desktop picks up the new app entry. A first scan runs automatically when
   the service starts. The devices it finds become the "known" baseline, and any
   device that appears later is flagged as **New**.

Requirements: DSM 7.0 or newer and Python 3. DSM 7 already ships `/usr/bin/python3`.
If it is missing, install **Python 3.9** from Package Center first. The package is
`noarch`, so it installs on every model.

Only members of the **administrators** group can open the app. Both the DSM menu
entry and the API check this.

## How it works

```
DSM window (iframe)  index.html · js/app.js · css/dsm.css
      │  fetch api.cgi?action=…   (DSM session cookie + SynoToken)
      ▼
api.cgi  ─ validates the session via DSM's authenticate.cgi, checks admin group
      │  JSON over unix socket  /var/packages/SynetScan/var/synetscan.sock
      ▼
synetscand  (package service, runs as the unprivileged package user)
  ├─ scheduler (periodic scans, scan on start)
  ├─ scanner   discovery → enrichment → classification
  └─ store     devices.json · events.json · scans.json · config.json
```

DSM 7 does not let third-party packages run as root, so raw ARP/ICMP sockets
aren't available. SynetScan works around this without privileges:

1. **Discovery.** For every address it sends a UDP datagram and makes a few
   parallel TCP connection attempts. Any answer, even a refusal, proves the host
   exists. These packets also force the kernel to ARP-resolve every address, so
   afterwards `/proc/net/arp`, which any user can read, lists every host that
   answered ARP. That includes completely firewalled devices.
   Hosts known only from the ARP cache are re-checked after the cache has settled,
   so devices that just left the network are not reported as online.
   `ping` is used too, if the system binary works for the package user.
2. **Enrichment.** For each discovered device:
   - a TCP port scan (configurable list)
   - reverse DNS
   - a NetBIOS node-status query
   - mDNS/Bonjour, both a DNS-SD browse and a unicast reverse lookup
   - SSDP/UPnP, including the device description XML
   - the HTTP title and Server header
   - vendor lookup from the MAC address (bundled Wireshark OUI database, about 59k entries)
3. **Classification.** Heuristics turn the vendor, ports, services and names into
   a device type: router, NAS, computer, server, phone, tablet, printer, camera,
   TV/media, speaker, console, smart home, network device, virtual machine.

A /24 network takes roughly 8–15 seconds to scan.

## DSM integration

- **Window.** Since DSM 7.2 a `"type": "legacy"` app entry opens in a browser tab, where the
  page cannot use the DSM session. So `ui/config` registers an ExtJS application,
  `SYNO.SDS.SynetScan.Instance` (see `ui/synetscan.js`), whose `SYNO.SDS.AppWindow` holds
  `index.html` in an iframe. `dsmappname` in INFO names the same class, which is what Package
  Center's "Open" button uses.
- **Session token.** The UI reads the SynoToken from the DSM desktop (its parent window). It
  also receives it in the URL fragment, which no server or log ever sees. API calls send it
  only as the `X-SYNO-TOKEN` header, CSV export included.
- **Opened outside DSM.** If `index.html` is opened in a tab on its own, the page offers
  "Open in DSM", which goes to `/?launchApp=SYNO.SDS.SynetScan.Instance`.
- **Service socket.** The socket has mode `0600`. Only the package user, which DSM also runs
  the package CGI as, can reach the service; everyone else has to go through `api.cgi` and its
  DSM session and admin checks.
- **Local or remote.** "Open web interface" only works when the browser is in the NAS's
  network. `api.cgi?action=client` compares the browser's address (`REMOTE_ADDR`) with the
  NAS's interface networks. A QuickConnect relay arrives via loopback, and DDNS or port
  forwarding arrives from a public address; both count as remote, and the web links are then
  greyed out with an explanation. Local QuickConnect hosts (`192-168-…direct.quickconnect.to`)
  count as local.
- **Errors.** The CGI always answers HTTP 200 with `"success": false`, so DSM's nginx never
  swaps the answer for an HTML error page. The UI translates errors by their `code`.

## Repository layout

```
src/
  bin/synetscand          daemon launcher (finds python3)
  lib/synetscan/          Python package (stdlib only, Python ≥ 3.6 / tested 3.8 + 3.12)
    scanner.py probes.py netinfo.py dnsmsg.py classify.py targets.py
    store.py config.py daemon.py cgi_main.py oui.py util.py
  share/oui.txt.gz        MAC vendor database (generated by tools/build_oui.py)
  ui/                     DSM web UI (config, index.html, api.cgi, css, js, images)
spk/                      INFO template, conf/privilege, lifecycle scripts, package icons
tools/
  devserver.py            local preview with a mock DSM desktop
  mock_dsm.html           the mock desktop (window frame + iframe)
  shot.mjs                headless-Chrome screenshot helper (CDP, no deps)
  build_oui.py            Wireshark manuf -> oui.txt.gz
  make_icons.py           renders the app/package icons (Pillow)
tests/test_core.py        unit tests
build.sh                  builds dist/SynetScan-<version>-noarch.spk
```

## Development

```sh
python3 -m unittest discover -s tests      # unit tests
python3 tools/devserver.py                 # http://127.0.0.1:8640/  (?lang=de, ?page=devices)
```

The dev server runs the real daemon, with its data in `.devvar/`, and the real
`api.cgi`. Setting `SYNETSCAN_DEV=1` skips the DSM login check. To scan specific
ranges, edit them in **Settings → Scan Targets**.

To update the vendor database:

```sh
curl -o third_party/manuf https://www.wireshark.org/download/automated/data/manuf
python3 tools/build_oui.py third_party/manuf src/share/oui.txt.gz
```

To release a new version, change `__version__` in `src/lib/synetscan/__init__.py`.
`BUILD=0002 ./build.sh` sets the build number.

## Limitations

- **IPv4 only.**
- **Routed networks have no MAC addresses.** Devices in networks reached through a
  router (custom ranges) are found by TCP/ping only. They show up without a MAC
  address, so no vendor lookup is possible for them.
- **Device types are guesses.** Many devices hide behind private (randomised) MAC
  addresses. The type can be corrected in the device's Edit dialog.
- **Docker hosts.** When Container Manager is installed, the `docker*`/`veth*`
  bridges are skipped automatically. Add a range under custom ranges if you want
  to scan one anyway.
- **Tested on a DS220+ with DSM 7.4.1 (version 1.0.0).** Install, service, CGI,
  authentication and scanning worked. The legacy app entry opened a browser tab, which
  1.0.1 replaces with the ExtJS window described above; that window still needs testing on
  real hardware.

Logs are in `/var/packages/SynetScan/var/synetscan.log`. DSM 7.4 Package Center has no Log
tab for third-party packages, so read the file over SSH or with a Task Scheduler script.
