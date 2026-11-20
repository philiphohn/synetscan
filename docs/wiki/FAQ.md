# Frequently Asked Questions and Known Limitations

## General

**What is SynetScan?**
A network scanner that runs as a package on a Synology NAS with DSM 7. It finds the devices on your network, identifies them, keeps a history and flags new devices. See [Home](Home).

**Is it free?**
Yes. SynetScan is free software under the GNU General Public License v3 or later. You may use it for any purpose, including commercially.

**Is it an official Synology app?**
No. It is an independent project and isn't signed by Synology, which is why DSM warns about an unknown publisher during installation.

**Which NAS models are supported?**
Every model with DSM 7.0 or newer. The package is `noarch`. It was tested on a DS220+, a DS923+ and a DS1813+. ARM models haven't been tried yet but should work. See [Requirements](Requirements-and-Compatibility).

**Does it work on DSM 6?**
No. DSM 7.0 is the minimum.

**Do I need Docker, root access or the command line?**
No. Everything works in DSM. SSH is only needed for optional tasks such as [enabling ping](Enabling-ICMP-Ping) or reading the log.

**Which languages are available?**
English and German. The app follows your DSM language: German if DSM is set to German, English for every other language. Translations are welcome: see [Contributing](Contributing#translations).

**Is there a mobile app?**
No. SynetScan runs in DSM's desktop interface in a browser.

## Scanning

**How long does a scan take?**
About 8 to 15 seconds for a typical /24 network. Larger and routed networks take longer. See [Performance](Schedule-and-Performance#how-long-will-a-scan-take).

**Does scanning slow down my network or the NAS?**
Hardly. A scan of a /24 network is a few thousand short connection attempts, spread over a few seconds, once an hour by default. You can reduce **Parallel probes** if you have a very slow NAS or a sensitive router.

**My router / firewall / antivirus reports a port scan from the NAS.**
That's SynetScan. It connects to several ports on every device. It's harmless, but if the alerts bother you, use a longer interval or a shorter port list, or add an exception for the NAS in that product. See [Security](Security-and-Privacy#devices-in-your-network-may-notice-the-scan).

**Why does SynetScan find devices that don't answer ping?**
Because it doesn't rely on ping. In the local network, every device has to answer ARP, and SynetScan reads the NAS's ARP table after poking every address. See [How Discovery Works](How-Discovery-Works).

**Why is ping "not available on this system"?**
DSM runs packages as unprivileged users, and on most systems the `ping` program doesn't work for such users. It isn't needed for local networks. To enable it, see [Enabling ICMP Ping](Enabling-ICMP-Ping).

**Can SynetScan scan other networks, VLANs or remote sites?**
Yes, as additional ranges, if the NAS can reach them. Devices there are found without MAC addresses. See [Routed Networks](Interfaces-VLANs-and-Routed-Networks).

**Can I scan a single address or exclude one?**
You can scan single addresses as additional ranges. There is no exclusion list. Instead, untick the automatic scan and enter the ranges around the address. See [Scan Targets](Scan-Targets#other-uses-of-additional-ranges).

**Does SynetScan scan UDP ports?**
No. The port scan is TCP only. mDNS, SSDP, NetBIOS and WS-Discovery are queried through their own protocols.

**Can I scan the internet or public addresses?**
SynetScan accepts any IPv4 range, but it's meant for your own networks. Only scan networks you are responsible for.

**How many devices can it handle?**
Up to 65,536 addresses per scan and 8,192 devices in the list.

## Devices

**What's the difference between "New" and "Unconfirmed"?**
They describe the same devices: those you haven't marked as known. "New" is the badge, "Unconfirmed" the filter and tile. The *New in 24 h* tile counts only devices first seen in the last 24 hours. See [Devices and Status](Devices-and-Status#known-unconfirmed-and-new).

**Why are all devices of my first scan already "known"?**
The first scan is the baseline: what's on your network when you install SynetScan. Only devices joining later are flagged. See [First Scan](First-Scan#what-the-baseline-means).

**Why does my NAS appear only once although it has two network ports?**
SynetScan merges the NAS's own addresses into one entry. The other addresses are listed in its Details tab.

**Why is "Response time" empty for most devices?**
It is measured by ping only, and only for devices that didn't answer on a TCP discovery port. Most devices answer TCP first, and ping is often unavailable.

**Why do so many devices say "Private address"?**
Phones, tablets and laptops use randomised MAC addresses for privacy, which reveal no manufacturer. See [No MAC or Vendor](No-MAC-or-Vendor).

**Can SynetScan tell me who is on my Wi-Fi?**
It tells you which devices are on your network and when new ones appear. It can't tell who owns them. Names and types are what the devices announce.

**Can I block a device?**
No. SynetScan only observes. Block devices in your router.

## Notifications and integrations

**Does SynetScan send e-mail or push notifications for new devices?**
Not at the moment. New devices are flagged in the app and logged in the activity log. You can [request the feature](Reporting-Bugs).

**Is there an API for Home Assistant or scripts?**
SynetScan has an internal API used by its own web interface. It requires a DSM administrator session and isn't a supported integration interface: it can change without notice. See [Internal API](Internal-API).

**Can I export the device list?**
Yes, as CSV: **Devices → Action → Export**. See [CSV Export](Device-Actions-and-CSV-Export#csv-export).

## Privacy and security

**Does SynetScan send data to the internet?**
No. There is no cloud service, no telemetry and no update check. Reverse DNS lookups go to the DNS server your NAS uses. See [Privacy](Security-and-Privacy#privacy).

**Who can see the device list?**
Only DSM administrators. See [Security](Security-and-Privacy).

## Known limitations

- **IPv6-only devices need to answer something.** Without root, SynetScan can't sweep an IPv6 network. It finds IPv6-only devices that answer mDNS, UPnP or WS-Discovery, that talk to the NAS, or (where the system allows unprivileged ping) that answer an echo to all nodes. Most home devices also use IPv4, and the IPv4 scan finds them regardless.
- **Link-local only devices.** Web interfaces of IPv6-only devices can only be opened when they have a global or unique-local address. Browsers can't open `fe80::` addresses.
- **Routed networks have no MAC addresses.** Devices in networks reached through a router (custom ranges) are found by TCP and ping only. They show up without a MAC address, so no vendor lookup is possible, and they are recognised by IP address.
- **Device types are guesses.** Many devices hide behind private (randomised) MAC addresses. Correct the type in the device dialog.
- **Rotating private MAC addresses** make a device look new each time it changes its address.
- **Docker hosts.** When Container Manager is installed, the `docker*`/`veth*` bridges are skipped automatically. Add a range under custom ranges if you want to scan one anyway.
- **No ignore or exclusion list.** Deleted devices come back as new when found again.
- **No notifications**, and no read-only access for non-administrators.
- **ICMP ping** depends on the system's `ping` working for the package user, which it usually doesn't on DSM.
- **No Log tab in Package Center** on DSM 7.4 for third-party packages. Read the log over SSH or with a scheduled task. See [Logs](Logs-and-Diagnostics).
- **ARM models not tried yet.** SynetScan contains no compiled code, so they should work.
- **Open Web Interface needs local access** and only uses a fixed set of web ports.

## Related articles

- [Troubleshooting](Troubleshooting)
- [Reporting Bugs and Requesting Features](Reporting-Bugs)
- [Network Scanning Basics](Network-Scanning-Basics)
