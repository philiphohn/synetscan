# Logs and Diagnostics

When something doesn't work as expected, these are the places to look, from the app itself to the log file.

## In the app

| Where | What it tells you |
| --- | --- |
| **Status area** (bottom left) | Whether a scan is running, its phase, and when the last scan finished |
| **Overview → Network** | The NAS's interfaces with IP, IPv6, gateway, MAC address and link speed; host name; DNS servers; the ranges of the last scan (**Scanned ranges**) |
| **Activity → Scan History** | Each scan's trigger, duration, number of devices found, new and offline, and its ranges |
| **Settings → Advanced** | Whether ICMP ping is available (*Not available on this system…*), and what the last scan found over IPv6 |
| **Device → Details** | **Detected via** (ARP, TCP, ICMP, MDNS, SSDP, NDP, WSD, SELF), **Interface**, **Reached through** (proxy ARP), **First seen / Last seen** |
| **Error messages** | See the table below |

### Error messages

| Message | Code | Meaning |
| --- | --- | --- |
| *Your DSM session has expired. Please sign in to DSM again.* | `auth` | DSM didn't confirm your session. Sign in again. |
| *SynetScan has to be opened from the DSM main menu. In a browser tab of its own it cannot use your DSM sign-in.* | `auth` | The page was opened outside the DSM window. Click **Open in DSM**. |
| *SynetScan is only available to members of the administrators group.* | `permission` | Your account isn't an administrator. |
| *The SynetScan service is not running. Please start the package in Package Center.* | `daemon` | The background service isn't reachable. |
| *The SynetScan web interface may not connect to the SynetScan service.* (with a user ID) | `daemon_perm` | The API runs as a different user than the service. Please [report it](Reporting-Bugs) with your DSM version. |
| *The request was refused because it did not come from the SynetScan window. …* | `cross_site` | The browser marked the request as started by another website. *Since 1.1.5.* |
| *The request was rejected by the NAS.* | `method`, `bad_request` | A change was sent without POST or without a JSON body. |
| *This function is not supported by the installed SynetScan service.* | `unknown_action` | The page and the service are different versions. Restart the package and reload DSM. |
| *Not possible while a scan is running. …* | `busy` | Wait for the scan to finish. |
| *The device no longer exists. The list has been refreshed.* | `not_found` | Someone else deleted it, or a scan replaced its record. |
| *The device has no known MAC address, so a Wake-on-LAN packet cannot be sent.* | `no_mac` | – |
| *Invalid value for "…": …* and specific messages for ranges, ports, timeout, probes, interval | `invalid_config` | A setting was rejected. Nothing was saved. |
| *The NAS could not be reached. Check the connection and try again.* | `network` | The browser lost the connection to DSM. |
| *The NAS sent an unexpected answer. Please try again.* | `http` | The answer wasn't SynetScan's JSON. A proxy or an error page got in between. |
| *An internal error occurred in the SynetScan service. Details are in the package log.* | `internal` | See the log. |

## The log file

The service writes its log to:

```
/var/packages/SynetScan/var/synetscan.log
```

It is rotated at 512 KB, keeping `synetscan.log.1` and `synetscan.log.2`. Problems that happen before logging starts (for example *python3 not found*) end up in `daemon.out` in the same folder.

**DSM 7.4 Package Center has no Log tab for third-party packages**, so read the file over SSH or copy it with a scheduled task. The file can only be read by the package user (*since 1.1.5*), so you need root.

### Option A: SSH

```sh
ssh your-admin-user@192.168.1.10
sudo tail -n 100 /var/packages/SynetScan/var/synetscan.log
sudo grep -E "WARNING|ERROR" /var/packages/SynetScan/var/synetscan.log
sudo cat /var/packages/SynetScan/var/daemon.out
```

Enable SSH in **Control Panel → Terminal & SNMP** first, and switch it off again afterwards if you don't use it otherwise **(to verify for your DSM version)**.

### Option B: copy the log to a shared folder (no SSH)

1. **Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script** **(to verify)**.
2. **General**: Task `SynetScan log copy`, User `root`.
3. **Schedule**: run on a date, once (or daily).
4. **Task Settings → Run command**, replacing `/volume1/public` with a shared folder of yours:

   ```sh
   cp /var/packages/SynetScan/var/synetscan.log /volume1/public/synetscan.log
   chmod 644 /volume1/public/synetscan.log
   ```

5. Click **OK**, select the task and click **Run**. Open the file with File Station or from your computer.

<!-- SCREENSHOT TODO: Task Scheduler → Scheduled Task → User-defined script copying the SynetScan log -->

The log names the devices on your network. Delete the copy when you're done, and don't leave it in a folder others can read.

### Reading the log

Each line has a timestamp, a level (`INFO`, `WARNING`, `ERROR`) and a message, always on one line. Typical lines:

| Line | Meaning |
| --- | --- |
| `synetscand 1.1.x listening on …/synetscan.sock` | The service has started. |
| `scan started: 254 targets (192.168.1.0/24 (eth0)), ping=False` | A scan begins: number of addresses, ranges, whether ping is used |
| `proxy ARP: 00:1d:aa:… answers for 192.168.1.1, 192.168.1.200; kept on 192.168.1.1` | A router answers ARP for other addresses ([proxy ARP](Interfaces-VLANs-and-Routed-Networks#proxy-arp-and-vpn-clients)) |
| `second ARP round found 2 more host(s)` | Sleeping devices answered the second datagram. |
| `dropping stale ARP entry 192.168.1.47` | A device known only from the ARP cache has gone ([Verifying](How-Discovery-Works#4-verifying)). |
| `mDNS: 1 device(s) answered the browse without a host name; asked directly, 1 gave it and 1 their IPv6 addresses` | Devices were asked directly for their `.local` name and addresses (*since 1.1.5*). |
| `mDNS: 1 device(s) answered the browse without IPv6 addresses; 0 gave them when asked directly` | Devices that gave their name but no IPv6 addresses were asked for them. Devices without IPv6 are counted too, so a 0 here is normal (*since 1.1.5*). |
| `IPv6: 12 neighbour(s) on eth0 (echo: none)` | IPv6 discovery result. `echo:` shows how the all-nodes echo was sent: `socket`, `ping` or `none`. |
| `IPv6: no interface with IPv6 (link-local) address, skipped` | IPv6 is off on the NAS. |
| `IPv6: 2 device(s) without IPv4` | IPv6-only devices found |
| `scan finished: 24 hosts in 10.8s` | The scan ended normally. |
| `scan cancelled` | Someone clicked **Stop**, or the service stopped. |
| `scan failed` + traceback | An error. Please [report it](Reporting-Bugs) with these lines. |
| `manual scan requested by alice` / `configuration changed by alice` / `WOL sent to … by alice` | Actions by a DSM user |
| `mDNS browse failed: …`, `SSDP discovery failed: …`, `IPv6 discovery failed: …` | One method failed. The rest of the scan continues. |
| `device list is full: removed N records (limit 8192)` | The device limit was reached. |
| `synetscand stopped` | The service stopped normally. |

## Package and service state

- **Package Center** shows whether SynetScan is **Running** or **Stopped**, and its version.
- If the service fails to start, Package Center shows *SynetScan service failed to start, see /var/packages/SynetScan/var/synetscan.log*. The start script waits up to 10 seconds for the service's socket.
- Over SSH: `sudo ls -l /var/packages/SynetScan/var/` shows whether `synetscan.sock` and `synetscand.pid` exist (they do while the service runs).

## What to collect for a bug report

1. SynetScan version (Package Center), DSM version, NAS model
2. How you open DSM: local address, QuickConnect, VPN, DDNS
3. The error message, or a screenshot with private names blurred
4. The relevant log lines, with names and MAC addresses replaced
5. For scan problems: the **Scan History** row, and the **Detected via** and **Interface** of an affected device

See [Reporting Bugs and Requesting Features](Reporting-Bugs).

## Related articles

- [Troubleshooting](Troubleshooting)
- [Data Storage, Retention, Backup, and Reset](Data-Storage-and-Backup)
- [Reporting Bugs and Requesting Features](Reporting-Bugs)
