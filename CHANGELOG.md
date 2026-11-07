# Changelog

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
