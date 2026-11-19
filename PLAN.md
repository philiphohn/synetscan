# SynetScan – LAN network scanner for Synology DSM 7

## Goal
A Synology package (`.spk`, `noarch`) that discovers devices on the NAS's LAN and
presents them in a UI that looks and behaves like a native DSM 7 application,
launched from the DSM main menu.

## Constraints that shape the design
* **DSM 7 forbids root for third-party packages** → the scanner runs as the
  unprivileged package user. No raw sockets, so no classic ARP scan / ICMP.
  * Discovery trick: send a UDP datagram + TCP connects to every address. The
    kernel ARP-resolves each target; afterwards `/proc/net/arp` (world readable)
    lists every host that answered ARP – even fully firewalled ones.
  * `ping` is used additionally if the system binary works for the package user.
* **No compiler/toolchain dependency** → Python 3 standard library only
  (DSM 7 ships `/usr/bin/python3`, 3.8). Code stays 3.8-compatible.
* **UI integration** → `ui/config` entry of type `legacy` = page opened in an
  iframe inside a real DSM window (DSM supplies title bar, minimise, etc.).
  The page itself re-creates DSM 7 styling (left navigation, toolbars, grids,
  dialogs, forms, buttons) with plain HTML/CSS/JS – no build step.
* **Auth** → every API call goes through `api.cgi`, which validates the DSM
  session (cookie + SynoToken) with `/usr/syno/synoman/webman/modules/authenticate.cgi`
  and requires membership of `administrators`.

## Architecture
```
DSM window (iframe) ── index.html + js/app.js + css/dsm.css
        │  fetch /webman/3rdparty/SynetScan/api.cgi?action=…  (SynoToken header)
        ▼
api.cgi (sh → python)  auth check → forwards JSON request
        │  unix socket  /var/packages/SynetScan/var/synetscan.sock
        ▼
synetscand (daemon, started by start-stop-status)
   ├─ API handler (devices, config, events, wake-on-LAN, export …)
   ├─ scheduler (periodic scans)
   ├─ scanner (worker thread)
   │    1. targets: auto-detected interface subnets + custom ranges
   │    2. discovery: UDP poke + TCP probes (+ping) → ARP table
   │    3. enrichment: port scan, reverse DNS, NetBIOS, mDNS, SSDP/UPnP, HTTP title
   │    4. classification (router, NAS, printer, phone, TV, IoT …) + OUI vendor
   └─ store: JSON files (devices, events, scan history, config) – single writer
```

## UI (DSM 7 look & feel)
* Left navigation: **Overview**, **Devices**, **Activity**, **Settings**
* Overview: status tiles, network interfaces, device-type breakdown, recent activity
* Devices: toolbar (Scan, Edit, Wake, Delete, Export), filter + search, sortable
  grid with status dots and type icons; detail/edit dialog with tabs
* Activity: event log (new device, offline, back online, IP changed)
* Settings: scan targets, schedule, ports, advanced, data maintenance
* English + German, chosen from the DSM session language

## Deliverables
* `src/` package sources, `spk/` package metadata & lifecycle scripts
* `build.sh` → `dist/SynetScan-<ver>-noarch.spk`
* `tools/devserver.py` – local preview with a mock DSM desktop
* `tests/` – unit tests for parsers, classifier, store, target expansion
* `README.md` – install, usage, architecture, limitations
