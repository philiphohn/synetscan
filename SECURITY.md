# Security policy

SynetScan runs on your Synology NAS, talks to every device on your network and is used through a DSM administrator session. Reports about security problems are very welcome.

## Supported versions

Security fixes go into the latest release only. Please check that the problem still exists in the newest version from the [Releases page](https://github.com/philiphohn/synetscan/releases).

## Reporting a vulnerability

Please **don't open a public issue** for a security problem. Report it privately on GitHub instead:

**[Report a vulnerability](https://github.com/philiphohn/synetscan/security/advisories/new)** (Security tab → Report a vulnerability)

Only the maintainer can see the report. Please include:

- the SynetScan and DSM versions
- what an attacker can do, and what they need for it (a device in the LAN, a web page the admin visits, a DSM account without admin rights, …)
- steps or a proof of concept to reproduce it

## What happens next

You'll get a confirmation that the report arrived. The fix is prepared in a private security advisory, and you're credited in it when the fixed version is released, unless you'd rather stay anonymous. Please keep the details private until then.

## Scope

In scope is anything that lets someone do more than the Security section of the [README](README.md) allows, for example:

- getting script to run in the SynetScan page through a device name, service announcement or web page title
- making the NAS fetch pages from, or connect to, a machine it didn't ask
- using the API without an administrator's DSM session, or from another website
- reading or changing SynetScan's data without being a DSM administrator
- stalling or crashing scans from a single device

Not in scope:

- A device lying about its own name, model or type. Discovery protocols have no authentication, so SynetScan treats these as claims (see the README).
- Problems in DSM itself. Please report those to Synology.
