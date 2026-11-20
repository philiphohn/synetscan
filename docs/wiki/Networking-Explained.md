# Networking Explained

Background for anyone who wants to know how SynetScan finds and recognises devices, and why some devices look the way they do.

- **[Network Scanning Basics](Network-Scanning-Basics)**: what a network scan is, what ARP, ports, mDNS and UPnP are, and why a Synology NAS is a good place to run one.
- **[How Discovery and Identification Work](How-Discovery-Works)**: SynetScan's scan step by step, from the first connection attempt to the device type.
- **[IPv6 Discovery and Addresses](IPv6)**: how SynetScan finds IPv6 addresses and IPv6-only devices without root, and what the IPv6 hints mean.
- **[Multiple Interfaces, VLANs, and Routed Networks](Interfaces-VLANs-and-Routed-Networks)**: NAS with several ports, Open vSwitch, Docker, VLANs, proxy ARP and networks behind a router.
- **[Local Access, QuickConnect, VPN, and DDNS](Local-Access-QuickConnect-VPN-and-DDNS)**: how SynetScan decides whether you are in the local network, and why that matters for Open Web Interface.
