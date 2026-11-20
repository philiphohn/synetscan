# Multiple Interfaces, VLANs, and Routed Networks

Most homes have one network, and SynetScan needs no configuration for it. This page is for everything else: a NAS with several network ports, VLANs, Docker and virtual machines, VPNs, and networks behind a router.

## A NAS with several network ports

SynetScan scans the network of **every** physical interface that is up and has an address. A NAS connected to two networks, say `eth0` in `192.168.1.0/24` and `eth1` in `10.10.0.0/24`, scans both. **Settings → Scan Targets** lists each interface with a checkbox.

- **Unticking** an interface leaves its network out of IPv4 and IPv6 discovery. Use this for storage or backup networks, or a direct link to another server.
- An interface without a link (*(down)*), or with only a self-assigned `169.254.x.x` address, is skipped automatically.
- **Link aggregation**: a bond (`bond0`) is a normal interface and is scanned.
- **The NAS itself appears once.** If several of its ports are connected, SynetScan merges them into one **This NAS** entry. It keeps the address of the port with the default gateway (or the first one) and lists the others under **Other IP addresses** in the Details tab, with their interface, for example `10.10.0.5 (eth1)`.
- Devices found on the second network show its interface (`eth1`) under **Interface** in the Details tab.

> Tested on a DS923+ with two LAN ports in an office network.

## Open vSwitch (Virtual Machine Manager)

When Virtual Machine Manager is installed or Open vSwitch is enabled, DSM moves the NAS's address onto an interface like `ovs_eth0`. SynetScan treats it as a physical interface and scans it as usual. *Tested on a DS1813+ (DSM 7.1.1) with Open vSwitch.*

Virtual machines in VMM bridged into your LAN are normal devices in that network. SynetScan finds them and types them as **Virtual machine** when their vendor (for example QEMU) shows it.

## Docker / Container Manager

Container Manager creates bridge interfaces (`docker0`, `br-…`, `veth…`) with private networks such as `172.17.0.0/16`. SynetScan **skips them** automatically: the containers are on the NAS itself, and scanning these networks would only take time.

To scan a Docker network anyway, add it as an additional range, for example `172.17.0.0/24`.

## VLANs

A VLAN is a separate network on the same cables. There are two cases:

1. **The NAS has an interface in the VLAN** (DSM: VLAN ID on the network interface). The VLAN interface is listed in **Scan Targets** like any other and is scanned automatically, with MAC addresses, Bonjour names and everything else.
2. **The VLAN is only reachable through a router** (the usual case for guest or IoT VLANs). It's a routed network: add it as an additional range. See below.

## Routed networks (custom ranges)

Any network the NAS reaches through a router can be scanned by adding it under **Settings → Scan Targets → Additional ranges**. Common examples are an IoT VLAN, a second site over a site-to-site VPN, or a lab network. The [step-by-step guide](Scan-Targets#guide-scan-another-vlan-or-subnet) is on the Scan Targets page.

What's different in a routed network:

| Aspect | In the NAS's own network | In a routed network |
| --- | --- | --- |
| Discovery | TCP, ARP table, mDNS, SSDP, ping | TCP to 9 discovery ports and ping only. Devices that block all of these aren't found. |
| MAC address and vendor | Yes, from ARP | **No**: ARP only works on the local segment. Exception: Windows and Samba devices report their MAC address in their NetBIOS answer. |
| Device identity | MAC address | **IP address** (`ip:192.168.20.15` internally). A new IP address looks like a new device. |
| Names | DNS, NetBIOS, mDNS, UPnP | DNS and NetBIOS. mDNS and SSDP don't cross routers. |
| Type | Vendor, ports, names, services | Ports and the few names, so less reliable |
| Wake-on-LAN | Yes | No (no MAC address, and broadcasts don't cross routers) |
| Interface in Details | `eth0` etc. | *custom* |

Tips:

- **Give routed devices fixed addresses** (DHCP reservations on the router). Their record is tied to the IP address.
- **Allow the NAS through the firewall** between the networks: at least TCP to the ports you want to see, and ICMP echo if you [enable ping](Enabling-ICMP-Ping).
- **If you need MAC addresses and Bonjour names for a VLAN**, give the NAS an interface in that VLAN instead of scanning it through the router (case 1 above).

## Proxy ARP and VPN clients

Some routers answer ARP requests on behalf of other devices, for example for VPN clients that seem to be in the LAN but are actually connected through a tunnel. They answer with their **own** MAC address for each client's IP address.

SynetScan detects this: if one MAC address answers for several addresses, the MAC address stays with one device (the gateway, if it's among them, otherwise the lowest address). Each of the other addresses becomes a device of its own, without a MAC address. Its Details tab shows:

> **Reached through**: The device with MAC address 00:1D:AA:… answers for this address (proxy ARP, e.g. a router for VPN clients).

> Tested on a DS923+ in a network with a VPN router using proxy ARP.

## VPNs and Tailscale on the NAS

VPN and overlay interfaces on the NAS itself (`tun…`, `tap…`, `wg…`, `tailscale…`, `zt…`) are virtual and skipped automatically. Devices behind them are routed devices, without MAC addresses. To scan them, add their range as an additional range.

Overlay networks such as Tailscale use large address spaces (100.64.0.0/10 has over four million addresses). An additional range may cover at most 65,536 addresses, so enter specific small ranges or single addresses instead.

How VPNs affect **Open Web Interface** is explained in [Local Access, QuickConnect, VPN, and DDNS](Local-Access-QuickConnect-VPN-and-DDNS).

## Large networks

Interface networks larger than *Maximum hosts per interface network* (default /22, 1022 hosts) are reduced to the block around the NAS's address. To cover more, raise the limit up to /19 (8190 hosts), or add the whole network as an additional range (up to a /16). Expect longer scans, and consider a longer interval. See [Scan Schedule and Performance](Schedule-and-Performance).

## Related articles

- [Scan Targets and Custom Ranges](Scan-Targets)
- [How Discovery and Identification Work](How-Discovery-Works)
- [A device has no MAC address or vendor](No-MAC-or-Vendor)
- [IPv6 Discovery and Addresses](IPv6)
