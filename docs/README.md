# kiwi-custodia documentation

kiwi-custodia gives you a separate Linux environment for each client network
you work in. A **box** is one such environment: a Linux distribution in a
rootless Podman container, with a home folder of its own, whose apps open on
your desktop. An **exit** is the connection a box goes out through, for
example a SOCKS5 proxy or a VPN; exits and their **gateways**, the containers
that hold an exit's network, belong to
[kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/). A box has no
network route other than its exit.

| Page | For | What it covers |
|---|---|---|
| [Install](install.md) | everyone | requirements, install, first setup, update, uninstall |
| [Using kiwi-custodia](usage.md) | everyone | the app, its Preferences, every command |
| [Boxes](boxes.md) | everyone | making a box, distributions, what is in a box, keeping what you installed, colours |
| [Exits and the network](exits.md) | everyone | how a box reaches the network, VPN and SOCKS5 exits, DNS, what a box is not |
| [Apps in the app grid](apps.md) | everyone | a box's apps and its terminal as entries in your app grid |
| [Snapshots](snapshots.md) | everyone with several devices | encrypted copies of your boxes for your other devices |
| [How it works](architecture.md) | the curious, contributors | the containers, their mounts and labels, the decisions |
| [Development](development.md) | contributors | running from a checkout, tests, CI, releases |

These pages are also on
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-custodia/), where
they are pulled from this folder at every release.
