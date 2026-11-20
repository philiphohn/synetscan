# Reporting Bugs and Requesting Features

Bug reports and ideas go to the GitHub issue tracker: **[github.com/philiphohn/synetscan/issues](https://github.com/philiphohn/synetscan/issues)**. You need a free GitHub account.

## Before you report

1. Check [Troubleshooting](Troubleshooting) and the [FAQ](FAQ). Many questions are answered there.
2. Search the [existing issues](https://github.com/philiphohn/synetscan/issues?q=is%3Aissue), open and closed. If your problem is already there, add your details to that issue instead of opening a new one.
3. Make sure you run the [latest release](https://github.com/philiphohn/synetscan/releases/latest). The [release notes](https://github.com/philiphohn/synetscan/releases) may already mention a fix.

## Reporting a bug

Open a [new issue](https://github.com/philiphohn/synetscan/issues/new) with a short, specific title, such as *"Hue bridge shown without name since 1.1.5"* rather than *"doesn't work"*.

Include:

| What | Where to find it |
| --- | --- |
| **SynetScan version** | Package Center → Installed → SynetScan |
| **DSM version and NAS model** | Control Panel → Info Center |
| **How you open DSM** | Local address, QuickConnect, VPN, DDNS, reverse proxy |
| **Browser** | Name and version |
| **What you did, what you expected, what happened** | Step by step |
| **The exact message**, with its wording | The app. Screenshots help. |
| **Relevant log lines** | `/var/packages/SynetScan/var/synetscan.log`, see [Logs and Diagnostics](Logs-and-Diagnostics) |
| **For scan problems** | The Scan History row; the affected device's Details (Detected via, Interface, Vendor, open ports) |

Each [troubleshooting entry](Troubleshooting) ends with a list of what helps for that kind of problem.

### Protect your privacy

Logs, screenshots and device details describe your network. Before posting:

- Replace **personal names** in device names ("Anna's iPhone" → "Phone A").
- Replace or shorten **MAC addresses** (keep the first six hex digits if the vendor matters: `5c:62:8b:xx:xx:xx`).
- Shorten **public IP addresses** and your **QuickConnect ID** or DDNS name.
- Private addresses such as `192.168.1.57` are harmless, but you may anonymise them too (`192.168.x.57`).
- Never post your DSM password, session tokens (`SynoToken`, cookies) or exported CSV files.

## Reporting a security vulnerability

Please **don't** describe a vulnerability in a public issue. Open an issue that only says you have found a security problem and asks for a private contact, or use GitHub's **private vulnerability reporting** (Security tab → *Report a vulnerability*) if it is enabled for the repository.

## Requesting a feature

Open an issue that describes:

- **The problem you want solved**, not only the solution. For example: "I want to know within minutes when an unknown device joins", rather than "add Telegram".
- **How you would use it**, and in what kind of network (home, office, several VLANs…)
- If you like, how it might look in the app

Ideas that come up regularly, such as notifications or an ignore list, are good candidates, and a thumbs-up on an existing request counts too.

## Contributing yourself

Code, translations and documentation fixes are welcome as pull requests. See [Contributing, Translations, and Vendor Database](Contributing).

## Related articles

- [Logs and Diagnostics](Logs-and-Diagnostics)
- [Troubleshooting](Troubleshooting)
- [Contributing](Contributing)
