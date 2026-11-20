# How Discovery and Identification Work

This page follows a scan from start to finish, as the code does it. The scan phases in the app (*Preparing*, *Discovering devices*, *Identifying devices*, *Verifying*) map onto the steps below.

All of it runs as the unprivileged package user. SynetScan uses no raw sockets and no root privileges, and builds no shell commands from network input.

## Overview

```
Preparing      interfaces, gateways, target list
Discovering    ┌ mDNS browse + SSDP search (multicast, in the background)
               └ every address: UDP datagram + TCP connects to 9 ports (+ ping if available)
               → read the ARP table · poke silent addresses again
               → IPv6 discovery starts in the background
Identifying    every device: port scan → reverse DNS → NetBIOS → mDNS → UPnP description → web page title
               → MAC vendor; late ARP answers get identified too
Verifying      devices known only from the ARP cache are checked once more
Finishing      merge the NAS's own ports · merge IPv6 · classify · save · events
```

## 1. Preparing

- SynetScan reads the NAS's IPv4 interfaces (with `ip -o -4 addr`, or directly from the kernel if `ip` is missing), each interface's link state and speed, and the default gateways from `/proc/net/route`.
- It builds the **target list**: the networks of the ticked physical interfaces, limited by *Maximum hosts per interface network*, plus your additional ranges. See [Scan Targets](Scan-Targets).
- It decides whether ping can be used: **ICMP ping** must be on, and the system `ping` must work for the package user. See [Enabling ICMP Ping](Enabling-ICMP-Ping).

## 2. Discovering devices

**Multicast discovery (background).** While the sweep runs, SynetScan listens for devices that announce themselves:

- **mDNS/Bonjour**: a DNS-SD query for all service types to `224.0.0.251:5353`, then queries for each type found plus a set of common ones (`_http`, `_workstation`, `_smb`, `_airplay`, `_googlecast`, `_ipp`, `_printer`, `_raop`, `_device-info`, `_companion-link`, `_hap`, `_spotify-connect`, `_ssh`, `_sonos`, `_homekit`). The answers carry host names, service instances, models and IPv6 addresses.
- **SSDP/UPnP**: an `M-SEARCH` for all devices (`ssdp:all`) to `239.255.255.250:1900`, sent twice. The answers carry the URL of each device's description and its `Server` header.

Both are sent from every physical interface that is up, and each takes about 2.5 seconds. Since version 1.1.5, the Bonjour browse gets a head start of up to two seconds before the sweep begins, and repeats its questions once. A device that is being probed sometimes answers late, without its host name, or not at all.

**The sweep.** For every address in the target list (except the NAS's own), in parallel (*Parallel probes*):

1. a one-byte UDP datagram to port 9 (discard). It needs no answer: its job is to make the NAS's kernel resolve the address with ARP;
2. TCP connection attempts to **80, 443, 22, 445, 62078, 8080, 1400, 8001 and 8009** at once, each waiting up to the *Probe timeout*. An accepted connection (open) or a rejection (closed) proves the device exists;
3. if nothing answered and ping is available: one ping with a one-second timeout.

**The ARP table.** After the sweep, SynetScan reads `/proc/net/arp`. Every address with a complete entry has answered ARP, so it is a device, even if it ignored everything else. Devices that only announced themselves over mDNS or SSDP are added too, if their address is in the target list.

**Second chance for sleepers.** Devices in Wi-Fi power saving (phones, speakers, TVs in standby) often miss the first ARP requests. SynetScan sends every silent address one more datagram. Their ARP entries are read again after the identification phase, which gives slow sleepers time to answer.

**Proxy ARP.** If one MAC address answers for several addresses, as a router does for its VPN clients, that MAC address belongs to only one of them: the gateway if it's among them, otherwise the lowest address. The other addresses become devices of their own without a MAC address. Their Details tab shows **Reached through**.

**IPv6** discovery starts now, in the background. See [IPv6](IPv6).

## 3. Identifying devices

For each device found, in parallel (half the *Parallel probes*, at least 8):

| Step | What SynetScan does | What it yields |
| --- | --- | --- |
| **Port scan** | TCP connection attempts to the ports of **Settings → Ports**, 32 at a time, each group waiting up to *timeout + 0.3 s* | Open ports (Services) |
| **Reverse DNS** | `PTR` lookup through the NAS's resolver | DNS name |
| **NetBIOS** | Node status query to UDP 137 (0.8 s) | Computer name, workgroup, MAC address (also for routed devices) |
| **mDNS** | Uses what the device announced during the browse. If it answered without its host name, SynetScan asks the device directly for its `.local` name and addresses; if it gave its name but no IPv6 addresses, SynetScan asks it for the addresses (*since 1.1.5*). If it didn't answer the browse at all, SynetScan asks it for its name by reverse lookup (0.6 s). | `.local` name, services, model, friendly name, IPv6 addresses |
| **UPnP** | Fetches the device description announced over SSDP, from the device that announced it only. Tries up to four announced descriptions in turn (*since 1.1.5*), within 8 seconds. | Friendly name, manufacturer, model name and number, device type |
| **Web page** | `GET /` on the first open port of 80, 8080, 443 and 5000, following redirects on the same device only, within 8 seconds per device | Page title and `Server` header |
| **Vendor** | Looks up the MAC prefix in the bundled IEEE database (about 59,000 entries) | Vendor; whether the MAC address is private |

Every answer is treated as untrusted input: text is cleaned of invisible characters and cut to a fixed length, answer sizes are limited, and XML with a DOCTYPE is refused. See [Security](Security-and-Privacy).

**Late ARP answers.** SynetScan reads the ARP table once more. Addresses that have appeared since the second datagram (waiting at least three seconds for them) are identified the same way.

## 4. Verifying

The kernel keeps ARP entries for a while after a device has left. A device known only from the ARP cache, with no open ports, could therefore be a ghost. SynetScan waits until about **8 seconds** after the sweep, reads the ARP table again, and drops such devices if their entry is gone. That's the *Verifying* phase. It only happens when there are such devices.

## 5. Finishing

- **The NAS itself.** A NAS with several connected ports would answer under each address. SynetScan merges them into one **This NAS** entry, keeping the port with the default gateway and listing the others under **Other IP addresses**.
- **IPv6.** IPv6 addresses are attached to the devices found over IPv4 (matched by MAC address and by mDNS host name). IPv6-only devices are port-scanned and identified like the others. See [IPv6](IPv6).
- **Classification** (see below), and the **Gateway** flag for the default gateway.
- **Saving.** The result is merged into the device list, events are recorded, and the scan is added to the history. See [Understanding Devices and Their Status](Devices-and-Status).

## Classification

The device type comes from rules applied in a fixed order. The first rule that matches decides. In short:

1. **NAS**: the NAS itself; vendor Synology, QNAP, Asustor or TerraMaster; ports 5000 **and** 5001; names like *DiskStation*. Also Western Digital, Buffalo or Netgear devices with file sharing ports and "nas" in the name.
2. **Router**: the default gateway; a UPnP *InternetGatewayDevice*; names like *FRITZ!Box*, *Speedport*, *router*; AVM devices with web or DNS ports.
3. **Virtual machine**: vendor VMware, QEMU, Xen, Parallels, VirtualBox or Proxmox, or a Hyper-V MAC address.
4. **Telephony** (*since 1.1.9*): telephony vendors (Mitel/Aastra, Snom, Yealink, Grandstream, Poly/Polycom, Avaya, Gigaset, Fanvil, Unify, Auerswald, Agfeo, innovaphone…); SIP ports 5060 or 5061; names and page titles like *MiVoice*, *FreePBX*, *Asterisk*, *3CX*, *PBX*, *VoIP*. Routers and the NAS are recognised before, so a FRITZ!Box with its built-in phone system stays a router.
5. **Printer**: ports 9100 or 515; printer or scanner services (`_ipp`, `_printer`, `_uscan`…); names like *LaserJet*, *PIXMA*.
6. **Camera**: port 554; camera vendors (Hikvision, Dahua, Axis, Reolink…); names like *camera*, *doorbell*, *NVR*.
7. **Game console**: Nintendo, Sony Interactive; names like *PlayStation*, *Xbox*, *Steam Deck*.
8. **Speaker**: port 1400; Sonos, Bose, Harman, Denon, Yamaha, Bang & Olufsen; Spotify Connect without AirPlay/Cast; names like *HomePod*, *Echo*, *soundbar*.
9. **TV & Media**: Cast, AirPlay, Android TV or Roku services (but not Macs); port 8009 or the Samsung TV ports; UPnP *MediaRenderer*; TV vendors; names like *Chromecast*, *Apple TV*, *Fire TV*, *Bravia*.
10. **Tablet**: names like *iPad*, *Galaxy Tab*, *Kindle*.
11. **Smartphone**: port 62078; names like *iPhone*, *Android*, *Galaxy*, *Pixel*; phone vendors.
12. **Smart home**: IoT chip and smart home vendors (Espressif, Tuya, Shelly, Signify, Nest, Ring, Sonoff, Bosch, Homematic…); ports 1883 or 8123; HomeKit, MQTT or Hue services; names like *Tasmota*, *ESP32*, *Home Assistant*.
13. **Network device**: network vendors such as Ubiquiti, TP-Link, Netgear, Cisco, Zyxel, MikroTik, D-Link, Linksys, LANCOM, DrayTek and devolo; names like *switch*, *access point*, *repeater*, *mesh*, *Deco*.
14. **Computer**: port 3389; Mac and PC names; workstation or companion-link services; SMB with a NetBIOS name.
15. **Server**: SSH together with web, database or mail ports; names like *server*, *ubuntu*, *debian*, *proxmox*.
16. Fallbacks: Raspberry Pi (Server with SSH, otherwise Smart home); Apple (Smartphone without open ports, otherwise Computer); Samsung (Smartphone with a private MAC or port 62078, otherwise TV & Media); PC vendors (Computer); private MAC without open ports (Smartphone); SSH (Server); IPv6 router announcements (Router; Thread border routers such as HomePods also send these, so this is the weakest signal).
17. Otherwise **Unknown**.

The rules are heuristics. Your own type in the device dialog always wins. If a rule regularly gets one of your devices wrong, please [report it](Reporting-Bugs) with the device's vendor, open ports, services and names.

## What SynetScan sends to your devices

| To | What |
| --- | --- |
| Every scanned address | A one-byte UDP datagram to port 9; TCP connection attempts to 9 ports; one ping (only if ping is available and nothing else answered) |
| Every device found | TCP connection attempts to the configured ports, closed again without sending data; a NetBIOS query (UDP 137); an mDNS query (UDP 5353) if needed |
| Devices with web ports | `GET /` with the user agent `Mozilla/5.0 SynetScan` |
| Devices announcing UPnP | `GET` of their announced description, user agent `SynetScan/1.0 UPnP/1.1` |
| The local network (multicast) | mDNS and SSDP queries over IPv4 and IPv6, WS-Discovery over IPv6 |
| The NAS's DNS server | Reverse lookups for every device found |

SynetScan never logs in anywhere, sends no passwords and changes nothing on any device. The only other packet it sends is the Wake-on-LAN packet when you click **Wake**.

## Related articles

- [Network Scanning Basics](Network-Scanning-Basics)
- [IPv6 Discovery and Addresses](IPv6)
- [Ports and Discovery Options](Ports-and-Discovery)
- [Architecture and DSM Integration](Architecture)
