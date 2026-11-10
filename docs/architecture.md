# Architecture

## Three containers, one namespace

```
                   ┌──────────────────────── gateway netns (kiwi-proxy) ────────────────────────┐
                   │ nftables output: default drop                                              │
                   │   ct established · lo · <one permitted address>:<port> · oifname kc0 (ours) │
 box ──────────────┼─► default route: kc0 ──► tun2socks ──► forwarder 127.0.0.1:1080 ───────────┼──► upstream
 (keep-id, your    │                                          (adds the exit's credentials)     │    SOCKS5
  user, own home)  │ dnscrypt-proxy 127.0.0.2:53 (resolver mode) ─ DoH through the forwarder    │
                   │ kc-dnsstub 127.0.0.3:53 (remote mode) ─ DNS/TCP through the forwarder      │
                   └─────────────────────────────────────────────────────────────────────────────┘
```

- **gateway** (`kf-gw-<exit>`) — kiwi-proxy's. Brought up with `gateway.up(ex,
  labels={"app": "kiwi-custodia", …}, measure=False)` exactly as kiwi-fox does;
  reused if it already runs for the exit (another box, a kiwi-fox profile, a
  `kiwi-proxy up`).
- **tunnel** (`kc-tun-<exit>`) — ours, one per exit, `--network container:<gateway>`,
  `NET_ADMIN` + `/dev/net/tun`, no user namespace of its own (capabilities over a
  netns are judged in the user namespace that owns it; the gateway's is podman's
  rootless one). `containers/tunnel/entrypoint.sh`:
  1. reads the gateway's permitted destination (`KC_ENDPOINT_IP`, from the
     gateway's env; the ruleset otherwise) and pins a host route to it on the
     real interface, unless it is on-link (a provider on `kf-providers`);
  2. inserts one rule into the gateway's output chain: `oifname "kc0" accept` —
     packets on the TUN do not leave the namespace; tun2socks reads them and
     connects on lo, which the ruleset already permits;
  3. starts tun2socks on `tun://kc0` with `socks5://127.0.0.1:1080`, addresses
     the device (198.18.0.1/15), deletes every default route and makes `kc0` the
     default. IPv6 gets no route at all.
  4. in remote DNS mode, starts the stub on 127.0.0.3.
  If the sidecar dies the TUN goes with it, and so does the default route.
- **box** (`kc-box-<id>`) — the distro image, `--network container:<gateway>`,
  `--userns keep-id`, `--init`, started as root running `kc-init`
  (`containers/box/kc-init.sh`, bind-mounted), which installs the baseline once,
  creates the user, writes sudoers and `/etc/profile.d/kiwi-custodia.sh`, and
  holds the container open. `enter` and `run` are `podman exec` as the user into
  `kc-shell`, the user's login shell.

## What a box mounts

| Host | Box | Why |
| --- | --- | --- |
| `…/boxes/<id>/home` | `/home/<user>` | its own home, kept when the container goes |
| `$XDG_RUNTIME_DIR/kiwi-custodia/tunnels/<exit>/resolv.conf` | `/etc/resolv.conf` | the gateway's resolver or the stub; `--dns` cannot be combined with `--network container:` |
| `containers/box/kc-init.sh` | `/usr/local/bin/kc-init` | the first process |
| `$XDG_RUNTIME_DIR/wayland-0`, `bus`, `pipewire-0`, `pulse/native` | the same under `/run/user/<uid>` | display, portals, sound |
| `/tmp/.X11-unix`, `$XAUTHORITY` | the same, `/run/user/<uid>/.Xauthority` | Xwayland clients |
| `/dev/dri` | device | hardware rendering |
| `/etc/localtime` | read-only | the host's clock |

Capabilities: podman's defaults (a distro needs `chown`, `setuid`, …) minus
`NET_RAW` and `NET_ADMIN`; `label=disable` because SELinux's container type
cannot open the Wayland socket, the GPU or a home under `$HOME`;
`no-new-privileges` is **not** set, because `sudo` is a setuid binary.

## Lifecycle

- `boxes.up`: gateway, sidecar, then the box. Each step reuses what runs. The
  distro image is pulled on the first start. Ready when the box logs
  `kc-init: ready`; the first start takes as long as the distro's mirrors take.
- `boxes.stop`: the box container goes. If no other box on the exit runs, the
  sidecar goes and `gateway.release(exit, ignore=(box, sidecar))` lets the
  gateway go unless someone else is inside or it is held.
- `boxes.reap`: box containers without a record or not running, sidecars with
  no running box on their exit, then `gateway.reap()`.
- A box cannot change its exit while running: `set --exit` stops it first.

## Labels

Every container kiwi-custodia starts carries `kiwi-custodia.role` (`box` |
`tunnel`), and a gateway it brought up `kiwi-custodia.role=gateway` beside
kiwi-proxy's own labels. `kiwi-custodia.box` and `kiwi-custodia.exit` say
which; `app=kiwi-custodia` is the family convention.

## On disk

```
~/.local/share/kiwi-custodia/boxes/<id>/box.json    the box
~/.local/share/kiwi-custodia/boxes/<id>/home/       its home
~/.local/share/kiwi-custodia/boxes/<id>/setup.sh    its setup script, for kc-init when it is built
~/.local/share/kiwi-custodia/boxes/<id>/rebuild/    a restored box's recipe, until its next stop
~/.local/share/applications/eu.kiwinetwork.KiwiCustodia.box-<box>-<app>.desktop   an exported app
~/.local/share/applications/eu.kiwinetwork.KiwiCustodia.enter-<id>.desktop        a box's terminal entry
~/.local/share/icons/hicolor/<size>/apps/kc-<box>-<icon>.*                         exported apps' icons
$XDG_RUNTIME_DIR/kiwi-custodia/tunnels/<exit>/resolv.conf
```

## Snapshots

A box's snapshot (in kiwi-proxy's encrypted folder, kind `box`) is a tar of:

```
box.json              the record (name, distro, exit, packages, setup script, exported apps)
home/                 the home without .cache
system/recipe.json    what was added to the system (below)
system/files.tar      the recorded files, read out of the image
```

**Recording** reads the box's committed image (`localhost/kiwi-custodia/box-…`),
never the box: `kc-record` runs in throwaway containers of that image and of the
base image, with `--network none`.

1. `kc-record packages` lists what the package manager says was installed on
   purpose (`dnf repoquery --userinstalled`, `apt-mark showmanual`, `pacman -Qqe`,
   zypper's AutoInstalled, apk's world), with the repository; `@commandline`
   means a file. The base image's list, kc-init's baseline (`kc-init baseline`,
   one list in one place) and the box's declared packages are subtracted.
2. `podman diff` of the two images gives the candidate paths under `/etc`, `/opt`,
   `/usr/local`, `/srv`, `/root` and the apt keyrings, minus this machine's files
   (users, hostname, resolver, sudoers, certificate bundles, kiwi-custodia's own).
3. `kc-record files` keeps the candidates no package owns and the ones changed
   from their package (`rpm -V`, `dpkg --verify`, `pacman -Qkk`, `apk audit`).
4. `kc-record local` gives a file-installed package's files and requirements.
5. The kept files are read out as a tar (`tar -T`), the repository files among
   them listed apart.

**Rebuilding**: a restore writes the recipe to `boxes/<id>/rebuild/` and removes
any image or container of the box on this device. The next `up` starts from the
base image with that folder at `/run/kc-rebuild` (read-only); kc-init, after its
baseline, unpacks the repository files, installs the packages (all at once, else
one by one, naming the failures), the requirements of file-installed packages,
unpacks every file, and writes the snapshot's id to
`/var/lib/kiwi-custodia/rebuilt` so it happens once. Packages that would not
install are listed in `/var/lib/kiwi-custodia/rebuild-missing`, which the image
keeps, and tried again at every start until they install. The setup script is mounted
at `/run/kc-setup.sh` whenever the box starts from its base image and runs once
after that. Exported apps are exported again once the box is up; the first stop
commits the result and the rebuild folder goes.

## Decisions

- **A TUN, not proxy environment variables.** `$ALL_PROXY` covers curl and
  pip; it does not cover a package manager's mirror probe, Steam, an Electron
  app with its own network stack, or anything static. The TUN covers every
  TCP connection the box opens. The variables are set as well, for `.onion`.
- **One sidecar per exit, not per box.** Two boxes on one exit are in one
  namespace: there is one routing table, so there can be one default route.
- **In the gateway's namespace, not a namespace of our own.** A namespace of
  our own would need a second firewall and a second forwarder; the gateway
  has both and kiwi-proxy keeps them right. The one thing added is a rule,
  and it only accepts packets that stay inside.
- **A box is required to have an exit.** A box with no exit would be
  distrobox; the point here is that nothing goes around the tunnel, and a
  state in which something could is not offered.
- **The home is per box.** Sharing the real home would share browser profiles,
  SSH keys and tokens across identities on different exits. Files move with
  `cp`, or the file chooser portal.
- **Not a sandbox from the desktop.** The session bus is the price of
  portals, notifications and the colour scheme; distrobox pays it too. Said
  plainly in the README and in the app.
- **UDP is dropped, not emulated.** tun2socks would carry UDP over SOCKS5
  UDP ASSOCIATE; the forwarder does not offer it and the gateway's promise is
  "no UDP leaves". QUIC falls back to TCP; WebRTC media does not work.
