# SynetScan does not open correctly after an update

← [Troubleshooting](Troubleshooting)

## Symptom

After installing a new version:

- the SynetScan window is blank, half-drawn or keeps spinning, or
- it opens in a browser tab instead of a DSM window, or says it *has to be opened from the DSM main menu*, or
- it shows *This function is not supported by the installed SynetScan service.*, or
- it shows *The SynetScan service is not running.*, or
- actions fail with *The request was refused because it did not come from the SynetScan window* or *The request was rejected by the NAS.*

## Likely explanation

1. **The DSM desktop still has the old app in memory.** DSM loads the list of apps and their window scripts once, when you sign in. Until you reload the page, it opens the app the old way.
2. **The browser cached old files.** SynetScan adds its version to its file addresses to prevent this, but proxies or aggressive caches can still serve old files.
3. **The service didn't restart** or failed to start, so the page and the service are different versions, or there is no service at all.
4. **Something between the browser and DSM changes requests.** Since 1.1.5, SynetScan refuses changes without a JSON body, and requests a browser marks as started by another website. A reverse proxy or a browser extension that rewrites requests can trigger this.
5. **The page's security policy blocks something** (since 1.1.5). The page allows only its own scripts. If something injects scripts into DSM pages, such as some browser extensions, the window can stay blank, with messages in the browser console.

## Checks

1. Reload the DSM page with F5, then open SynetScan from the main menu again.
2. In **Package Center**, does SynetScan show the new version, and **Running**?
3. Try a private browser window, or another browser, without extensions.
4. Open the browser's developer tools (F12) → **Console**: are there errors mentioning *Content Security Policy* or failed requests to `api.cgi`?
5. Look at the end of the [log](Logs-and-Diagnostics) and at `daemon.out`: did the new version start (`synetscand 1.1.x listening on …`)?

## Resolution

| Cause | Fix |
| --- | --- |
| Old app in the DSM desktop | Reload DSM (F5). Sign out and in again if that doesn't help. |
| Cached files | Clear the browser cache for the DSM address, or use a private window. |
| Service not restarted | **Package Center → SynetScan → Stop**, then **Run**. Then reload DSM. |
| Service doesn't start | Read `synetscan.log` and `daemon.out` ([how](Logs-and-Diagnostics)). Check that Python 3 is still installed. Then [report it](Reporting-Bugs). |
| Opens in a tab / "has to be opened from the DSM main menu" | Open SynetScan from the DSM main menu, not from a bookmark of `index.html`. **Open in DSM** takes you there. |
| `cross_site` / "rejected by the NAS" errors | Open DSM directly, without a reverse proxy or extensions that rewrite requests. If that's not possible, report your setup. |
| Blank window with CSP messages | Disable extensions that inject scripts into pages, for the DSM address. Report which extension caused it. |

If nothing helps, uninstalling and reinstalling the package usually fixes broken installations. Back up the data first: see [Data Storage, Retention, Backup, and Reset](Data-Storage-and-Backup#backup).

## What to include in a bug report

- Old and new SynetScan version, DSM version, NAS model, browser and version
- How you open DSM (local, QuickConnect, VPN, reverse proxy)
- The exact message, and the browser console errors (F12 → Console)
- The last lines of `synetscan.log` and the content of `daemon.out`

## Related articles

- [Updating and Uninstalling](Updating-and-Uninstalling)
- [Logs and Diagnostics](Logs-and-Diagnostics)
- [Architecture and DSM Integration](Architecture)
