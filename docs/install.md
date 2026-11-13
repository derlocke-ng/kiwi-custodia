# Install

This page says what kiwi-custodia needs, how to install it, what the first
setup does, and how to update and remove it. kiwi-custodia is installed for
your own user only. It needs no root rights, because its containers run in
rootless Podman, which means Podman containers that run as your own user.

## What you need

| What | Why |
|---|---|
| Linux with rootless Podman | Every box, and the tunnel container next to it, runs in Podman as your user. |
| `catatonit`, Podman's `--init` helper | Every box starts with `--init`, so that processes its apps leave behind are cleaned up. Podman cannot start a box without it. |
| `/dev/net/tun`, usable by rootless containers | The tunnel container creates a TUN device, a virtual network interface, in the exit's gateway. Machines where kiwi-proxy's VPN module works have it. |
| [kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/) | It keeps the exits and runs their gateways. kiwi-custodia imports it and runs its setup. |
| Python 3.12 or newer, with pydantic 2.6 or newer | The command and the app are written in Python. |
| A Wayland session | A box's apps open their windows through your Wayland socket. Without one, a box runs, but its apps cannot open windows. |
| GTK 4, libadwaita and PyGObject | Only for the app, **Kiwi Custodia**. The command works without them. |
| A terminal emulator | Only for the terminal button in a box's row in the app, and for a box's own entry in the app grid. `kiwi-custodia doctor` says which one it found. |

Some features need a newer kiwi-proxy:

| Feature | Needs |
|---|---|
| [Snapshots](snapshots.md) | kiwi-proxy 0.8.1 or newer, and what kiwi-proxy's snapshots need |
| **Check and repair** on the Maintenance page | kiwi-proxy 0.8.2 or newer |
| **Repair on start** and `kiwi-custodia repair`; with an older kiwi-proxy they do nothing | kiwi-proxy 0.8.2 or newer |
| The (?) buttons in the app | kiwi-proxy 0.8.3 or newer |
| A box on a VPN exit without the tunnel container, with UDP | kiwi-proxy 0.11 and kiwi-plugin-vpn 0.3 or newer |
| "VPN not answering" in the list | kiwi-proxy 0.18 or newer |

[Exits and the network](exits.md) explains the last two.

## Supported systems

kiwi-custodia belongs to the Kiwi desktop, a Fedora Atomic workstation. The
tunnel image is based on Alpine 3.21 and is built for x86_64 and aarch64.
These are the tests that run automatically:

| What is tested | Where |
|---|---|
| Unit tests and the linter, against kiwi-proxy's `main` branch | GitHub Actions, Ubuntu 24.04 |
| The tunnel image: built without a cache, then `tun2socks --version` from inside | GitHub Actions, `ubuntu-latest` with Podman |

No test in CI starts a box. The unit tests check the `podman` commands
kiwi-custodia would run against a stand-in for Podman.

## Install with kiwi

```bash
kiwi install kiwi-custodia
kiwi-custodia setup
```

kiwi-custodia is in the [Kiwi catalog](https://kiwi-network.eu/docs/desktop/catalogs/)
with user scope. It depends on kiwi-proxy, so `kiwi install` installs
kiwi-proxy first when it is missing. `kiwi` checks for `podman` and `python3`
before it installs. `KIWI_GUI=0` installs without the app.

## Install from a checkout

```bash
git clone https://github.com/derlocke-ng/kiwi-custodia
cd kiwi-custodia
./install.sh install
kiwi-custodia setup
```

The commands that `install.sh` writes load kiwi-proxy from
`~/.local/lib/kiwi-proxy`, so install kiwi-proxy first. `install.sh` reads
these environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `KIWI_PREFIX` | `~/.local` | Where the program, the commands and the app entry go. |
| `KIWI_GUI` | `1` | `0` installs without the app, for a machine without a desktop. |
| `KIWI_SCOPE` | `user` | With any other scope, the installer does nothing: kiwi-custodia is a user app only. |

## What the installer writes

| Path | What it is |
|---|---|
| `~/.local/lib/kiwi-custodia/` | The Python package, and the container files of the tunnel image and of a box's first process. |
| `~/.local/bin/kiwi-custodia` | The command. |
| `~/.local/bin/kiwi-custodia-gui` | The app (not with `KIWI_GUI=0`). |
| `~/.local/share/applications/eu.kiwinetwork.KiwiCustodia.desktop` and its icon | The app's entry in your app grid. |

When `~/.local/share/kiwi-custodia/boxes` exists, the installer also rewrites
each box's own entry in the app grid, so that it points to the new install
(`kiwi-custodia desktop sync`). Entries of apps you exported are not
rewritten; if the install moved, export them again.

kiwi-custodia keeps its own data in these places:

| Path | What it holds |
|---|---|
| `~/.local/share/kiwi-custodia/boxes/` | One folder per box: its record (`box.json`), its home folder and, when it has one, its setup script. |
| `~/.local/share/kiwi-custodia/icons/` | Each box's icon in its colour. |
| `~/.config/kiwi-custodia/` | The app's preferences (`settings.json`) and window size (`window.json`). |
| Podman: `kiwi-custodia/tunnel:latest` | The tunnel image. |
| Podman: `localhost/kiwi-custodia/box-…` | One image per box, with what you installed in it. [Boxes](boxes.md#keep-what-you-installed) explains it. |

The entries a box puts into your app grid are listed on
[Apps in the app grid](apps.md#files).

## First setup

`kiwi-custodia setup` prepares everything a box needs before it can start. It
is not part of the install, because it builds an image and downloads data. It
is safe to run again at any time.

1. It runs kiwi-proxy's setup: the gateway image, the DNS data, the ad-block
   list and the images of the provider modules you installed.
2. It builds the tunnel image, `kiwi-custodia/tunnel:latest`, from
   `containers/tunnel/Containerfile`. The build downloads tun2socks v2.7.0 and
   checks it against a pinned checksum.

The distributions' images are not downloaded by `setup`. Podman pulls an image
when a box that uses it starts for the first time. In the app, the banner
"Setup incomplete" with its **Set up** button, or **Set up environment** on
the Maintenance page of Preferences, runs the same setup.

## Check the setup

```bash
kiwi-custodia doctor
```

`doctor` lists Podman and its version, the tunnel image and kiwi-proxy's
gateway image (each `current`, `stale` or `missing`), your display, the session
bus, the GPU, the terminal emulator it found, how many exits kiwi-proxy has,
and which tunnel containers are running. It ends with exit code 1 when Podman
or one of the two images is missing. In the app, **Check environment** on the
Maintenance page of Preferences says what is missing.

## Update

`kiwi update` updates kiwi-custodia like every other Kiwi app. After an
update, run `kiwi-custodia setup` again. It rebuilds the tunnel image only
when the new version changed the files the image is built from, and does
nothing otherwise. Until then, `kiwi-custodia doctor` reports the image as
`stale`.

## Uninstall

```bash
kiwi uninstall kiwi-custodia            # or: ./install.sh uninstall
kiwi uninstall kiwi-custodia --purge    # or: ./install.sh uninstall --purge
```

An uninstall first stops every box. Each box is kept in its own image as it
stops. The uninstall then removes the program, the commands, the app entry
and its icon, every entry that kiwi-custodia put into your app grid, and the
tunnel image. It keeps `~/.local/share/kiwi-custodia` and the boxes' images,
so a new install continues with your boxes, their homes and what you installed
in them.

`--purge` deletes `~/.local/share/kiwi-custodia` and `~/.config/kiwi-custodia`
as well, with every box's home, the boxes' images, and the icons of the apps
you exported. The distributions' base images stay in Podman; `podman rmi`
removes them. Your exits stay in kiwi-proxy, and kiwi-proxy stays installed;
remove it separately if you no longer need it.
