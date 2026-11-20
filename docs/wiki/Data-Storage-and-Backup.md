# Data Storage, Retention, Backup, and Reset

## Where the data is

Everything SynetScan stores is in the package's data folder on the NAS:

```
/var/packages/SynetScan/var/
  devices.json      the device list: detected details, your names, types, notes, known flags
  events.json       the activity log
  scans.json        the scan history
  config.json       the settings
  synetscan.log     the service log (plus synetscan.log.1 and .2, rotated)
  daemon.out        output of the service process (start errors)
  synetscand.pid    process ID of the running service
  synetscan.sock    control socket of the running service
```

On DSM 7, `/var/packages/SynetScan/var` usually points to a folder on your first volume, such as `/volume1/@appdata/SynetScan` **(to verify)**. All files belong to the package user and can only be read by that user (mode `0600`, *since 1.1.3*). Administrators need `sudo` to read them over SSH.

The files are plain JSON, written atomically: a new version is written next to the old one and then swapped in, so a power cut never leaves a half-written file. There is no database. The formats are described in [Internal API and Data Formats](Internal-API#data-files).

## How much is kept

| Data | Kept | What happens beyond the limit |
| --- | --- | --- |
| Devices | up to 8,192 (*since 1.1.3*) | The least valuable records are removed: devices you never named, typed, noted or marked as known go first, offline before online, longest unseen first. The NAS itself is never removed. |
| Activity events | the newest 1,000 | The oldest events are dropped. |
| Scan history | the newest 100 scans | The oldest scans are dropped. |
| Previous IPs per device | 5 | The oldest is dropped. |
| Log | about 1.5 MB (3 files of 512 KB) | The oldest file is deleted. |

**Offline devices** stay forever by default. To remove them automatically, set **Settings → Advanced → Data → Remove offline devices after** to 7, 30, 90 or 365 days. It is applied after every scan, and deletes devices that are offline and were last seen longer ago than that, together with your names and notes for them. Their events stay in the log until the 1,000-event limit pushes them out.

How the events of a device are kept: each event stores the device's name, address and MAC address as they were. Deleting a device doesn't delete its events, and renaming it doesn't change old events.

## Clean-up and reset

| Action | Where | Deletes | Keeps |
| --- | --- | --- | --- |
| **Delete** (devices) | Devices → select → **Delete** | The selected devices with their names, notes and types | Events, history, settings |
| **Remove Offline Devices** | Settings → Advanced → Data | All devices that are offline now | Online devices, events, history, settings |
| **Clear** (activity log) | Activity → Events → **Clear** | All events | Devices, history, settings |
| **Delete All Data** | Settings → Advanced → Data | All devices, all events, the whole scan history | Settings |

Every action asks for confirmation first. **Delete All Data** isn't possible while a scan runs (*Not possible while a scan is running.*). After it, the next scan is a **first scan** again: it records a new baseline, and all devices it finds count as known.

To also reset the **settings**, open each Settings tab and restore the defaults (**Restore defaults** for the ports), or stop the package, delete `config.json` and start the package again **(SSH, root)**.

## Backup

SynetScan has no backup function of its own. Whether **Hyper Backup** includes the data of third-party packages depends on DSM and the package **(to verify for SynetScan)**. These two ways work in any case:

### Option A: CSV export (devices only)

**Devices → Action → Export** downloads all devices with names, types, notes and addresses. Good as a readable inventory. It can't be imported back.

### Option B: copy the data folder (everything)

Over SSH as an administrator. Instead of the `synopkg` lines, you can also stop and start the package in Package Center **(to verify: `synopkg` is at `/usr/syno/bin/synopkg` on your DSM version)**:

```sh
sudo -i
/usr/syno/bin/synopkg stop SynetScan
mkdir -p /volume1/backup/synetscan
cp -a /var/packages/SynetScan/var/*.json /volume1/backup/synetscan/
/usr/syno/bin/synopkg start SynetScan
```

Replace `/volume1/backup` with a shared folder of yours. Stop the package first so the files don't change while you copy them. The backup contains your whole network inventory, so protect the folder accordingly.

To automate this, put the same commands into a scheduled task in **Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**, with user `root` **(to verify)**.

### Restoring

```sh
sudo -i
/usr/syno/bin/synopkg stop SynetScan
OWNER=$(stat -c '%U:%G' /var/packages/SynetScan/var/synetscan.log)   # the package user and group
cp /volume1/backup/synetscan/*.json /var/packages/SynetScan/var/
chown "$OWNER" /var/packages/SynetScan/var/*.json
chmod 600 /var/packages/SynetScan/var/*.json
/usr/syno/bin/synopkg start SynetScan
```

Restore into the same or a newer SynetScan version. Unknown or damaged files are ignored when the service starts, and SynetScan then starts with an empty list or default settings instead of failing.

## Moving to another NAS

Install SynetScan on the new NAS, then restore the backup as above. Devices are recognised by MAC address, so names and notes carry over. The new NAS itself has a different MAC address: it appears as a new device, and the old NAS's entry goes offline. Delete the old entry.

## Related articles

- [Updating and Uninstalling](Updating-and-Uninstalling)
- [Logs and Diagnostics](Logs-and-Diagnostics)
- [Complete Settings Reference](Settings-Reference#data)
- [Internal API and Data Formats](Internal-API)
