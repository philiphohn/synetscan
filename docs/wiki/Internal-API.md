# Internal API and Data Formats

> **This is an internal API.** It exists for SynetScan's own web interface. It isn't a supported integration interface: actions, parameters and fields can change in any release without notice. It is documented here for contributors and for diagnosis. If you build something on it, expect to adapt it after updates, and consider [requesting](Reporting-Bugs) a supported interface instead.

## Endpoint and authentication

```
/webman/3rdparty/SynetScan/api.cgi?action=<action>
```

Every request needs:

- the **DSM session cookie** of a signed-in user in the **administrators** group;
- DSM's session token in the **`X-SYNO-TOKEN`** header. The token is accepted only from the header, never from the URL (*since 1.1.5*);
- for changing actions: **POST** with **`Content-Type: application/json`** and a JSON object as body (*JSON requirement since 1.1.5*);
- no `Sec-Fetch-Site` header other than `same-origin` or `none`. Requests started by another website are refused (*since 1.1.5*).

The checks run in that order: cross-site, session, administrator, known action, method, content type. See [Architecture](Architecture#the-request-path-in-apicgi).

## Responses

Every answer is JSON, with HTTP status **200** even for errors. DSM's web server would otherwise replace error answers with its own HTML pages.

```json
{"success": true, "data": { … }}
{"success": false, "error": {"code": "invalid_config", "message": "custom_targets: invalid target: 10.0.0.0/33",
                             "field": "custom_targets", "value": "10.0.0.0/33"}}
```

Response headers include `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (the last two *since 1.1.5*).

### Error codes

| Code | Meaning |
| --- | --- |
| `cross_site` | Request started by another website |
| `auth` | No valid DSM session |
| `permission` | Not an administrator |
| `unknown_action` | No such action (*since 1.1.5 also for unknown GET actions*) |
| `method` | Changing action without POST, or a method other than GET/POST |
| `bad_request` | POST without JSON content type, invalid JSON, or not a JSON object |
| `too_large` | Body larger than 1 MB |
| `daemon` | The service isn't running |
| `daemon_perm` | The CGI may not connect to the service's socket (runs as another user) |
| `python` | No Python 3 found (sent by the `api.cgi` shell wrapper) |
| `busy` | Not possible while a scan runs (`reset`) |
| `not_found` | No device with this ID |
| `no_mac` | Wake-on-LAN for a device without a MAC address |
| `invalid_config` | A setting was rejected. `field` and `value` say which. |
| `internal` | Unexpected error in the service. See the log. |

## Read actions (GET or POST)

| Action | Returns |
| --- | --- |
| `status` | `status` (`idle`/`scanning`), `phase` (`prepare`, `discover`, `identify`, `verify`), `done`, `total`, `found`, `started`, `trigger`, `version`, `last_scan` (summary or null), `next_scan` (Unix time or null), `last_error`, `now`, `ping` (ping available), `tz_offset` (seconds), `tz_name`, `awaiting_open` (true while a fresh installation waits for the app to be opened before its first scan, *since 1.1.8*) |
| `overview` | `status` (as above), `hostname`, `interfaces` (`name`, `ip`, `prefix`, `network`, `mac`, `up`, `speed`, `virtual`, `gateway`, `ipv6`, `ipv6_deprecated`), `dns`, `counts` (`total`, `online`, `offline`, `new24h`, `unknown`), `types` (online devices per type), `events` (newest 12), `scans` (newest 20) |
| `devices` | `devices` (list of device records, see below), `port_names` (port → name), `types` (list of type keys) |
| `events` | `events`: all events, newest first |
| `scans` | `scans`: all scan summaries, newest first |
| `config_get` | `config` (current settings), `defaults`, `interfaces` (`name`, `ip`, `prefix`, `network`, `virtual`, `up`), `intervals`, `port_names` |
| `export` | `csv`: the CSV text. With `&format=csv`, the answer is a file download `synetscan-devices.csv` (UTF-8 with BOM) instead. |
| `client` | `ip` (browser address as seen by the NAS), `local` (`true`/`false`/`null`), `via` (interface name, `relay`, `link-local`, `remote` or `unknown`). Answered by the CGI itself. |

## Changing actions (POST, JSON body)

| Action | Body | Returns |
| --- | --- | --- |
| `scan` | `{}` | `started`: false if a scan is already running |
| `cancel` | `{}` | `{}`. Stops a running scan. |
| `opened` | `{}` | The same as `status`. Sent by the UI when it opens and `awaiting_open` is true: starts the first scan (trigger `open`) if **Scan when the service starts** is on, and ends the waiting. Changes nothing later (*since 1.1.8*). |
| `device_update` | `id`, and any of `name`, `notes`, `type_user` (a type key or empty for automatic), `known` | `id` |
| `device_known` | `ids` (list), `known` (default true) | `{}` |
| `device_delete` | `ids` (list) | `deleted` (count) |
| `wake` | `id` | `sent` (number of packets sent) |
| `config_set` | `config`: an object with the settings to change (partial is fine) | `config`: the complete new settings |
| `clear_events` | `{}` | `{}` |
| `clear_offline` | `{}` | `deleted` |
| `reset` | `{}` | `{}`. Deletes devices, events and history. `busy` during a scan. |

Example, run in the browser's developer console with the SynetScan frame selected as context (the DSM session object belongs to the parent window):

```js
fetch("api.cgi?action=device_update", {
  method: "POST", credentials: "same-origin",
  headers: {"Content-Type": "application/json", "X-SYNO-TOKEN": parent.SYNO.SDS.Session.SynoToken},
  body: JSON.stringify({id: "24:0a:c4:10:21:00", name: "Garden sensor", type_user: "iot", known: true})
}).then(r => r.json()).then(console.log);
```

## Service socket

`api.cgi` forwards each request to the service over the Unix socket `/var/packages/SynetScan/var/synetscan.sock` (mode 0600, package user only). The protocol is one line of JSON per connection in each direction:

```
→ {"action": "devices", "params": {}, "user": "alice"}
← {"success": true, "data": {…}}
```

Action names must match `^[a-z_]{1,32}$` and an `api_<action>` method of the service. Requests are limited to 1 MB, and an idle connection is closed after 30 seconds.

## Data files

All in `/var/packages/SynetScan/var/`, JSON in UTF-8, written atomically, mode 0600.

### devices.json

An object keyed by device ID: the MAC address (`aa:bb:cc:dd:ee:ff`), or `ip:<address>` for devices without a MAC address.

| Field | Source | Meaning |
| --- | --- | --- |
| `id` | store | Device ID (same as the key) |
| `ip`, `mac`, `vendor` | scan | IPv4 address (empty for IPv6-only devices), MAC address, MAC vendor |
| `hostname`, `mdns_name`, `netbios`, `workgroup` | scan | Reverse DNS, mDNS, NetBIOS names |
| `friendly`, `model` | scan | Friendly name (UPnP/mDNS), model |
| `upnp` | scan | `friendlyName`, `manufacturer`, `modelName`, `modelNumber`, `deviceType`, `modelDescription` |
| `http` | scan | `port`, `server`, `title` |
| `services`, `instances` | scan | mDNS service types and instance names |
| `ssdp_server` | scan | `Server` header of the SSDP answer |
| `ports` | scan | Open TCP ports (replaced on every scan) |
| `rtt` | scan | Ping round-trip time in ms, or null (replaced on every scan) |
| `via` | scan | Detection methods: `arp`, `tcp`, `icmp`, `mdns`, `ssdp`, `ndp`, `wsd`, `self` (replaced on every scan) |
| `iface` | scan | NAS interface, or `custom` |
| `random_mac` | scan | Locally administered (private) MAC address |
| `ipv6`, `ipv6_deprecated` | scan | IPv6 addresses, sorted; outdated ones of the NAS |
| `ipv6_router` | scan | The device sent IPv6 router advertisements |
| `self`, `gateway` | scan | The NAS itself; the default gateway |
| `other_ips` | scan | Further addresses of the NAS: `"10.10.0.5 (eth1)"` |
| `proxy_arp` | scan | MAC address of the device answering ARP for this address |
| `proxy_arp_for` | scan | Addresses this MAC address answers for |
| `type_auto` | scan | Automatic type |
| `name`, `notes`, `type_user`, `known` | user | Custom name, notes, custom type (empty = automatic), confirmed |
| `first_seen`, `last_seen` | store | Unix times |
| `online`, `missed` | store | Status, and missed scans in a row |
| `baseline` | store | Part of the first scan |
| `ip_history` | store | Up to 5 previous IPv4 addresses, newest first |

Scan fields are only overwritten when a scan finds a non-empty value, except `ports`, `rtt` and `via`. The `devices` action adds `type` (effective type), `display_name`, `address` (IPv4 or first IPv6) and `detected_name` to each record.

### events.json

A list, oldest first, at most 1,000 entries:

```json
{"ts": 1795116567, "kind": "ip_changed", "id": "9e:10:20:00:00:52", "name": "iPad",
 "ip": "192.168.1.52", "mac": "9e:10:20:00:00:52", "detail": "192.168.1.47 → 192.168.1.52"}
```

`kind`: `baseline` (detail: number of devices), `new` (detail: vendor), `online`, `offline`, `ip_changed`.

### scans.json

A list, oldest first, at most 100 entries:

```json
{"started": 1795116556, "finished": 1795116567, "duration": 11.0,
 "targets": ["192.168.1.0/24 (eth0)"], "target_count": 254, "found": 23, "new": 0,
 "offline": 0, "online_again": 0, "ip_changed": 0, "trigger": "schedule",
 "ipv6": {"enabled": true, "ifaces": ["eth0"], "routable": true, "with_ipv6": 4, "only": 1}}
```

`trigger`: `manual`, `schedule`, `startup` or `open` (the first scan of a fresh installation, started by opening the app, *since 1.1.8*); missing in scans recorded by 1.1.1 and older. `ipv6.error` is present when IPv6 discovery failed.

### config.json

The settings. See the [Settings Reference](Settings-Reference#settings-file).

## Related articles

- [Architecture and DSM Integration](Architecture)
- [DSM Permissions, Security, and Privacy](Security-and-Privacy)
- [Complete Settings Reference](Settings-Reference)
