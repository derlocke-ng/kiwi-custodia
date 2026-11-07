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
kiwi-proxy add mullvad-se --module vpn --lease Sweden    # an exit, defined once, in kiwi-proxy
kiwi-custodia new work --exit mullvad-se --distro fedora  # a box on it; its first start installs the baseline
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

UDP has no way out of a gateway (no QUIC, no WebRTC media), and that holds in
a box: an app's UDP is dropped, and the sane ones fall back to TCP.

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
