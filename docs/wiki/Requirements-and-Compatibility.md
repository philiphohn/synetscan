# Requirements and Compatibility

SynetScan is a single package for every Synology model that runs DSM 7. This page lists what it needs and where it has been tested.

## Requirements

| Requirement | Details |
| --- | --- |
| **DSM version** | DSM 7.0 or newer. The package declares a minimum of DSM 7.0-40000, so Package Center refuses it on DSM 6. |
| **Model / CPU** | Any. The package is `noarch`: it contains only Python, HTML and JavaScript, no compiled code. |
| **Python 3** | Python 3.6 or newer. DSM 7 ships `/usr/bin/python3` (3.8), so normally there is nothing to install. The installer stops with a message if no Python 3 is found. In that case install **Python 3.9** from Package Center first. |
| **Account** | A DSM user in the **administrators** group, to install the package and to use the app. |
| **Network** | The NAS must be connected to the network you want to scan. Other networks reached through a router can be added as [custom ranges](Scan-Targets). |
| **Browser** | Any current browser that runs DSM 7. |
| **Disk space** | The package is under 1 MB. Its data (device list, history, log) stays small; see [Data Storage](Data-Storage-and-Backup). |

SynetScan looks for Python in this order and uses the first one it finds:

1. `/var/packages/Python3.9/target/usr/bin/python3` (the Python 3.9 package from Package Center)
2. `/usr/local/bin/python3`
3. `/usr/bin/python3` (the one DSM 7 ships)
4. `/bin/python3`

It uses only the Python standard library. There are no extra modules, no Docker container and no internet connection to set up.

## What SynetScan does not need

- **No root.** It runs as an unprivileged package user, as DSM 7 requires for third-party packages. See [DSM Permissions, Security, and Privacy](Security-and-Privacy).
- **No Docker, no Container Manager.**
- **No cloud account, no internet access.** Everything stays on the NAS.
- **No command line.** Installation, use and configuration all happen in DSM. SSH is only needed for optional tasks such as [enabling ICMP ping](Enabling-ICMP-Ping) or reading the [log file](Logs-and-Diagnostics).

## Tested on

SynetScan was tested on three Synology NAS in three different networks, from the first install through updates to IPv6:

| Model | CPU | DSM | Network | Access |
| --- | --- | --- | --- | --- |
| DS220+ | Intel Celeron J4025 (x86-64) | 7.4.1 | Home network, IPv6 off on the NAS | QuickConnect |
| DS923+ | AMD Ryzen R1600 (x86-64) | 7.4.1 | Office network with two LAN ports, a VPN router using proxy ARP, link-local IPv6 | Local network |
| DS1813+ | Intel Atom D2700 (x86-64) | 7.1.1 | Home network with native IPv6 from the provider, Open vSwitch | Tailscale |

The package is `noarch` and uses only the Python that DSM ships, so other models and DSM 7 versions should work the same way.

**ARM models have not been tried yet.** All three test NAS use x86-64 CPUs. SynetScan contains no compiled code, so ARM models (for example the "j" and value series) should work as well. If you run SynetScan on an ARM model, a short report in the [issues](https://github.com/philiphohn/synetscan/issues) is welcome.

## DSM versions in detail

- **DSM 7.0 and 7.1**: supported. Tested on DSM 7.1.1.
- **DSM 7.2 and later**: supported. Tested on DSM 7.4.1. Since DSM 7.2, a simple "legacy" app entry would open in a separate browser tab, where it cannot use your DSM sign-in. SynetScan therefore registers a real DSM desktop window, like Synology's own apps. See [Architecture and DSM Integration](Architecture).
- **DSM 6.x and older**: not supported.
- **DSM 7 on virtual DSM (VMM)**: not tested. It should behave like any other DSM 7 system, but it can only see the networks of its virtual network adapter.

## Access methods

SynetScan works however you reach DSM: in the local network, through QuickConnect, a VPN or a DDNS name. One function depends on it: **Open Web Interface** only works when your browser is in the NAS's local network. See [Local Access, QuickConnect, VPN, and DDNS](Local-Access-QuickConnect-VPN-and-DDNS).

## Related articles

- [Installing SynetScan](Installation)
- [FAQ and Known Limitations](FAQ)
- [Network Scanning Basics](Network-Scanning-Basics)
