# Troubleshooting

Find your symptom below. Each entry follows the same pattern: **symptom → likely explanation → checks → resolution → what to include in a bug report.** Longer entries have a page of their own.

Problems with installing or opening the app are covered in [Installing SynetScan](Installation#5-common-problems) and [Logs and Diagnostics](Logs-and-Diagnostics#error-messages).

| Symptom | Page |
| --- | --- |
| A device or part of my subnet is missing | [Missing-Devices](Missing-Devices) |
| A phone repeatedly appears offline (or as new) | [Phone-Appears-Offline](Phone-Appears-Offline) |
| A device has the wrong name or type | [Wrong-Name-or-Type](Wrong-Name-or-Type) |
| A device has no MAC address or vendor | [No-MAC-or-Vendor](No-MAC-or-Vendor) |
| A deleted device reappears | [below](#a-deleted-device-reappears) |
| "Open web interface" is disabled | [Open-Web-Interface-Disabled](Open-Web-Interface-Disabled) |
| SynetScan does not open correctly after an update | [Problems-After-Update](Problems-After-Update) |
| Older activity entries are missing | [below](#older-activity-entries-are-missing) |

---

## A device or part of my subnet is missing

**Symptom.** A device you know is on the network isn't listed, or whole ranges of addresses are never found.

**Likely explanation.** The device was off or asleep during the scan, its address isn't in the scan targets (large networks are limited to /22 around the NAS by default), or it is in another network behind a router.

**Checks.** Activity → Scan History → **Ranges**; Settings → Scan Targets; whether the device answers from another computer.

**Resolution.** Fix the targets, raise the limit or add a custom range, and give sleeping devices a second chance with the next scan.

**Full entry:** [A device or part of my subnet is missing](Missing-Devices)

---

## A phone repeatedly appears offline

**Symptom.** A phone or tablet flips between *Went offline* and *Back online*, or reappears as a **New** device.

**Likely explanation.** Wi-Fi power saving makes phones miss scans. Private MAC addresses that rotate make a phone look like a new device.

**Resolution.** Raise **Mark offline after**, and use a fixed private address for your home Wi-Fi on the phone.

**Full entry:** [A phone repeatedly appears offline](Phone-Appears-Offline)

---

## A device has the wrong name or type

**Symptom.** A device shows a cryptic or outdated name, or the wrong type icon.

**Likely explanation.** Names come from the device and your DNS, and the first meaningful one wins. Values from earlier scans stay when a device stops announcing them. Types are heuristics.

**Resolution.** Set a custom name and type, or delete the device to have it detected afresh.

**Full entry:** [A device has the wrong name or type](Wrong-Name-or-Type)

---

## A device has no MAC address or vendor

**Symptom.** *–* in the MAC column, or *Private address* / no vendor.

**Likely explanation.** Routed networks and proxy ARP give no MAC address. Private MAC addresses have no registered vendor.

**Full entry:** [A device has no MAC address or vendor](No-MAC-or-Vendor)

---

## A deleted device reappears

**Symptom.** You deleted a device, and after the next scan it's back, with a **New** badge and a *New device* event.

**Likely explanation.** This is by design. Deleting removes the record, not the device. If the device is still on the network, the next scan finds it, and because SynetScan no longer has a record for it, it is a new device again. The confirmation dialog says so: *They will reappear as new devices when found again.* SynetScan has no "ignore" list.

Two special cases make it look like a deleted device came back although it is a different record:

- A phone with a **rotating private MAC address** appears under a new MAC address. See [Phone-Appears-Offline](Phone-Appears-Offline).
- A device **without a MAC address** (routed networks, proxy ARP) is recorded by IP address. Another device that later gets the same address takes over that record's place.

**Checks.**

1. Is the device still switched on and connected? Check its MAC address in the Details tab against the deleted one, if you noted it.
2. Is **Remove offline devices after** (Settings → Advanced) set? It only removes *offline* devices.

**Resolution.**

- To keep the device but stop being reminded of it: don't delete it, **mark it as known**. Give it a name, and a note such as "guest phone, OK".
- To get it out of the list for good: remove it from the network, or exclude its address from the scan. There is no exclusion list, but you can untick the automatic interface scan and enter ranges that skip the address (for example `192.168.1.1-99` and `192.168.1.101-254`). See [Scan Targets](Scan-Targets#other-uses-of-additional-ranges).
- To clear out devices that are really gone: **Settings → Advanced → Remove Offline Devices**, or set **Remove offline devices after**.

**For a bug report.** Only if a device you deleted reappears although it is verifiably off the network: the device's Details (MAC address, Detected via, Interface) and the scan history rows around the time it reappeared.

---

## "Open web interface" is disabled

**Symptom.** **Open Web Interface** is greyed out, or the **Open** links on the Services tab are grey.

**Likely explanation.** You aren't in the NAS's local network (QuickConnect, VPN into another subnet, internet), the device has no known web port, or it has only a link-local IPv6 address.

**Full entry:** ["Open web interface" is disabled](Open-Web-Interface-Disabled)

---

## SynetScan does not open correctly after an update

**Symptom.** After an update, the window is blank or half-drawn, shows the old version, or reports that a function isn't supported.

**Likely explanation.** The DSM desktop or the browser still uses the old files, or the service wasn't restarted.

**Resolution.** Reload DSM (F5), clear the cache, restart the package.

**Full entry:** [SynetScan does not open correctly after an update](Problems-After-Update)

---

## Older activity entries are missing

**Symptom.** Events you remember are no longer in **Activity → Events**, or the Overview shows only a few.

**Likely explanation.**

- **The Overview shows only the newest seven events.** Click **View all** for the full log.
- **SynetScan keeps the newest 1,000 events.** Older ones are dropped, regardless of age. A network with many sleeping devices (frequent *Went offline / Back online*) or short scan intervals reaches that limit faster.
- **A filter or search is active** on the Events tab.
- **The log was cleared** with **Clear**, or everything was reset with **Delete All Data** (Settings → Advanced).
- **The first scan creates no "New device" events**, only one *First scan* entry. After **Delete All Data**, the next scan is a first scan again.
- The **scan history** keeps the newest 100 scans.

Deleting a device doesn't delete its events, and neither does **Remove offline devices after**.

**Checks.**

1. Set the event filter to *All events* and empty the search box.
2. Count: if the Events tab shows *1000 item(s)*, the limit has been reached.
3. Look for a *First scan* entry that is newer than expected: then the data was reset.

**Resolution.**

- Reduce the noise that fills the log: raise **Settings → Schedule → Mark offline after** to 2, 3 or 5, or lengthen the interval. See [Phone-Appears-Offline](Phone-Appears-Offline).
- To keep a long-term record, [back up](Data-Storage-and-Backup#backup) `events.json` regularly.

**For a bug report.** If events are missing although the count is well below 1,000 and nobody cleared the log: the Events count, the newest and oldest event times, and whether the package was updated or reinstalled in between.

## Still stuck?

- [Logs and Diagnostics](Logs-and-Diagnostics): error messages, the log file and what to collect
- [FAQ and Known Limitations](FAQ)
- [Report a bug](Reporting-Bugs)
