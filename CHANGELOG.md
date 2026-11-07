# Changelog

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
