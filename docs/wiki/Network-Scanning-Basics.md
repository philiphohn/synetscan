# Network Scanning Basics

This page explains the ideas behind a network scanner: what it does, which protocols it uses, and why a Synology NAS is a good place to run one. No prior networking knowledge needed.

## What is a network scan?

Every device in your home or office network has an **IP address**, such as `192.168.1.23`, and a **MAC address**, such as `5C:62:8B:10:20:02`, burnt into its network adapter. A network scanner asks every possible address in your network whether something is there, and then asks each device that answers what it is.

The result is an **inventory**: a list of all devices with their addresses, manufacturer, name, type and services. Scanned regularly, the inventory also shows **changes**: a new device joins, a device disappears, a device gets a new address.

Why that's useful:

- **Security.** You notice devices you don't know, such as a neighbour on your Wi-Fi or a forgotten test device.
- **Overview.** You find the address of the printer, the camera or the smart plug without searching the router's menus.
- **Troubleshooting.** You see whether a device is online, which services it offers, and when it was last seen.
- **Documentation.** Names, notes and a CSV export make an inventory of your network.

## Network terms in two minutes

**Subnet.** Devices that can talk to each other directly form a subnet (also called a LAN segment or broadcast domain). It is written like `192.168.1.0/24`: the `/24` means the first three numbers are fixed, so there are 254 usable addresses (`.1` to `.254`). Most home networks are a single /24.

**ARP.** Before a device can send anything to `192.168.1.23` in its own subnet, it has to know that address's MAC address. It asks the whole subnet "who has 192.168.1.23?", and the device with that address answers. This is the Address Resolution Protocol. Each computer keeps the answers in its **ARP table**. A device practically can't refuse to answer ARP: without it, it couldn't communicate at all. That makes ARP the most reliable way to find devices in your own subnet, including devices that block every port.

**MAC address and vendor.** The first half of a MAC address identifies the manufacturer of the network adapter. The IEEE publishes this register, so `00:11:32:…` is Synology and `B8:27:EB:…` is Raspberry Pi. **Private (randomised) MAC addresses**, used by modern phones, tablets and laptops for privacy, are made up and reveal no manufacturer.

**Ports and services.** A device offers services on numbered **TCP ports**: web pages on 80 and 443, file sharing on 445, printing on 9100 and 631, SSH on 22. If a connection attempt to a port is accepted, the port is **open**. If the device rejects it, the port is **closed**, but the device has proved it exists. If nothing comes back, the port is **filtered**: a firewall swallowed the attempt, or there is no device.

**ICMP ping.** The classic "are you there?" message. Many devices ignore it on purpose (Windows does by default), so a scanner that relies only on ping misses devices.

**Names.** Devices have names in several places:

- **DNS**: your router usually registers the names devices give when they ask for an address (DHCP), and answers reverse lookups ("which name has 192.168.1.23?").
- **mDNS/Bonjour**: devices announce their own name (`MacBook-Pro.local`) and services (printer, AirPlay, Chromecast, HomeKit) on the local network. Apple devices, printers, speakers and many smart home devices use it.
- **NetBIOS**: Windows PCs and Samba servers answer with their computer name and workgroup.
- **UPnP/SSDP**: routers, TVs, media servers and game consoles announce themselves and offer a description with their friendly name, manufacturer and model.

**IPv6.** The newer internet protocol. An IPv6 subnet has 18 quintillion addresses, far too many to try one by one. Scanners have to make devices reveal themselves instead. See [IPv6](IPv6).

**Router and routed networks.** The router connects your subnet to other networks: the internet, a guest network, a VLAN for IoT devices. ARP and announcements like mDNS don't cross a router. A scanner sees devices in other subnets only by connecting to them, and doesn't learn their MAC addresses. See [Routed Networks](Interfaces-VLANs-and-Routed-Networks).

## Why run the scanner on a Synology NAS?

A network scanner is only useful if it scans regularly and keeps a history. That needs a machine that is **always on, always in the network, and sits on a cable**. In most homes and small offices, the NAS is that machine.

| Reason | What it means |
| --- | --- |
| **Always on** | Scheduled scans day and night, without a PC that has to stay on. New devices are noticed even when nobody is looking. |
| **Wired and central** | The NAS is usually connected by cable directly to the router or main switch, so it sees the main network as a full member, including ARP. A laptop on Wi-Fi may be in a different segment, or have client isolation. |
| **One inventory for everyone** | All administrators see the same list, names and history in DSM, from anywhere they can reach DSM. |
| **No extra hardware, no cloud** | No Raspberry Pi, no Docker host, no cloud service. The data stays on your NAS. |
| **Light** | A /24 network takes about 10 seconds per scan, once an hour by default. The NAS barely notices. |
| **Part of DSM** | The app opens like any other Synology app, with DSM's sign-in, permissions and look. |

### Why SynetScan works without root

DSM 7 runs third-party packages as unprivileged users, which is good for security. A classic scanner like nmap needs root for its fastest techniques (raw ARP and ICMP packets). SynetScan gets the same results without them:

- It sends a small UDP datagram and a few TCP connection attempts to every address. That alone forces the NAS's kernel to resolve each address with ARP.
- Afterwards, it reads the kernel's ARP table (`/proc/net/arp`), which any user may read. It lists every device that answered ARP, even devices that block every port.
- Names come from DNS, NetBIOS, mDNS and UPnP, all of which work without privileges.

How this plays out in detail: [How Discovery and Identification Work](How-Discovery-Works).

### Compared with other ways to see your devices

| Approach | Pros | Cons |
| --- | --- | --- |
| **Router's client list** | Already there; knows DHCP names | Often only DHCP clients; no history across weeks; no services or types; differs per router brand |
| **Scanner app on a phone or PC** | Quick look, any time | Only while it runs; Wi-Fi only; no history |
| **nmap or similar on a server** | Very powerful | Command line; needs root for ARP and ping scans; you build the history and alerts yourself |
| **SynetScan on the NAS** | Always on, history, new-device flags, DSM interface, no root | Sees only networks the NAS can reach; routed networks without MAC addresses; types are informed guesses |

## A word on responsibility

Scan only networks you own or administer. In your own home and office network that's normal and harmless. A scan is a few connection attempts per address, comparable to what a phone does when it looks for a Chromecast. Some security products in your network may still log or report a scan from the NAS. See the [FAQ](FAQ).

## Related articles

- [How Discovery and Identification Work](How-Discovery-Works)
- [Quick Start: Your First Scan](First-Scan)
- [FAQ and Known Limitations](FAQ)
