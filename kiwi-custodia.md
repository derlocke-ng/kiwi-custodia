# kiwi-custodia — working notes

## What this is

The third consumer of kiwi-proxy, after kiwi-fox (browsers) and kiwi-pentesting
(tools): **host-grade distro containers whose every byte leaves through an
exit**. distrobox over SOCKS5. See README.md for the user's view and
docs/architecture.md for how the three containers fit in one namespace.

## Rules

- The exit is kiwi-proxy's. Never define, edit or delete an exit here; open
  Kiwi Proxy for that. `store.exit_of(box)` loads it; `gateway.up()` brings
  it up. The gateway is shared and released with `ignore=(box, sidecar)`.
- Fail closed, by construction. Nothing in this app ever gives a box a route
  that is not the TUN. The sidecar's entrypoint deletes every default route
  before adding its own, and does not try to "repair" a gateway whose
  ruleset it does not recognise (`nft list table inet kiwiproxy` must exist).
- The sidecar runs in podman's rootless user namespace (`userns=None`), like
  the gateway. A keep-id container has NET_ADMIN only in a nested user
  namespace and cannot configure the gateway's netns. Do not "fix" this.
- The box is not sealed from the desktop and the README says so. Do not add
  `no-new-privileges` to the box (sudo is setuid) and do not drop podman's
  default capabilities below what a package manager needs. Do drop NET_RAW and
  NET_ADMIN.
- `kc-init.sh` is POSIX sh and runs on busybox. Every package manager call is
  tolerant: a failed baseline logs a warning and the box still comes up
  (`exec --user root` works regardless).
- Specs are rendered apart from running them (`boxes.run_args`,
  `tunnel.spec`) and tested with a fake podman (tests/unit/conftest.py); the
  real namespace behaviour needs a machine with podman.
- Snapshots record from the box's committed image, never from a running box:
  `kc-record.sh` (POSIX sh, like kc-init) runs in throwaway `--network none`
  containers. kc-init's baseline list lives in kc-init alone (`kc-init
  baseline`); recipe.py asks it rather than keeping a copy. A restore removes
  any image of the box on this device, so the next start is the rebuild.

## Things to verify on a real machine (not yet measured)

- tun2socks creating `kc0` as container-root with NET_ADMIN in a rootless
  gateway — kiwi-proxy's VPN module creates a TUN the same way, so it should.
- That `oifname "kc0" accept` is enough: replies written by tun2socks arrive
  via kc0 as `ct established`. If a client sees SYNs leave and nothing come
  back, look at the input chain first.
- `--init` on hosts without catatonit (podman errors out). Fall back to
  running without it if that turns out to be common.
- Xwayland auth: `$XAUTHORITY` is mounted at `/run/user/<uid>/.Xauthority`.
  GNOME's mutter cookie path is under `$XDG_RUNTIME_DIR`; other compositors
  may differ.
- The icon copy for exported apps uses `podman cp` per file; a theme with
  twelve sizes makes twelve calls. Fine, but slow on a loaded machine.
