# A device or part of my subnet is missing

← [Troubleshooting](Troubleshooting)

## Symptom

- A device you know is on the network doesn't appear in the device list, or
- devices in part of your address range never appear (for example nothing above `192.168.3.x`), or
- devices of another network (a VLAN, a guest network, a second site) are missing.

## Likely explanations

In the NAS's own network, SynetScan finds practically every device that is switched on: even a device that blocks every port has to answer ARP, and SynetScan reads the NAS's ARP table after poking every address. When a local device is missing, it is usually one of these:

1. **It wasn't there, or was asleep, during the scan.** Devices in Wi-Fi power saving (phones, tablets, speakers, e-readers, TVs in standby) sometimes miss even the second ARP attempt. Devices that are switched off can't be found.
2. **Its address isn't among the scan targets.**
   - The interface it's on is unticked in **Settings → Scan Targets**, or the automatic scan is off.
   - The network is larger than **Maximum hosts per interface network** (default /22, 1022 hosts). SynetScan then scans only the block around the NAS's address. A `/16` home network, for example, is scanned only partly.
   - The interface is down, has only a `169.254.x.x` address, or is a virtual interface (Docker, VPN, tunnel), which is skipped automatically.
3. **It's in another network behind a router.** Routed networks aren't scanned unless you add them. There, discovery has no ARP table: a device must answer on one of the discovery ports (80, 443, 22, 445, 62078, 8080, 1400, 8001, 8009), or answer ping if ping is available.
4. **It was dropped as a stale ARP entry.** A device known only from the ARP cache, with no open ports, is checked again about 8 seconds after the sweep. If its entry has disappeared by then, SynetScan assumes it has left. Rarely, a device that answers very briefly falls through.
5. **Client isolation or a separate Wi-Fi segment.** Guest Wi-Fi and some mesh systems keep wireless clients apart from the wired network. Such devices aren't in the NAS's network at all.
6. **It has only IPv6** and answers none of the IPv6 discovery methods. See [IPv6](IPv6#limits-of-ipv6-discovery).

## Checks

1. **Activity → Scan History → Ranges** (or the Overview's **Scanned ranges**): is the device's address inside one of the listed ranges?
2. **Overview → Network**: which interfaces and networks does the NAS have? Is the device in one of them?
3. **Settings → Scan Targets**: is the interface ticked? Is the limit smaller than your network?
4. Is the device on right now? Can another computer reach it, for example with `ping` or its web page?
5. Check your router's client list: which IP address does the device have, and is it in the same network as the NAS?
6. Run **Scan Now** while the device is active (screen on, playing music), and look again.
7. If it still doesn't show up, look at the [log](Logs-and-Diagnostics) for this scan: the `scan started` line (number of targets, ranges), `second ARP round found …` and `dropping stale ARP entry …` lines.

## Resolution

| Cause | Fix |
| --- | --- |
| Asleep during the scan | Usually solves itself with the next scan. If it happens often, raise **Settings → Schedule → Mark offline after** so known devices don't flip to offline. See [Phone-Appears-Offline](Phone-Appears-Offline). |
| Interface unticked or automatic scan off | Tick it in **Scan Targets** and click **Apply**. |
| Network larger than the limit | Raise **Maximum hosts per interface network** (up to /19, 8190 hosts), or add the whole network as an additional range (up to /16). Scans take longer. See [Scan Targets](Scan-Targets#maximum-hosts-per-interface-network). |
| Another network behind a router | Add it under **Additional ranges**. Make sure the router or firewall lets the NAS connect. Consider [enabling ping](Enabling-ICMP-Ping). See [Routed Networks](Interfaces-VLANs-and-Routed-Networks#routed-networks-custom-ranges). |
| Virtual interface (Docker, VPN) | Add its range under **Additional ranges**. |
| Client isolation, guest Wi-Fi | Allow access from the NAS in the router, or accept that guest devices are separate. |
| Firewalled device in a routed network | Allow at least one of the discovery ports or ICMP echo from the NAS's address. |
| IPv6-only device | See [IPv6](IPv6). |

## What to include in a bug report

If a device in the NAS's own network is reliably missing although it is on and reachable from other computers:

- SynetScan and DSM version, NAS model
- The device's IP address and network, with the first parts anonymised if you like (e.g. `192.168.x.57/24`), and the NAS's network from **Overview → Network**
- The **Scan History** row (duration, found, ranges)
- From the log: the `scan started` line and any lines mentioning the device's address
- What the device is (vendor, model) and whether it's on Wi-Fi or cable

## Related articles

- [Scan Targets and Custom Ranges](Scan-Targets)
- [How Discovery and Identification Work](How-Discovery-Works)
- [Multiple Interfaces, VLANs, and Routed Networks](Interfaces-VLANs-and-Routed-Networks)
