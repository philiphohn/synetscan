# A device has no MAC address or vendor

← [Troubleshooting](Troubleshooting)

## Symptom

- The **MAC address** column shows *–*, or
- the **Vendor** column shows *Private address* or *–*.

## Likely explanation

**No MAC address.** SynetScan learns MAC addresses from the NAS's ARP table (IPv4) and neighbour table (IPv6). Both only contain devices on the NAS's own network segments. A device has no MAC address in SynetScan when:

- **it's in a routed network** (an additional range behind a router). ARP doesn't cross routers. The only exception is Windows PCs and Samba servers, whose NetBIOS answer includes their MAC address;
- **another device answers ARP for its address** (proxy ARP), typically a router answering for its VPN clients. The MAC address belongs to the router, so SynetScan keeps it there. The Details tab shows **Reached through** with the router's MAC address;
- it was found only through an mDNS or UPnP announcement and didn't answer ARP in time (rare).

Without a MAC address, the device is recognised by its IP address. A new IP address therefore looks like a new device, and **Wake** isn't possible.

**No vendor.**

- **Private MAC address** (*Private address*): phones, tablets, and laptops with Wi-Fi privacy enabled use a made-up, "locally administered" address. It's not registered to any manufacturer, so there's no vendor to show. The Details tab says *Randomised (private) MAC address*.
- **The vendor isn't in the database.** SynetScan bundles the IEEE registry as published by the Wireshark project, with about 59,000 entries. Very new prefixes, or prefixes of small manufacturers, may be missing. Virtual adapters (Docker, VMs) often use unregistered addresses too.
- **No MAC address at all** (see above) means no vendor either.

## Checks

1. **Details → Interface**: *custom* means the device came from an additional range, so it's routed.
2. **Details → Reached through**: present means proxy ARP.
3. **Details → MAC address**: *Randomised (private) MAC address* explains a missing vendor.
4. Look up the MAC prefix (the first six hex digits) in an online OUI database. If it is registered there, the bundled database may be older.

## Resolution

| Cause | What you can do |
| --- | --- |
| Routed network | Expected. To get MAC addresses, give the NAS an interface in that network (for example a VLAN interface), so the network is no longer routed. Give routed devices fixed IP addresses so their records stay stable. |
| Proxy ARP (VPN clients) | Expected. The address is a client behind the router. |
| Private MAC address | Expected. Name the device yourself. On your own devices you can switch off the private address for your home network. See [Phone-Appears-Offline](Phone-Appears-Offline#resolution). |
| Vendor missing from the database | A newer SynetScan release may know it. Maintainers update the database with `tools/build_oui.py` (see [Contributing](Contributing#vendor-database)). You can [report the prefix](Reporting-Bugs). |

## What to include in a bug report

Only if a device in the NAS's own network, on a cable, has no MAC address:

- **Details**: IP address, Interface, Detected via, Reached through (if shown)
- Whether the device's MAC address appears in your router's client list
- Log lines mentioning `proxy ARP`

For a missing vendor: the first six hex digits of the MAC address and the manufacturer, if you know it.

## Related articles

- [Multiple Interfaces, VLANs, and Routed Networks](Interfaces-VLANs-and-Routed-Networks)
- [Understanding Devices and Their Status](Devices-and-Status)
- [Network Scanning Basics](Network-Scanning-Basics)
