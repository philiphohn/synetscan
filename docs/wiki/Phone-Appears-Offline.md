# A phone repeatedly appears offline

← [Troubleshooting](Troubleshooting)

## Symptom

- A phone or tablet keeps switching between *Online* and *Offline*, and the activity log fills with **Went offline** / **Back online** for it, or
- the same phone shows up again and again as a **New device**, with a different MAC address each time, while old entries go offline.

## Likely explanation

**1. Wi-Fi power saving.** A phone with its screen off sleeps most of the time and wakes its Wi-Fi only now and then. During a scan it may not answer ARP or TCP in time. SynetScan already pokes silent addresses twice and reads the ARP table again late in the scan, but a deeply sleeping phone still misses scans now and then. With the default **Mark offline after: 1 missed scan**, a single miss marks it offline, and the next scan that catches it marks it *Back online*.

**2. Rotating private MAC addresses.** Phones, tablets and some laptops use a private (randomised) MAC address per Wi-Fi network. Usually it stays fixed for your network. Some phones can be set to change it regularly, and some do so after a "forget network" or a reset. SynetScan recognises devices by MAC address, so a new MAC address is a new device: it appears as **New**, while the old entry goes offline. Such devices show *Private address* as vendor, and *Randomised (private) MAC address* in the Details tab.

**3. It really leaves.** It's a phone: it goes out of the house, and the log is right.

## Checks

1. Open the device and look at **Details → MAC address**. Does it say *Randomised (private) MAC address*?
2. Filter **Activity → Events** by the device name or search for its host name (e.g. `iPhone`): do *New device* events appear for it with different MAC addresses? That's rotation. Only *Went offline / Back online* pairs, a few hours apart, point to sleeping.
3. Compare the times with your day. Offline overnight and at work is real.
4. On the phone, look at the Wi-Fi settings of your home network: is the private address *Off*, *Fixed* or *Rotating*? The option names depend on the system and version.

## Resolution

**Against sleeping (flip-flopping):**

- Set **Settings → Schedule → Mark offline after** to **2, 3 or 5 missed scans**. A phone then counts as offline only after it has really been gone for a while: with 3 missed scans and an hourly interval, about three hours.
- A shorter interval (for example 15 minutes) together with a higher threshold gives a more accurate picture.

**Against rotating MAC addresses:**

- On the phone, set the private Wi-Fi address for **your home network** to a fixed address, or switch it off for that network. The phone keeps a random address for other networks. The exact setting depends on the system (iOS/iPadOS: Wi-Fi → (i) next to the network → Private Wi-Fi Address; Android: Wi-Fi → network → Privacy → MAC address type) **(names vary by version)**.
- Then clean up: keep the entry with the current MAC address, give it a name and mark it as known, and delete the old entries.

**Against noise in general:**

- Mark the phone as known so it no longer counts as unconfirmed.
- Use the event filter (*New device* only) to see what matters.

## What to include in a bug report

Only if a device on a cable, or with a fixed MAC address, keeps flipping although it is reachable from other computers:

- How the device is connected (cable, Wi-Fi, mesh node)
- Its **Details** (MAC address, Detected via, Interface, Last seen)
- The scan history rows around a flip, and your **Mark offline after** and interval settings
- From the log: `second ARP round …` and `dropping stale ARP entry <its address>` lines, if any

## Related articles

- [Understanding Devices and Their Status](Devices-and-Status)
- [Scan Schedule and Performance](Schedule-and-Performance#mark-offline-after)
- [A device has no MAC address or vendor](No-MAC-or-Vendor)
