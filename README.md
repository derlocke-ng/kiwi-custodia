# Kiwi Custodia

Distro containers whose every byte leaves through a
[kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy) exit.

A **box** is one Linux distribution — Fedora, Ubuntu, Debian, Arch, openSUSE or
Alpine — in a rootless Podman container with a home of its own, joined to the
sealed gateway of a kiwi-proxy exit. Install anything in it with its package
manager; run its desktop apps on your desktop; put them in the app grid. The
box has no route but the exit: not for `dnf`, not for a game client, not for a
static binary that never heard of `$ALL_PROXY`. If the exit goes, the box has
no route at all.

Think distrobox, with the network in custody.

```
gateway container   kiwi-proxy's, for the exit; owns the network namespace
                    nftables: default drop, one permitted destination
                    forwarder 127.0.0.1:1080: adds the exit's credentials
                    dnscrypt-proxy 127.0.0.2:53: ad-blocking, through the same exit
tunnel sidecar      kiwi-custodia's, one per exit, in the same namespace
                    TUN device kc0 = the default route; tun2socks feeds it into the forwarder
box container       the distro, joined to the same namespace — no routing table of its own
                    your user (keep-id), its own home, the display, sound and the session bus
```

The kill switch is the absence of a route, not software that has to notice.

## Install

```
kiwi install kiwi-custodia   # brings kiwi-proxy along; or: ./install.sh install
kiwi-custodia setup          # the tunnel image, and kiwi-proxy's gateway image and DNS data
```

Distro images are pulled when a box is first started, not at install time.

## Use

```
kiwi-proxy add home --module vpn --config ~/wg0.conf     # an exit, defined once, in kiwi-proxy
kiwi-custodia new work --exit home --distro fedora        # a box on it; its first start installs the baseline
kiwi-custodia enter work                                  # a shell in it: sudo dnf install steam
kiwi-custodia run work -- firefox                         # one command in it
kiwi-custodia check work                                  # what the world sees from inside — through the TUN
kiwi-custodia apps work                                   # the desktop apps it has
kiwi-custodia export work firefox                         # "Firefox (work)" in the app grid
kiwi-custodia stop work
kiwi-custodia-gui                                         # "Kiwi Custodia" in your app grid
```

`new` takes `--distro` (a preset: Fedora, Ubuntu, Debian, Arch, openSUSE, Rocky,
Alpine, Kali, the toolbx images of the first four — `kiwi-custodia distros` lists
them — or `custom` with `--image registry/name:tag` for any OCI image; the package
manager is detected on the first start), `--shell` for a login shell other than
bash, `--package NAME` for things the first start should install, `--no-gpu`,
`--desktop-entry` for a terminal entry in the app grid, `--no-start`, `--enter`.
`set` changes a box afterwards, `--exit OTHER` included: the box is stopped for
it and starts again on the new exit with everything that was installed in it —
a box is committed to a snapshot image when it stops, and the next start comes
from that. kiwi-proxy does the same before it removes a box with the exit (the
stop button in Kiwi Proxy, `kiwi-proxy down`), from 0.7.1 on. `reset` goes back
to the base image (the home stays); `rm` deletes the box and its home.

### The app

`kiwi-custodia-gui` does all of it: new box, start and stop, a terminal into
it, its applications with one button to put each in the app grid, the exit it
is on (and **Open Kiwi Proxy** for a new one), what the world sees through it,
logs, setup.

### The box

- Your user, same uid, passwordless `sudo`. The box's home is
  `~/.local/share/kiwi-custodia/boxes/<id>/home` on the host — one per box, not
  your real home: two boxes are two identities, and deleting a box deletes it.
- The first start installs a baseline: `sudo`, bash, a locale, Mesa for GPU
  rendering, a font, `xdg-utils`, `curl`. Whatever you add with the package
  manager stays: the container is committed to the box's snapshot image when the
  box stops, and recreated from that — after an exit change, a new base image,
  a reboot. `kiwi-custodia reset` is the way back to the plain base image.
- Wayland, X11 for Xwayland clients, PipeWire and its PulseAudio shim, the
  session bus and `/dev/dri` are passed in, so a GTK, Qt or Electron app opens
  on your desktop with your theme and talks to the portals.
- The hostname is the box's name, so prompts read `you@work`.
- No proxy setting is needed: the default route already is the exit. The
  gateway's SOCKS5 is in `$KIWI_CUSTODIA_SOCKS` for a tool you want to point at
  it by hand; on a remote-DNS exit (Tor) `ALL_PROXY` is set as well, since a
  `.onion` resolves only that way. Elsewhere it is left unset: Chromium and
  Electron apps read `all_proxy` and choke on it.

### What goes where

| Exit's DNS mode | A box resolves names at |
| --- | --- |
| resolver (default) | the gateway's dnscrypt-proxy, 127.0.0.2 — ad-blocking applies |
| remote (Tor) | the sidecar's stub, 127.0.0.3 — each query over TCP through the exit to a public resolver |

Two boxes on one exit share its gateway and its sidecar — one namespace, one
exit IP, one set of Tor circuits. Boxes that must not share an exit take
different exits. A kiwi-fox profile and a box on the same exit share it too.

On a SOCKS5 exit (Tor, a proxy, 9proxy) UDP has no way out of the gateway, and
that holds in a box: an app's UDP is dropped, and the sane ones fall back to TCP.
**On a VPN exit a box gets UDP too:** the exit's namespace is the VPN's own
(kiwi-proxy 0.11, kiwi-plugin-vpn), so the box needs no sidecar and sends TCP and
UDP straight through the tunnel — games, calls, DNS tools — and nothing leaves
when the tunnel is down.

## A box on your other devices

Boxes go into the same encrypted snapshot folder as Kiwi Proxy's exits and Kiwi
Fox's profiles; your sync client (Nextcloud) carries it to your other devices.
A snapshot does not hold the box's image (about 2 GB for a Fedora box with a
desktop app in it). It holds what you did to the box, recorded by itself every
time:

- **The packages you added**, from the package manager's own list of what was
  installed on purpose, minus what the base image and the baseline bring.
- **The system files you added or changed** outside the home: repository files
  and signing keys, edits under `/etc`, what you unpacked into `/opt` or
  `/usr/local`. A file that belongs to a package unchanged is left out, since
  the package brings it back. So is what is this machine's (users, hostname,
  resolver, certificates bundles).
- **A package installed from a downloaded file** travels as its files, with what
  it requires.
- **The home**, without `.cache`.

On the other device the box is rebuilt from its base image at its first start,
through its own exit: repositories and keys first, then the packages, then the
remaining files, then the setup script; the home is already there.

```bash
kiwi-proxy snapshot setup ~/Nextcloud/kiwi-snapshots   # once per device; the same in Preferences
kiwi-custodia snapshot list
kiwi-custodia snapshot show work                       # what its newest snapshot carries
kiwi-custodia snapshot restore work                    # its exit must be restored in Kiwi Proxy first
kiwi-custodia set work --setup-script setup.sh         # for anything a list cannot express
```

- **When:** after a box ran and stopped, after you change it, and whenever you
  ask (Snapshots… in its menu, or Preferences → Snapshots). A running box is
  committed to its image first, so the recording reads a consistent system.
- **The setup script** (the editor's "Extra setup script") runs once as root
  after the packages whenever the box is built: at its first start here, and on
  another device when it is rebuilt.
- **Starting an older copy asks first**, and a box open on another device says
  so, as in Kiwi Fox.
- **Its exit comes from Kiwi Proxy.** A box whose exit is not on this device
  says "restore it in Kiwi Proxy first"; Kiwi Custodia never makes or restores
  proxies.

Three limits, so they do not surprise you: packages are installed again from
their repositories, so the other device may get newer versions; a large program
unpacked by hand makes the snapshot as large as that program (the editor shows
the size); and only dnf, apt, pacman, zypper and apk boxes are recorded, other
images carry their home and declared packages only. The image a box is committed
to stays on its device and remains the fast path there.

## What it is not

A box is **network custody, not a sandbox from the desktop**. It gets your
session bus and your display, like distrobox: a program in the box can talk to
your desktop, show windows, read the clipboard, use the portals. What it cannot
do is reach the network other than through the exit. For an identity that
must not share hardware tells with your other identities, that is kiwi-fox's
job; this is for using software through a tunnel.

## Requirements

Rootless Podman with `catatonit` (the `--init` helper, shipped with podman on
Fedora, Debian, Ubuntu and Arch), [kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy),
a Wayland session, Python 3.12+ with pydantic, GTK 4 + libadwaita (PyGObject)
for the app. `/dev/net/tun` must be usable by rootless containers, which it is
wherever kiwi-proxy's VPN module works.

After updating, run `kiwi-custodia setup` again: it rebuilds the tunnel image
when what it is built from changed, and does nothing otherwise.

## Documentation

- [docs/architecture.md](docs/architecture.md) — the sidecar, the routes, the box, what is shared
- kiwi-proxy's [docs/consumers.md](https://github.com/derlocke-ng/kiwi-proxy/blob/main/docs/consumers.md) — the API this is built on

## License

GPL-3.0-or-later — see [LICENSE](LICENSE). The tunnel image fetches
[tun2socks](https://github.com/xjasonlyu/tun2socks) (GPL-3.0) at build time,
pinned by version and checksum.
