# DSM Permissions, Security, and Privacy

SynetScan has an inventory of your whole network, so who can see it and what it may do matters. This page describes the permissions model, how SynetScan protects itself against hostile devices on the network, and what happens to your data.

## Who can use SynetScan

- **Administrators only.** Only members of the DSM **administrators** group can open SynetScan. The main menu entry is hidden from other users, and **every API request** is checked again on the NAS, so hiding the menu isn't the only barrier. Other users get: *SynetScan is only available to members of the administrators group.*
- **Your DSM sign-in is the only sign-in.** SynetScan has no accounts or passwords of its own. Each request is checked against your DSM session by DSM's own `authenticate.cgi`, with the session cookie and DSM's session token (SynoToken). If the session has expired, the app asks you to sign in to DSM again.
- **The session token stays out of URLs.** The app reads the token from the DSM desktop and sends it only in a request header, the CSV export included. It never appears in an address, a log or the browser history. *Available since 1.1.3.*
- To give a colleague access, make them a DSM administrator. There is no read-only role.

## What the package may do on the NAS

- **It runs as an unprivileged package user**, not as root. DSM 7 requires that for third-party packages (`run-as: package`).
- That user can't open raw sockets. That's why SynetScan finds devices through ordinary connections and the kernel's ARP table, and why [ICMP ping](Enabling-ICMP-Ping) may be unavailable.
- **The service's control socket** (`synetscan.sock`) can only be opened by the package user. All access goes through `api.cgi`, which checks the DSM session and the administrators group first.
- **The data files and the log can only be read by the package user** (file mode `0600`). Files from older versions are tightened when the service starts. *Available since 1.1.3.*
- SynetScan uses no database server, starts no shell with input from the network or the browser, and writes only to its own data folder.

## How SynetScan treats data from the network

Almost everything SynetScan shows comes from the devices themselves: names, models, service announcements, web page titles. Anyone in your network can send such answers, so SynetScan treats all of it as untrusted input. *Most of the following is available since 1.1.3.*

- **Names stay text.** Control characters and invisible or direction-changing Unicode characters are removed, and every string is cut to a fixed length before it is stored. The app shows these strings as text, never as markup. A Content Security Policy on the page allows no inline or foreign scripts and no connections to other hosts.
- **The NAS only talks to the device it asked.** A UPnP description is fetched only from the device that announced it, whatever address the announcement names. Redirects are followed on the same device only, and no host name from the network is ever resolved. A device can't make the NAS fetch pages from other machines, or read local files.
- **A device can't stall or flood a scan.** Each device has a fixed time budget, however slowly it answers. Answer sizes, the number of devices (8,192), the history and the list fields are limited. XML with a DOCTYPE is refused, which blocks entity-expansion attacks.
- **The log stays one line per entry.** Text from the network can't forge log lines.
- **CSV export.** Cells that a spreadsheet would run as a formula get a leading apostrophe.
- **Web pages of devices** open in a separate tab with no access to the DSM window, and without telling the device where the link came from.

### The API refuses requests from other websites

SynetScan's API runs inside your DSM session, so another website must not be able to use it through your browser:

- **Changes need a POST with a JSON body.** A web page of another origin can make a browser send a form or plain text along with your cookies, but not JSON, without a permission DSM never gives. *JSON requirement available since 1.1.3.*
- **Requests that the browser marks as started by another website are refused** (`Sec-Fetch-Site`). *Available since 1.1.3.* The app then says: *The request was refused because it did not come from the SynetScan window. Open SynetScan from the DSM main menu.*
- Read requests only return data and change nothing.

See [Internal API](Internal-API) for the details.

### What this can't change

The discovery protocols (mDNS, UPnP, NetBIOS, DNS) have no authentication. A device can still lie about its name or model, or pretend to be another device. **Read a device's name as a claim, not as proof.** The MAC address is a better identifier, but it can be faked too. SynetScan helps you notice changes. It isn't an intrusion detection system.

## Privacy

- **Your data stays on the NAS.** SynetScan has no cloud service and sends no telemetry or usage statistics. It doesn't check for updates. The MAC vendor database is bundled with the package.
- **The only network traffic** is what a scan sends to the networks you scan (see [What SynetScan sends to your devices](How-Discovery-Works#what-synetscan-sends-to-your-devices)), **reverse DNS lookups** through the DNS server the NAS is configured to use, and Wake-on-LAN packets when you click **Wake**. If the NAS uses a public DNS server (for example your provider's), that server receives the reverse lookups for your local addresses. Switch off **Reverse DNS lookup** if you don't want that.
- **The log** contains device names, IP and MAC addresses. Remove them before you post log lines publicly. See [Reporting Bugs](Reporting-Bugs).
- **The CSV export** contains your whole inventory, including notes. Treat it like any other internal document.

## Devices in your network may notice the scan

A scan connects to many ports on every device. Some routers, firewalls, antivirus suites or security cameras log this as a "port scan" from the NAS's address. That is expected and harmless, because the scan only connects and disconnects. If a device raises alerts, consider a longer interval, a shorter port list, or switching off **Read web page titles**. Only scan networks you are responsible for.

## Reporting a security problem

If you find a vulnerability, please don't publish the details in a public issue. Open an issue that only asks for a private contact, or use GitHub's private vulnerability reporting if it is enabled for the repository. See [Reporting Bugs and Requesting Features](Reporting-Bugs).

## Related articles

- [Architecture and DSM Integration](Architecture)
- [Data Storage, Retention, Backup, and Reset](Data-Storage-and-Backup)
- [Local Access, QuickConnect, VPN, and DDNS](Local-Access-QuickConnect-VPN-and-DDNS)
