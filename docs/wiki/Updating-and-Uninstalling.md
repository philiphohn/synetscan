# Updating and Uninstalling

## Updating SynetScan

### 1. What you will achieve

SynetScan runs the new version, with all devices, names, notes, history and settings kept.

### 2. Prerequisites

- SynetScan is installed.
- The new `SynetScan-<version>-noarch.spk` from the [Releases page](https://github.com/philiphohn/synetscan/releases). The release notes there describe what has changed.
- Optional: a [backup of the data](Data-Storage-and-Backup#backup).

SynetScan doesn't check for updates by itself and doesn't contact the internet. To hear about new versions, *watch* the repository on GitHub (**Watch → Custom → Releases**).

### 3. Steps

1. Check the installed version: in **Package Center → Installed**, select SynetScan. The version is shown on its page.
2. Download the new `.spk` from the [Releases page](https://github.com/philiphohn/synetscan/releases).
3. In **Package Center**, click **Manual Install**, choose the new `.spk`, and click **Next**.
4. DSM recognises that SynetScan is already installed and offers to update it. Confirm the publisher warning and the summary.
5. When Package Center reports SynetScan as **Running**, **reload the DSM page in your browser (F5)**. The DSM desktop keeps the old app entry and scripts in memory until it is reloaded.
6. Open SynetScan from the main menu.

<!-- SCREENSHOT TODO: Package Center → Manual Install recognising an update of SynetScan (old version → new version) -->

What happens during the update:

- The package service stops, the files are replaced, and the service starts again.
- Your data in the package's data folder (devices, events, scan history, settings, log) is kept. The new version migrates it if needed, for example by cleaning stored text from older versions.
- If **Scan when the service starts** is on (the default), a scan runs right after the update. The scan history lists it as **Service start**.

### 4. Expected result

- Package Center shows the new version.
- SynetScan opens normally, and your devices, names and history are all there.

> Verified: updates from 1.0.1 to 1.0.2, from 1.0.2 to 1.0.3, and from 1.1.1 and 1.1.2 through the 1.1.5 test builds to 1.1.5 kept all data on DSM 7.4.1 and 7.1.1.

### 5. Common problems

| Problem | What to do |
| --- | --- |
| **The window is blank, half-drawn, or shows the old version.** | Reload DSM (F5). If that doesn't help, clear the browser cache for the DSM address, or try a private window. See [SynetScan does not open correctly after an update](Problems-After-Update). |
| **"This function is not supported by the installed SynetScan service."** | The page is newer than the running service. Restart the package (Package Center → **Stop**, then **Run**), then reload DSM. |
| **"The SynetScan service is not running."** | Start the package in Package Center. If it doesn't start, see [Logs and Diagnostics](Logs-and-Diagnostics). |
| **Manual Install does nothing.** | Try again; over QuickConnect, a first attempt sometimes didn't react in testing. |

### Going back to an older version

Downgrades haven't been tested. Package Center may refuse to install an older version over a newer one **(to verify)**. Data written by a newer version may not be fully understood by an older one. If you need to go back, keep a backup of the data from before the update, uninstall, install the older version, and restore the backup.

## Uninstalling SynetScan

1. Open **Package Center → Installed → SynetScan**.
2. Open the menu next to **Open** (or the action menu, depending on the DSM version) and choose **Uninstall**. Confirm.

<!-- SCREENSHOT TODO: Package Center → SynetScan → Uninstall -->

The service stops and the package is removed. SynetScan's own uninstall scripts don't delete or keep anything themselves.

**Your data:** on DSM 7, the package's data folder (`/var/packages/SynetScan/var`) is normally removed together with the package **(to verify on your DSM version)**. If you might want your device list again, export it as CSV or [back up the data folder](Data-Storage-and-Backup#backup) before uninstalling.

Nothing else is left behind: SynetScan creates no shared folders, scheduled tasks, firewall rules or user accounts of its own, apart from the package user DSM manages. If you created a boot-up task for [ICMP ping](Enabling-ICMP-Ping), delete it in **Control Panel → Task Scheduler**.

## Stopping and starting

**Package Center → SynetScan → Stop** stops the service. No scans run, and the app shows *The SynetScan service is not running.* **Run** starts it again, and with **Scan when the service starts** on, a scan runs right away. Stopping waits up to 15 seconds for a running scan to end.

## Related articles

- [Installing SynetScan](Installation)
- [Data Storage, Retention, Backup, and Reset](Data-Storage-and-Backup)
- [SynetScan does not open correctly after an update](Problems-After-Update)
- [Release notes on GitHub](https://github.com/philiphohn/synetscan/releases)
