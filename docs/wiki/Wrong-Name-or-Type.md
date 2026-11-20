# A device has the wrong name or type

← [Troubleshooting](Troubleshooting)

## Symptom

- A device has a cryptic name (`esp32-c3f1a0`, a vendor name, an IP address), a name that's out of date, or the name of another device.
- The type icon and the **Type** column are wrong, for example a laptop shown as *Phone*, or a TV as *Unknown*.

## Likely explanation

**Where names come from.** Without a custom name, SynetScan uses the first meaningful name in this order: UPnP/Bonjour friendly name → mDNS host name → NetBIOS name → DNS name → (for the gateway) the model → MAC vendor → web page title → address. Cryptic names are what the device itself announces, or what your router registered for it. Junk such as random IDs, UUIDs, generic UPnP class names and (since 1.1.5) the host names Android makes up (`Android_K7QX2M4P`) is skipped. See [Where the name comes from](Devices-and-Status#where-the-name-comes-from).

**Old values stay.** A scan only overwrites a detail it finds again. If a device stops announcing a name (Bonjour off, asleep, new firmware), the old name stays in the record. This is why a device can keep a name it no longer uses.

**Names from another device.** In networks with a router that answers ARP for VPN clients (proxy ARP), versions before 1.1.2 could merge names of the clients into the router's record. Current versions split them and remove those names. A DNS server that has stale entries can also give a device another device's old name.

**Types are guesses.** The type is derived from the vendor, open ports, services and names. A device with a private MAC address reveals no vendor, and a device with no open ports gives little to go on. Some devices look alike: a Mac with AirPlay receiver enabled has AirPlay like an Apple TV, and a Samsung address is usually a TV but can be a phone.

**Names can be false.** Every name comes from the network. A device can announce any name it likes.

## Checks

1. Open the device: **Details** shows **Detected name** and every name source (DNS name, mDNS name, NetBIOS name, Model, UPnP device, Web page). Which one is wrong or outdated?
2. **General → Device type** shows the automatic guess as **Automatic (…)**.
3. **Services** shows the open ports and Bonjour services the guess was based on.
4. For DNS names: check what your router or DNS server lists for that address.

## Resolution

- **Set a custom name and type** in the device dialog (General tab). Your values always win and are never changed by scans. See [Managing Names, Types, and Notes](Names-Types-and-Notes).
- **To have everything detected afresh**, delete the device. The next scan creates a new record with only current information. It appears as **New** with a *New device* event, and your name and notes for it are gone, so note them first.
- **Outdated DNS names**: fix or remove the entry on your router or DNS server, then delete and rediscover the device. Or switch off **Reverse DNS lookup**.
- **Improve the type guess**: add ports the device uses to **Settings → Ports** (for example 3306 or 5432 for database servers). See [Custom Port Lists](Custom-Port-Lists).

## What to include in a bug report

If SynetScan picks an obviously bad name or type for a common device, a report helps improve the rules for everyone:

- The device (manufacturer, model) and what you expected
- From **Details**: Vendor (or *Private address*), Model, DNS/mDNS/NetBIOS names, UPnP device, Web page, Detected via
- From **Services**: the open ports and mDNS services
- The automatic type shown in **Automatic (…)**

Replace personal parts of names (such as "Anna's iPhone") with placeholders.

## Related articles

- [Understanding Devices and Their Status](Devices-and-Status)
- [How Discovery and Identification Work](How-Discovery-Works#classification)
- [Managing Names, Types, and Notes](Names-Types-and-Notes)
