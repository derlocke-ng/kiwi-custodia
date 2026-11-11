# Changelog

## 0.4.1

- A box's details on a VPN exit say "the VPN itself: TCP and UDP, no sidecar"
  instead of naming a tun2socks sidecar that does not exist there.

## 0.4.0

- **A box on a VPN exit uses the VPN directly: TCP and UDP.** With kiwi-proxy 0.11
  and kiwi-plugin-vpn 0.3, a VPN exit's namespace routes through its tunnel, so a
  box there needs no tun2socks sidecar: games, calls, DNS tools and anything else
  that speaks UDP work, and nothing leaves when the tunnel is down. Other exits
  are as before (TCP through the sidecar).

## 0.3.2

- **Preferences → General:** repair on start (on), what a new box starts with
  (distribution, and an exit or "Ask every time"), and the window size with a Reset.
  Preferences is in the menu even without a snapshot folder.
- **Short texts, the rest behind a (?)** that opens the explanation and a link to
  kiwi-network.eu (shared with Kiwi Proxy 0.8.3).
- The list of boxes up to 920 px wide.

## 0.3.1

- **Repair on start:** the window removes kiwi-custodia's containers a crash or a
  reset left. A box's is committed to its snapshot image first, so nothing
  installed in it is lost; when its storage is gone (it can be neither started nor
  committed) it is removed and the window says so; its home is kept. Any other
  failure leaves it in place. `kiwi-custodia repair` by hand.
- **Tidy up unused containers** no longer removes a stopped box's container
  without committing it first.
- **Check and repair** in the menu: podman's quick storage check, shared with
  Kiwi Proxy and Kiwi Fox. Needs kiwi-proxy 0.8.2.

## 0.3.0

**Boxes on your other devices.** Boxes go into kiwi-proxy's encrypted snapshot
folder, which your sync client (Nextcloud) carries to your other devices. Needs
kiwi-proxy 0.8.1.

- **What a snapshot holds:** the box's record, its home without `.cache`, and
  what was added to its system, recorded from its committed image in throwaway
  containers with no network: the packages you installed (dnf, apt, pacman,
  zypper, apk), the repositories and signing keys you added, the system files
  you added or changed outside the home, and a package installed from a file as
  its files. Not the image.
- **Rebuilt on the other device:** a restored box starts from its base image and
  kc-init puts back, once, the repositories and keys, the packages, the files;
  its exported apps go back into the app grid. The next stop commits the result
  to its own image as usual. A package that does not install (a mirror down, the
  exit slow) is named when the box comes up and tried again at every start until
  it installs.
- **Extra setup script:** in the editor and `kiwi-custodia set --setup-script`;
  it runs once as root after the packages whenever the box is built.
- **When:** after a box ran and stopped (the window catches up on what stopped
  while it was closed), after it changed, and when asked. Before a start, a newer
  copy from another device or the box in use elsewhere asks first; exported apps
  ask in a small window.
- **In the app:** Preferences (Ctrl+,) with the Snapshots page, "Snapshot
  everything now", a banner when snapshots are locked, boxes in the folder that
  are not on this device with Restore, Snapshots… per box, and "What travels to
  another device" in the editor with the sizes.
- **Command line:** `kiwi-custodia snapshot list|now|history|show|restore|forget`,
  `up --as-is` and `--restore`; setup, unlock and lock are kiwi-proxy's
  (`kiwi-custodia snapshot setup` hands over to it).
- A box whose exit is not on this device says to restore that exit in Kiwi Proxy
  first. A restore keeps what was here as a snapshot first, so it can be undone.

## 0.2.3

- **A bigger window, and the size you leave it at.** The window opened at
  760×600, barely larger than its own dialogs, so those came up squeezed. It now
  opens at 1040×840, and the size and maximized state it has when closed are kept
  in `config/window.json` for the next start.

## 0.2.2

- The window said "the first start installs its baseline, give it a minute" on
  every start, a start from the snapshot included; it now says which of the two
  it is, as the command line does since 0.2.1.

## 0.2.1

- **Taking the exit down in Kiwi Proxy no longer empties the box.** A box is a
  container joined to kiwi-proxy's gateway, and taking the exit down — the stop
  button in Kiwi Proxy, `kiwi-proxy down`, a replace, a reap — removes every
  container inside that gateway. The 0.2.0 snapshot was taken by kiwi-custodia's
  own `stop` alone, so the box went with the exit, with everything installed in
  it. A box now carries the `kiwi-proxy.snapshot` label and kiwi-proxy 0.7.1
  commits it to its snapshot image before removing it; the next `up` starts from
  that. A box a reboot or a crash left behind is committed before it is replaced,
  too.
  A box that was already running when this version was installed carries no
  label yet: stop and start it once (`kiwi-custodia stop NAME && kiwi-custodia
  up NAME`, a few seconds from its snapshot).
- `kiwi-custodia up` says whether it starts from the snapshot or from the base
  image (it always said "the first start installs the baseline"), and `stop`
  says the box was kept. A stop whose snapshot failed leaves the container in
  place instead of removing it.
- `install.sh uninstall --purge` removes the snapshot images as well; without
  `--purge` they stay, with the homes.

## 0.2.0

A box keeps what you put in it, speaks bash, and can be any image.

- **A box keeps what was installed in it.** Changing a box's exit (or anything
  else that recreates its container — podman cannot move a container to another
  network namespace) rebuilt it from the base image, and every `dnf install`
  since was gone; only the home survived. The container is now committed to a
  per-box snapshot image when the box stops, and the next start comes from that:
  packages, repositories you added, tools you built stay. `kiwi-custodia reset
  NAME` goes back to the base image (the home stays). `set --package` installs
  what was added since, not the baseline again.
- **The login shell is bash** when the box has it (every baseline installs it),
  or the one you name: `new --shell /usr/bin/zsh`, `set --shell`.
- **More images, or any image.** Presets for the toolbx images of Fedora, Ubuntu,
  Debian and Arch, Kali rolling and Rocky 9 beside the plain ones; and
  `--distro custom --image registry/name:tag` for any OCI image — the package
  manager (dnf, apt, pacman, zypper, apk) is detected on the first start. The app
  has the image and shell fields too.
- `check` says when the exit's proxy refused connections recently (the tunnel
  sidecar sees that; an app only sees an "SSL error").
- `ALL_PROXY` is set in a box's shells only on a remote-DNS exit (Tor), where a
  `.onion` needs it; the default route already is the exit, and Chromium and
  Electron apps that read `all_proxy` choked on the socks5h form ("no internet",
  empty responses). `$KIWI_CUSTODIA_SOCKS` names the gateway's SOCKS5 for tools
  you point at it by hand. The baseline includes gawk: launcher scripts use it
  and the plain Fedora image has no awk.


## 0.1.0

The first version.

- **Boxes**: a distribution (Fedora, Ubuntu, Debian, Arch, openSUSE, Alpine)
  in a rootless Podman container with a home of its own, joined to a
  kiwi-proxy exit's gateway. `new`, `enter`, `run`, `up`, `stop`, `list`,
  `show`, `set`, `rm`, `check`, `reap`, `ps`, `doctor`, `distros`.
- **The tunnel sidecar** (`kc-tun-<exit>`): tun2socks (v2.7.0, pinned by
  checksum) in the gateway's namespace, the TUN as the default route, one
  nftables rule, the permitted destination pinned to the real interface — so a
  box's every TCP connection goes through the exit without proxy settings.
  A DNS stub for exits in remote DNS mode (Tor).
- **The box's first start** (`kc-init`): the family's baseline (sudo, locale,
  Mesa, a font, xdg-utils, curl), the host user with the same uid and
  passwordless sudo, `/etc/profile.d/kiwi-custodia.sh`, `kc-shell`.
- **Desktop**: Wayland, X11, PipeWire/Pulse, the session bus and `/dev/dri`
  passed in; `apps` and `export` put a box's applications in the app grid with
  their own icons; `--desktop-entry` a terminal into the box.
- **The app** (`kiwi-custodia-gui`, GTK 4 + libadwaita): boxes and their state,
  start/stop, a terminal, applications with export, details, the exit (with
  Open Kiwi Proxy), check, logs, setup.
