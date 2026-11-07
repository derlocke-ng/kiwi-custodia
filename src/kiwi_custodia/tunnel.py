"""The tunnel sidecar: one per exit, in the gateway's namespace.

A kiwi-proxy gateway offers members a SOCKS5 at 127.0.0.1:1080 and nothing
else — fine for a browser that is told about it, useless for `dnf`, a game
client or a static binary that is not. The sidecar joins the gateway, creates a
TUN device, makes it the namespace's default route and runs tun2socks on it,
so every TCP connection a box opens lands in the forwarder without the box
knowing. See containers/tunnel/entrypoint.sh for the routes and the one
nftables rule it adds.

It is a member of the gateway like any other: `gateway.release` counts it, so a
box being stopped has to take it down first (boxes.stop does) or the gateway
would stay up for it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from kiwi_proxy import gateway, podman
from kiwi_proxy.models import ContainerSpec, Exit

from . import paths

TUN_DEVICE = "kc0"
TUN_ADDR = "198.18.0.1/15"
DNS_STUB = "127.0.0.3"
DNS_UPSTREAM = "1.1.1.1:53"
READY_MARK = "ready — default route is"
LABELS = {"app": paths.APP, paths.ROLE_LABEL: "tunnel"}


class TunnelError(RuntimeError):
    pass


@dataclass
class Tunnel:
    exit_id: str
    name: str
    resolver: str  # what a box puts in /etc/resolv.conf
    reused: bool = False


def resolver_for(ex: Exit) -> str:
    """The nameserver a box on this exit uses: the gateway's own resolver, or the
    sidecar's stub when the exit resolves remotely."""
    return gateway.RESOLVER if ex.dns.mode == "resolver" else DNS_STUB


def spec(ex: Exit, gw_name: str, endpoint_ip: str | None = None) -> ContainerSpec:
    env = {
        "KC_SOCKS": gateway.FORWARDER,
        "KC_TUN": TUN_DEVICE,
        "KC_TUN_ADDR": TUN_ADDR,
        "KC_DNS_MODE": ex.dns.mode,
        "KC_DNS_STUB": DNS_STUB,
        "KC_DNS_UPSTREAM": DNS_UPSTREAM,
    }
    if endpoint_ip:
        env["KC_ENDPOINT_IP"] = endpoint_ip
    return ContainerSpec(
        name=paths.tunnel_name(ex.id),
        image=paths.TUNNEL_IMAGE,
        network=f"container:{gw_name}",
        env=env,
        devices=[podman.TUN_DEVICE],
        cap_drop=["all"],
        # NET_ADMIN for the device, the routes and the one nftables rule;
        # NET_BIND_SERVICE for the DNS stub on :53. No NET_RAW: tun2socks uses a
        # TUN, not raw sockets.
        cap_add=["NET_ADMIN", "NET_BIND_SERVICE"],
        security_opt=["no-new-privileges"],
        # Capabilities over a network namespace are judged in the user namespace
        # that owns it. The gateway runs in podman's rootless one (userns=None);
        # a keep-id container would be in a nested one and could configure
        # nothing, so the sidecar runs where the gateway does.
        userns=None,
        labels={**LABELS, paths.EXIT_LABEL: ex.id},
    )


def is_up(exit_id: str) -> bool:
    return podman.is_running(paths.tunnel_name(exit_id))


def wait_ready(name: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not podman.is_running(name):
            return False
        if READY_MARK in podman.logs(name, tail=100):
            return True
        time.sleep(0.2)
    return False


def up(ex: Exit, gw: gateway.Gateway) -> Tunnel:
    """Bring the exit's sidecar up in its gateway, or hand back the running one."""
    name = paths.tunnel_name(ex.id)
    if podman.is_running(name):
        return Tunnel(ex.id, name, resolver_for(ex), reused=True)
    if not podman.image_exists(paths.TUNNEL_IMAGE):
        raise TunnelError("the tunnel image is missing; run `kiwi-custodia setup`")
    endpoint_ip = podman.container_env(gw.name, "KF_ENDPOINT_IP")
    s = spec(ex, gw.name, endpoint_ip)
    podman.rm(name)
    try:
        podman.start(s)
    except podman.PodmanError as exc:
        raise TunnelError(f"tunnel failed to start: {exc}") from exc
    if not wait_ready(name):
        logs = podman.logs(name)
        podman.rm(name)
        raise TunnelError(f"tunnel did not come up:\n{logs}")
    return Tunnel(ex.id, name, resolver_for(ex))


def down(exit_id: str) -> None:
    podman.rm(paths.tunnel_name(exit_id))


def write_resolv_conf(ex: Exit) -> Path:
    """What a box mounts at /etc/resolv.conf: it has its own mount namespace, and
    --dns cannot be combined with --network container:."""
    path = paths.tunnel_runtime_dir(ex.id) / "resolv.conf"
    path.write_text(f"nameserver {resolver_for(ex)}\noptions edns0 trust-ad\n")
    return path
