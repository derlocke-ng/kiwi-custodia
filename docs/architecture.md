# How it works

This page is for readers who want to know what runs where: the containers of
a running box, what a box mounts, how it starts and stops, and why it is built
this way. To use kiwi-custodia, [Boxes](boxes.md) and
[Exits and the network](exits.md) are enough.

## The containers of a running box

A running box is two or three containers that share one network namespace,
the exit's. A network namespace is a separate set of network interfaces,
routes and firewall rules.

In the names on this page, `<id>` and `<exit>` stand for the id of a box and
of an exit. Container names carry their first 12 characters, the names of a
box's image and its own app-grid entry the first 8, and the box's folder the
whole id.

- **gateway** (`kf-gw-<exit>`): kiwi-proxy's container for the exit. It owns
  the namespace, its nftables firewall drops everything except the way to the
  exit, its forwarder at 127.0.0.1:1080 adds the exit's credentials, and its
  resolver at 127.0.0.2 answers DNS. kiwi-custodia starts it with
  `gateway.up(exit, labels=…, measure=False)`, as kiwi-fox does, and reuses it
  when it already runs for the exit, for another box, a kiwi-fox profile or
  `kiwi-proxy up`.
- **tunnel** (`kc-tun-<exit>`): kiwi-custodia's, one per exit, only on exits
  that are not VPN exits. It is described below.
- **box** (`kc-box-<id>`): the distribution's image, joined to the gateway
  with `--network container:<gateway>`. It has no network interfaces of its
  own.

On a **VPN exit** (kiwi-proxy 0.11 and kiwi-plugin-vpn 0.3 or newer), the
gateway itself joins the namespace of the VPN's container, whose default route
is the VPN tunnel. kiwi-proxy's `gateway.is_tunnel(exit)` says which exits
these are. A box there needs no tunnel container: TCP and UDP go straight
through the VPN, and nothing leaves while the tunnel is down.

## The tunnel container

On every other exit, the gateway offers only its SOCKS5 forwarder. The tunnel
container makes the namespace's default route lead into it:

```
                   ┌──────────────────────── gateway netns (kiwi-proxy) ────────────────────────┐
                   │ nftables output: default drop                                              │
                   │   ct established · lo · <one permitted address>:<port> · oifname kc0 (ours) │
 box ──────────────┼─► default route: kc0 ──► tun2socks ──► forwarder 127.0.0.1:1080 ───────────┼──► upstream
 (keep-id, your    │                                          (adds the exit's credentials)     │    SOCKS5
  user, own home)  │ resolver 127.0.0.2:53 (resolver mode) ─ DoH through the forwarder          │
                   │ kc-dnsstub 127.0.0.3:53 (remote mode) ─ DNS over TCP through the forwarder │
                   └─────────────────────────────────────────────────────────────────────────────┘
```

It runs with `--network container:<gateway>`, `NET_ADMIN`, `NET_BIND_SERVICE`
and `/dev/net/tun`, every other capability dropped, `no-new-privileges`, and
no user namespace of its own. Capabilities over a network namespace count in
the user namespace that owns it, and the gateway's is Podman's rootless one.
Its entrypoint,
[containers/tunnel/entrypoint.sh](https://github.com/derlocke-ng/kiwi-custodia/blob/main/containers/tunnel/entrypoint.sh):

1. refuses to start unless the namespace has kiwi-proxy's `inet kiwiproxy`
   table;
2. reads the gateway's permitted destination (from the gateway's environment,
   otherwise from its ruleset) and pins a host route to it on the real
   interface, unless it is on-link, as a provider on the `kf-providers`
   network is;
3. inserts one rule into the gateway's output chain, `oifname "kc0" accept`.
   Packets on the TUN do not leave the namespace: tun2socks reads them and
   connects to the forwarder on `lo`, which the ruleset already permits;
4. starts tun2socks on `tun://kc0` with `socks5://127.0.0.1:1080`, gives the
   device the address 198.18.0.1/15, deletes every IPv4 default route and makes
   `kc0` the default. IPv6 gets no route at all;
5. in remote DNS mode, starts a small resolver at 127.0.0.3 that sends each
   query over TCP through the forwarder to 1.1.1.1.

If the tunnel container stops, the TUN device goes with it, and so does the
default route: the box has no route at all.

## What a box mounts

| Host | Box | Why |
|---|---|---|
| `~/.local/share/kiwi-custodia/boxes/<id>/home` | `/home/<user>` | Its own home, kept when the container goes. |
| `$XDG_RUNTIME_DIR/kiwi-custodia/tunnels/<exit>/resolv.conf` | `/etc/resolv.conf` (read-only) | The gateway's resolver or the tunnel's; `--dns` cannot be combined with `--network container:`. |
| `containers/box/kc-init.sh` | `/usr/local/bin/kc-init` (read-only) | The box's first process. |
| `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY`, `bus`, `pipewire-0`, `pulse/native` | The same under `/run/user/<uid>` | Display, portals, sound. |
| `/tmp/.X11-unix`, `$XAUTHORITY` | The same, and `/run/user/<uid>/.Xauthority` | Programs that need Xwayland. |
| `/dev/dri` | Device | Hardware rendering; not with `--no-gpu`. |
| `/etc/localtime` | Read-only | The host's time zone. |
| `boxes/<id>/rebuild/` | `/run/kc-rebuild` (read-only) | Only for a box restored from a snapshot, until it is rebuilt. |
| `boxes/<id>/setup.sh` | `/run/kc-setup.sh` (read-only) | Only when the box starts from its base image and has a setup script. |

The box runs with `--userns keep-id`, `--init` and `--shm-size 1g`, and starts
as root to run `kc-init`. Its capabilities are Podman's defaults, which a
package manager needs (`chown`, `setuid` …), minus `NET_RAW` and `NET_ADMIN`.
It runs with `label=disable`, because SELinux's container type cannot open
the Wayland socket, the GPU or a home under `$HOME`. `no-new-privileges` is
**not** set, because `sudo` is a setuid program.

## The first process

`kc-init`
([containers/box/kc-init.sh](https://github.com/derlocke-ng/kiwi-custodia/blob/main/containers/box/kc-init.sh))
is POSIX sh, so it also runs on busybox. At every start it:

1. finds the package manager when the image is a custom one; at the first
   start, installs the baseline and the box's packages, and at later starts
   only the packages added since;
2. for a restored box, rebuilds the system once from `/run/kc-rebuild`;
3. runs the setup script once, when one is mounted;
4. creates your user with your uid and gid, gives it passwordless `sudo`,
   and writes `/etc/profile.d/kiwi-custodia.sh` and
   `/usr/local/bin/kc-shell`, which starts your login shell; `enter` and `run`
   start it with `podman exec`;
5. logs `kc-init: ready` and holds the container open.

A failed package install logs a warning; the box still comes up.

## Starting and stopping

- **Start** (`boxes.up`): the gateway, the tunnel container when the exit
  needs one, then the box. Each step reuses what already runs. The box starts
  from its saved image when it has one, otherwise from its base image, which
  Podman pulls when it is not there. It is ready when it logs
  `kc-init: ready`.
- **Stop** (`boxes.stop`): the box's container is committed to its saved
  image, `localhost/kiwi-custodia/box-<id>:latest`, and removed. If no other
  box on the exit runs, the tunnel container goes, and
  `gateway.release(exit, ignore=(box, tunnel))` lets the gateway go unless
  something else uses it.
- **Tidy up** (`boxes.reap`): box containers without a record or not
  running, tunnel containers with no running box on their exit, then
  kiwi-proxy's `gateway.reap()`. A box's container is committed first.
- **Repair** (`boxes.repair`): kiwi-custodia's containers that kiwi-proxy's
  `storage.leftovers()` reports. A box's container is committed first; when
  its storage is damaged so that it cannot be committed, it is removed and its
  home is kept.

A box cannot change its exit while it runs, because Podman cannot move a
container to another namespace: `set --exit` stops it first.

## Labels

Every container kiwi-custodia starts carries `kiwi-custodia.role` (`box` or
`tunnel`), and a gateway it started carries `kiwi-custodia.role=gateway` next
to kiwi-proxy's own labels. `kiwi-custodia.box`, `kiwi-custodia.exit` and
`kiwi-custodia.distro` say which; `app=kiwi-custodia` is the convention of the
Kiwi apps. A box also carries `kiwi-proxy.snapshot` with the name of its saved
image: kiwi-proxy 0.7.1 and newer commit the box to it before they remove it
along with the exit's gateway.

## Snapshots inside

A box's snapshot, kind `box` in kiwi-proxy's encrypted folder, is a tar of:

```
box.json              the record (name, distribution, exit, packages, setup script, exported apps)
home/                 the home without .cache
system/recipe.json    what was added to the system (below)
system/files.tar      the recorded files, read out of the image
```

**Recording** reads the box's saved image, never the running box. `kc-record`
([containers/box/kc-record.sh](https://github.com/derlocke-ng/kiwi-custodia/blob/main/containers/box/kc-record.sh))
runs in throwaway containers of that image and of the base image, with
`--network none`:

1. `kc-record packages` lists what the package manager says was installed on
   purpose (`dnf repoquery --userinstalled`, `apt-mark showmanual`,
   `pacman -Qqe`, zypper's `AutoInstalled`, apk's `world`), with the
   repository. The base image's list, kc-init's baseline (`kc-init baseline`,
   one list in one place) and the box's declared packages are subtracted.
2. `podman diff` of the two images gives the candidate paths under `/etc`,
   `/opt`, `/usr/local`, `/srv`, `/root` and the apt keyrings, minus this
   machine's files (users, hostname, resolver, sudoers, certificate bundles,
   kiwi-custodia's own).
3. `kc-record files` keeps the candidates no package owns and the ones changed
   from their package (`rpm -V`, `dpkg --verify`, `pacman -Qkk`, `apk audit`).
4. `kc-record local` gives the files and, on rpm systems, the requirements of
   a package installed from a file.
5. The kept files are read out as a tar, the repository files among them
   listed apart.

**Rebuilding**: a restore writes the recipe to `boxes/<id>/rebuild/` and
removes any image or container of the box on this device. The next start
begins from the base image with that folder at `/run/kc-rebuild`. After its
baseline, kc-init unpacks the repository files, installs the packages (all at
once, else one by one, naming the failures), the requirements of
file-installed packages, unpacks every file, and writes the snapshot's id to
`/var/lib/kiwi-custodia/rebuilt` so that it happens once. Packages that would
not install are listed in `/var/lib/kiwi-custodia/rebuild-missing`, which the
image keeps, and tried again at every start until they install. Exported apps
are exported again once the box is up; the first stop commits the result, and
the rebuild folder goes.

## Decisions

- **A TUN, not proxy environment variables.** `$ALL_PROXY` covers curl and
  pip. It does not cover a package manager's mirror probe, Steam, an Electron
  app with its own network stack, or a static program. The TUN covers every
  TCP connection the box opens. `ALL_PROXY` is set only on remote-DNS exits,
  where a `.onion` address needs it.
- **The VPN itself where there is one.** On a VPN exit the namespace already
  routes through the tunnel, so a tunnel container would only take UDP away.
- **One tunnel container per exit, not per box.** Two boxes on one exit are in
  one namespace. There is one routing table, so there can be one default route.
- **In the gateway's namespace, not a namespace of its own.** A namespace of
  its own would need a second firewall and a second forwarder. The gateway has
  both, and kiwi-proxy keeps them right. The one thing added is a rule, and it
  only accepts packets that stay inside.
- **A box must have an exit.** A box without an exit would be distrobox. The
  point here is that nothing goes around the tunnel, and a state in which
  something could is not offered.
- **The home is per box.** Sharing your real home would share browser
  profiles, SSH keys and tokens across identities on different exits. Files
  move with `cp`, or with the file chooser portal.
- **Not a sandbox from the desktop.** The session bus is the price of portals,
  notifications and the colour scheme; distrobox pays it too. The README and
  the app say so.
- **UDP is dropped on SOCKS5 exits, not carried.** tun2socks could carry UDP
  over SOCKS5 UDP ASSOCIATE, but the forwarder does not offer it, and the
  gateway promises that no UDP leaves. QUIC falls back to TCP; WebRTC media
  does not work. A box that needs UDP goes on a VPN exit.
