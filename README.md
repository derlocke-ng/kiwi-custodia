# kiwi-custodia

kiwi-custodia gives you a separate Linux environment for each client network
you work in. Each environment is a **box**: one Linux distribution of your
choice (Fedora, Ubuntu, Debian, Arch, openSUSE, Alpine and others) in a
rootless Podman container, which is a container that runs as your own user
without root rights. A box has a home folder of its own, you install software
in it with its package manager, and its desktop apps open on your desktop and
can go into your app grid.

A box has no network route of its own. All of its traffic goes through one
**exit**, a named connection that
[kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/) keeps, for
example a SOCKS5 proxy into a client's network or a VPN. That holds for every
program in the box: for `dnf`, for a game client, and for a program that
ignores proxy settings. If the exit stops, the box has no route at all. If you
know distrobox, this is the same idea, with the network kept in custody.

kiwi-custodia is part of the Kiwi desktop, next to kiwi-proxy and kiwi-fox.

- Latest release: **v0.6.1**, in the
  [Kiwi catalog](https://kiwi-network.eu/docs/desktop/catalogs/) (user scope,
  no root needed)
- Runs on: Linux with rootless Podman, Python 3.12 or newer and kiwi-proxy.
  CI runs the unit tests on Ubuntu 24.04 and builds the tunnel image with
  Podman.
- License: GPL-3.0-or-later

## Install

```bash
kiwi install kiwi-custodia
kiwi-custodia setup
```

`kiwi install` installs kiwi-proxy as well when it is missing, then puts
kiwi-custodia under `~/.local` with the `kiwi-custodia` command and the
**Kiwi Custodia** app. Nothing is installed as root. `kiwi-custodia setup`
builds the tunnel image and runs kiwi-proxy's own setup; run it once after the
install. From a checkout, `./install.sh install` does the same as
`kiwi install`. The [install page](docs/install.md) lists what kiwi-custodia
needs and every file it writes.

## Quick start

```bash
kiwi-proxy add client-a socks5://user:pass@proxy.example.net:1080
kiwi-custodia new work --exit client-a --distro fedora
kiwi-custodia run work -- sudo dnf install -y firefox
kiwi-custodia run work -- firefox
kiwi-custodia apps work
kiwi-custodia stop work
```

`kiwi-proxy add` saves the exit. `kiwi-custodia new` creates a Fedora box on
it and starts it; the first start installs a small baseline. `run` runs a
command in the box, here an install and then the browser, which opens on your
desktop and goes out through the exit. `apps` lists the box's desktop apps
with their ids, and `kiwi-custodia export work ID` puts one of them into your
app grid. `stop` stops the box and keeps what you installed in it. The app,
**Kiwi Custodia** in your app grid, does the same without a terminal.

## Documentation

| Page | What it covers |
|---|---|
| [Install](docs/install.md) | requirements, install, first setup, update, uninstall |
| [Using kiwi-custodia](docs/usage.md) | the app, its Preferences, every command |
| [Boxes](docs/boxes.md) | making a box, what is in it, keeping what you installed, colours |
| [Exits and the network](docs/exits.md) | how a box reaches the network, VPN and SOCKS5 exits, DNS |
| [Apps in the app grid](docs/apps.md) | a box's apps and its terminal as entries in your app grid |
| [Snapshots](docs/snapshots.md) | your boxes on your other devices, encrypted |
| [How it works](docs/architecture.md) | the containers, their mounts and labels, the decisions |
| [Development](docs/development.md) | running from a checkout, tests, CI, releases |

The same pages are on
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-custodia/).

## Status

A box limits the network. It is not a sandbox that protects your desktop from
the programs in it: like a distrobox container, a box gets your display and
your session bus. See
[What a box is not](docs/exits.md#what-a-box-is-not).

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). The tunnel image downloads
[tun2socks](https://github.com/xjasonlyu/tun2socks) (GPL-3.0) when it is
built, pinned by version and checksum.
