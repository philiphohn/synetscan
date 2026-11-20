# Local Development and Testing

SynetScan needs no build step. Clone the repository, and you can run the tests and a local preview with a mock DSM desktop on any Linux or macOS machine with Python 3 (3.8 or newer recommended).

```sh
git clone https://github.com/philiphohn/synetscan.git
cd synetscan
```

## Unit tests

```sh
python3 -m unittest discover -s tests
```

- `tests/test_core.py`: target parsing, configuration, MAC and vendor lookup, DNS and NetBIOS parsing, classification and display names, the store's device lifecycle, the local/remote check, IPv6 parsing and merging, proxy ARP, mDNS direct queries, multiple UPnP stacks.
- `tests/test_security.py`: what a hostile device, web page or request may try: invisible characters, oversized answers, slow ("dripping") devices, redirects to other machines, XML entity expansion, CSV formulas, API gate checks, private file modes.

The tests use local sockets and fake devices only. They don't scan any network.

## The local preview

```sh
python3 tools/devserver.py [--port 8640] [--var DIR] [--no-daemon]
```

Open `http://localhost:8640/`. Add `?lang=de` for German and `?page=devices` (or `activity`, `settings`) to start on another page.

The dev server:

- serves `tools/mock_dsm.html`, a simple stand-in for the DSM desktop with one window that holds the real `index.html` in an iframe;
- serves `src/ui/` under `/webman/3rdparty/SynetScan/`, as DSM does;
- runs the real API code through `tools/dev_cgi.py`. There is no DSM on a development machine, so `dev_cgi.py` replaces only the DSM login and administrator checks. The package itself has no switch to skip them;
- starts the **real daemon** (`src/bin/synetscand`) with its data in `--var` (default `.devvar/`). `--no-daemon` doesn't start it.

`SYNETSCAN_DEV_CLIENT=203.0.113.5 python3 tools/devserver.py` previews a remote session (QuickConnect or internet), with web links greyed out. Use `localhost` rather than `127.0.0.1` in the browser: the UI's host-name check treats a numeric address outside the private ranges as remote.

### ⚠️ The preview's daemon really scans

The daemon in the preview is the real one. With the default settings, **it scans as soon as it starts, and every hour**, in every network your machine is connected to. On a laptop in your own home network, that's what you want. On a **cloud server, a shared office network or any network that isn't yours**, it would probe other people's machines. Don't let that happen:

1. Create a data folder and fill it with made-up devices:

   ```sh
   VAR=$(mktemp -d)
   python3 tools/demo/seed.py "$VAR"
   ```

2. **Before starting the server**, switch every scan off in `$VAR/config.json`:

   ```sh
   python3 - "$VAR" <<'PY'
   import json, os, sys
   p = os.path.join(sys.argv[1], "config.json")
   c = json.load(open(p))
   c.update(scan_on_start=False, schedule_enabled=False, auto_subnets=False, custom_targets=[],
            use_mdns=False, use_ssdp=False, use_ipv6=False, use_ping=False)
   json.dump(c, open(p, "w"))
   PY
   ```

3. Start the server in the background, note its process ID, and stop it by that ID:

   ```sh
   python3 tools/devserver.py --var "$VAR" --port 8641 & echo $! > "$VAR/devserver.pid"
   # … work …
   kill "$(cat "$VAR/devserver.pid")"     # also stops the daemon it started
   ```

4. Don't click **Scan Now**, and don't change scan settings with **Apply**, in such a preview.

For real scan tests on a machine that isn't in a home network, use an isolated network: for example a Docker network created with `--internal`, with fake devices and the daemon running as containers inside it. Remove the network and the containers afterwards.

## Demo data

`tools/demo/seed.py <dir>` writes a made-up home network: 25 devices in `192.168.1.0/24` and `2001:db8:…` (the IPv6 documentation prefix), with invented MAC addresses and names, events and a scan history. Use only such fictional data in screenshots, tests and issues.

`tools/demo/shim.js` is injected into the app frame by the recording tools. It replaces the development machine's own network interfaces with those of the demo NAS (`eth0` 192.168.1.10), and plays a scan instead of running one.

## Screenshots and recordings

| Tool | Purpose |
| --- | --- |
| `node tools/shot.mjs <url> <out.png> [js] [width] [height]` | One screenshot with headless Chrome over the DevTools protocol, optionally running JavaScript inside the app frame first. No npm dependencies. **It doesn't inject the shim**, so the Overview shows the real interfaces of your machine. |
| `node tools/demo/record.mjs [url] [out.gif]` | Records the README demo (`docs/images/demo.gif`): drives the app, draws a pointer, assembles a GIF with ffmpeg. |
| `node tools/demo/wiki_shots.mjs [url] [outdir] [scenes]` | Produces the wiki's screenshots and GIFs (`docs/wiki/images/`). Besides `shim.js`, it injects a second shim that answers every action that would change data or send packets (scan, cancel, wake, settings, known/edit/delete, clear, reset) locally, and shows the default settings whatever the preview's `config.json` says. Pass a comma-separated list of scene names to redo only some. |

Requirements: Node.js 22 or newer (built-in `WebSocket`), `google-chrome` and, for GIFs, `ffmpeg`.

Wiki images are quantised to 256 colours afterwards to keep them small (for example with Pillow's `quantize(method=FASTOCTREE)`).

## Checking a change on a real NAS

The mock desktop can't reproduce everything: DSM's session check, the package user's permissions, nginx in front of the CGI, the real ExtJS window, QuickConnect. Before a release:

1. Build the package ([Building](Building-and-Releasing)) and install it on a test NAS with **Manual Install**, both fresh and as an update over the previous release.
2. Open it from the main menu, locally and over QuickConnect.
3. Run a scan, check devices, settings, CSV export, Wake-on-LAN.
4. Check `synetscan.log` for warnings.

## Related articles

- [Architecture and DSM Integration](Architecture)
- [Building Packages and Publishing Releases](Building-and-Releasing)
- [Contributing](Contributing)
