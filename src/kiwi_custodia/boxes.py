"""Box -> gateway + tunnel + container -> lifecycle.

Bringing a box up: its exit's gateway (kiwi-proxy's, shared with whoever else
uses the exit), the tunnel sidecar in that gateway (ours, shared by every box
on the exit), then the box container joined to the same namespace. The box has
no interfaces of its own; its default route is the sidecar's TUN; if either
dies it has no route. Stopping a box removes its container, the sidecar when no
other box on the exit runs, and lets go of the gateway the way kiwi-fox does.
"""

from __future__ import annotations

import contextlib
import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from kiwi_proxy import endpoint, exits, gateway, podman, providers
from kiwi_proxy.models import Exit, ExitInfo

from . import distros, paths, session, store, tunnel
from .models import Box, BoxState

INIT_SCRIPT = "/usr/local/bin/kc-init"
SHELL = "/usr/local/bin/kc-shell"
READY_MARK = "kc-init: ready"
# Said on a gateway this app brought up; the gateway is the exit's and shared.
GATEWAY_LABELS = {"app": paths.APP, "kiwi-custodia.role": "gateway"}
_NETWORK_ERRORS = (
    gateway.GatewayError,
    providers.ProviderError,
    endpoint.EndpointError,
    podman.PodmanError,
    tunnel.TunnelError,
)


class BoxError(RuntimeError):
    pass


@dataclass
class BoxUp:
    box: Box
    gateway: str
    tunnel: str
    container: str
    reused: bool = False  # the container was already running
    first_start: bool = False  # the init installed its baseline this time
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------- pieces
REBUILD_DIR = "/run/kc-rebuild"
SETUP_FILE = "/run/kc-setup.sh"


def rebuild_pending(box: Box) -> bool:
    """Restored from a snapshot and not yet rebuilt into an image of its own."""
    return (paths.box_rebuild_dir(box.id) / "id").is_file()


def init_script() -> Path:
    """containers/box/kc-init.sh, in a checkout or an installed copy."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "containers", here.parents[1] / "containers"):
        path = candidate / "box" / "kc-init.sh"
        if path.exists():
            return path
    raise BoxError("cannot find containers/box/kc-init.sh next to the package")


def exit_of(box: Box) -> Exit:
    try:
        return store.exit_of(box)
    except store.StoreError as exc:
        raise BoxError(str(exc)) from exc


def home_in_box(sess: session.Session) -> str:
    return f"/home/{sess.user}"


def run_args(
    box: Box,
    ex: Exit,
    gw_name: str,
    resolv_conf: str,
    sess: session.Session,
    *,
    detach: bool = True,
    image: str | None = None,
    rebuild: bool = False,
    setup: bool = False,
) -> list[str]:
    """The `podman run` for a box. Rendered apart from running it so it can be
    tested without podman.

    keep-id so files in the home are the user's on both sides; container-root
    for the init, which creates that user and installs packages; podman's
    default capability set (sudo, package managers and chown need it — this is a
    distro, not a sealed service) but no NET_ADMIN and no NET_RAW; --init so
    whatever an app leaves behind is reaped."""
    d = distros.get(box.distro)
    home = home_in_box(sess)
    args = [
        "run",
        "--replace",
        "--name",
        paths.box_name(box.id),
        "--hostname",
        box.host,
        "--network",
        f"container:{gw_name}",
        "--userns",
        "keep-id",
        "--user",
        "root:root",
        "--init",
        "--shm-size",
        "1g",
        # SELinux's container type cannot reach the Wayland socket, the GPU or a
        # home under $HOME; the box runs unlabelled, as kiwi-fox's browsers do.
        "--security-opt",
        "label=disable",
        "--cap-drop",
        "NET_RAW",
        "--cap-drop",
        "NET_ADMIN",
    ]
    if detach:
        args.append("--detach")
    env = {
        "KC_USER": sess.user,
        "KC_UID": str(sess.uid),
        "KC_GID": str(sess.gid),
        "KC_HOME": home,
        "KC_FAMILY": d.family,  # "auto": kc-init detects the package manager
        "KC_SHELL": box.shell or "",
        "KC_PACKAGES": " ".join(box.packages),
        "KC_SOCKS": gateway.FORWARDER,
        # ALL_PROXY in the box's shells only on a remote-DNS exit (Tor), where a
        # .onion needs it; otherwise the default route is the exit and the
        # variable only confuses Chromium/Electron apps.
        "KC_PROXY_ENV": "1" if ex.dns.mode == "remote" else "0",
        "KC_BOX": box.name,
        "KC_EXIT_NAME": ex.name,
        **sess.env,
    }
    for key, val in sorted(env.items()):
        args += ["--env", f"{key}={val}"]
    volumes = [
        (str(paths.box_home(box.id)), home, "rw"),
        (resolv_conf, "/etc/resolv.conf", "ro"),
        (str(init_script()), INIT_SCRIPT, "ro"),
        *sess.volumes,
    ]
    if rebuild:
        # restored from a snapshot: kc-init rebuilds the system from this, once
        volumes.append((str(paths.box_rebuild_dir(box.id)), REBUILD_DIR, "ro"))
    if setup:
        # its setup script: kc-init runs it once, when the box is built
        volumes.append((str(paths.box_setup_script(box.id)), SETUP_FILE, "ro"))
    for src, dst, opts in volumes:
        args += ["--volume", f"{src}:{dst}:{opts}"]
    for dev in sess.devices:
        args += ["--device", dev]
    labels = {
        "app": paths.APP,
        paths.ROLE_LABEL: "box",
        paths.BOX_LABEL: box.id,
        paths.EXIT_LABEL: ex.id,
        paths.DISTRO_LABEL: box.distro,
        paths.SNAPSHOT_LABEL: paths.box_image(box.id),  # kiwi-proxy keeps it before removing it
    }
    for key, val in sorted(labels.items()):
        args += ["--label", f"{key}={val}"]
    args += [image or box.image, INIT_SCRIPT]
    return args


# -------------------------------------------------------------- snapshots
def has_snapshot(box: Box) -> bool:
    return podman.image_exists(paths.box_image(box.id))


def image_size(box: Box) -> int:
    """The size of the box's snapshot image (what stays on this device); 0 when
    it has none."""
    proc = podman._run(
        ["image", "inspect", "--format", "{{.Size}}", paths.box_image(box.id)], check=False
    )
    try:
        return int(proc.stdout.strip()) if proc.returncode == 0 else 0
    except ValueError:
        return 0


def snapshot(box: Box) -> bool:
    """Commit the box's container to its snapshot image, so what was installed
    in it (packages, a repo you added, a tool built from source) survives the
    container being recreated — for another exit, a hostname, a new base image.
    The home is a host directory and never needed this. False when there is no
    container to commit."""
    name = paths.box_name(box.id)
    if not podman.exists(name):
        return False
    image = paths.box_image(box.id)
    proc = podman._run(["commit", "-q", "--pause=false", name, image], check=False, timeout=600)
    if proc.returncode != 0:
        raise BoxError(f"could not keep the box's contents: {proc.stderr.strip()}")
    if not podman.image_exists(image):
        raise BoxError(f"podman commit returned but {image} is not there; the box is left running")
    return True


def forget_snapshot(box: Box) -> None:
    podman._run(["rmi", "-f", paths.box_image(box.id)], check=False)


def exec_args(
    box: Box,
    command: list[str] | None,
    *,
    tty: bool = True,
    user: str | None = None,
    workdir: str | None = None,
    sess: session.Session | None = None,
) -> list[str]:
    """`podman exec` into a running box as the user, in a login shell: the whole
    command line for `enter` (no command) or `run` (a command)."""
    sess = sess or session.current(gpu=box.gpu)
    home = "/root" if user in ("root", "0") else home_in_box(sess)
    args = ["exec", "--interactive"]
    if tty:
        args.append("--tty")
    args += [
        "--user",
        user or f"{sess.uid}:{sess.gid}",
        "--workdir",
        workdir or home,
        "--env",
        f"HOME={home}",
        "--env",
        f"TERM={sess.env.get('TERM', 'xterm-256color')}",
        paths.box_name(box.id),
        SHELL,
    ]
    if command:
        args += ["-c", shlex.join(command)]
    return args


# ----------------------------------------------------------------- lifecycle
def _network_error(exc: Exception) -> BoxError:
    return BoxError(str(exc))


def gateway_up(box: Box) -> tuple[Exit, gateway.Gateway]:
    ex = exit_of(box)
    try:
        return ex, gateway.up(ex, labels=dict(GATEWAY_LABELS), measure=False)
    except _NETWORK_ERRORS as exc:
        raise _network_error(exc) from exc


def wait_ready(name: str, timeout: float) -> tuple[bool, bool]:
    """(ready, first start). The first start installs packages, which takes as
    long as the distro's mirrors take."""
    deadline = time.monotonic() + timeout
    first = False
    while time.monotonic() < deadline:
        if not podman.is_running(name):
            return False, first
        logs = podman.logs(name, tail=50)
        if "first start" in logs:
            first = True
        if READY_MARK in logs:
            return True, first
        time.sleep(0.3)
    return False, first


def _could_not_install(logs: str) -> list[str]:
    """The packages kc-init said it could not install at this start."""
    found: list[str] = []
    for line in logs.splitlines():
        _, mark, rest = line.partition("WARNING: could not install:")
        if mark:
            for pkg in rest.split("(")[0].split():
                if pkg not in found:
                    found.append(pkg)
    return found


def up(box: Box, *, timeout: float = 900.0) -> BoxUp:
    """Bring the box up, or hand back the one already running."""
    if not podman.available():
        raise BoxError("podman not found")
    name = paths.box_name(box.id)
    ex, gw = gateway_up(box)
    notes = list(gw.notes)
    try:
        tun = tunnel.up(ex, gw)
    except _NETWORK_ERRORS as exc:
        gateway.release(ex.id)
        raise _network_error(exc) from exc
    if podman.is_running(name):
        return BoxUp(box, gw.name, tun.name, name, reused=True, notes=notes)
    if podman.exists(name):
        # Left behind by a crash or a reboot: what is in it is kept before
        # --replace starts a new one.
        snapshot(box)

    image = box.image
    rebuild = False
    if has_snapshot(box):
        image = paths.box_image(box.id)  # the box as it was when last stopped
        notes.append("from its snapshot: what was installed is still there")
    elif rebuild_pending(box):
        rebuild = True
        notes.append("restored from a snapshot: its packages and files are put back at this start")
    elif podman.image_exists(box.image):
        notes.append(f"from the base image {box.image}: a fresh box, the baseline gets installed")
    elif not podman.image_exists(box.image):
        notes.append(f"pulling {box.image}")
        try:
            podman.pull(box.image)
        except podman.PodmanError as exc:
            _let_go(box, ex.id, name)
            raise BoxError(f"could not pull {box.image}: {exc}") from exc

    sess = session.current(gpu=box.gpu)
    notes += sess.notes
    resolv = tunnel.write_resolv_conf(ex)
    setup = image == box.image and bool(box.setup_script.strip())
    if setup:
        script = paths.box_setup_script(box.id)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(box.setup_script.rstrip() + "\n")
        notes.append("its setup script runs once, after the packages")
    args = run_args(box, ex, gw.name, str(resolv), sess, image=image, rebuild=rebuild, setup=setup)
    podman.rm(name)
    try:
        podman._run(args, timeout=180)
    except podman.PodmanError as exc:
        _let_go(box, ex.id, name)
        raise BoxError(f"box failed to start: {exc}") from exc
    ready, first = wait_ready(name, timeout)
    if not ready:
        logs = podman.logs(name)
        if not podman.is_running(name):
            _let_go(box, ex.id, name)
            raise BoxError(f"box exited during start:\n{logs}")
        notes.append("the box did not report ready in time; its init may still be installing")
    elif missing := _could_not_install(podman.logs(name, tail=200)):
        notes.append(f"could not install {', '.join(missing)}; tried again at the next start")
    store.save(box)
    from . import snapshots as box_snapshots  # late: it imports this module

    box_snapshots.started(box)
    if rebuild and ready:
        box_snapshots.rebuilt(box)
    return BoxUp(box, gw.name, tun.name, name, first_start=first, notes=notes)


def _others_running(exit_id: str, *, except_box: str) -> bool:
    return any(
        b.id != except_box and podman.is_running(paths.box_name(b.id))
        for b in store.boxes_on(exit_id)
    )


def _let_go(box: Box, exit_id: str, name: str) -> None:
    """After a failed start: the container, and the exit's sidecar and gateway
    unless another box on the exit runs."""
    podman.rm(name)
    if not _others_running(exit_id, except_box=box.id):
        tunnel.down(exit_id)
        with contextlib.suppress(Exception):
            gateway.release(exit_id, ignore=(name, paths.tunnel_name(exit_id)))


def stop(box: Box, *, keep: bool = True) -> str | None:
    """The box's container goes — committed to its snapshot first (`keep`), so
    the next start has everything that was installed in it. The exit's sidecar
    goes with it unless another box on the exit is running; the gateway goes
    unless something else — a kiwi-fox browser, a pentest tool, `kiwi-proxy up`
    — still uses it. With `keep`, a box that ran since its last snapshot in the
    snapshot folder gets one; the return is a line when that did not work."""
    if not podman.available():
        return None
    name = paths.box_name(box.id)
    was = podman.exists(name)
    if keep and was:
        snapshot(box)  # raises, and the container stays, rather than lose its contents
    podman.rm(name)
    if not _others_running(box.exit, except_box=box.id):
        tun = paths.tunnel_name(box.exit)
        tunnel.down(box.exit)
        with contextlib.suppress(Exception):
            gateway.release(box.exit, ignore=(name, tun))
    if not (keep and was):
        return None
    from . import snapshots as box_snapshots  # late: it imports this module

    note = box_snapshots.after_stop(box) if box_snapshots.available() else None
    box_snapshots.settled(box)
    return note


def running(box: Box) -> bool:
    return podman.is_running(paths.box_name(box.id))


def ours() -> list[dict]:
    """Every container kiwi-custodia started, running or not, with its labels."""
    if not podman.available():
        return []
    out = podman._run(
        ["ps", "--all", "--format", "json", "--filter", paths.FILTER], check=False
    ).stdout.strip()
    return json.loads(out) if out else []


def state(box: Box) -> BoxState:
    if running(box):
        return "running" if gateway.is_up(box.exit) and tunnel.is_up(box.exit) else "gateway-down"
    return "stopped"


def exec_(box: Box, command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    """A command in the running box, as the user, captured."""
    args = exec_args(box, command, tty=False)
    return podman._run(args, check=False, timeout=timeout)


def check(box: Box) -> ExitInfo:
    """What the world sees from inside the box, through the TUN — the whole
    path a box's apps take, not just the forwarder."""
    if not running(box):
        raise BoxError(f"box {box.name!r} is not running")
    failures = []
    for url in endpoint.GEO_URLS:
        proc = exec_(box, ["curl", "-fsS", "--max-time", "25", url], timeout=45)
        if proc.returncode != 0:
            failures.append((proc.stderr or proc.stdout).strip() or f"{url}: failed")
            continue
        try:
            return endpoint.parse_geo(proc.stdout)
        except endpoint.EndpointError as exc:
            failures.append(f"{url}: {exc}")
    refused = _recent_refusals(box.exit)
    if refused:
        failures.append(
            "the exit's proxy refused connections recently (a refused connection looks "
            f"like an SSL error to the app): {refused}"
        )
    raise BoxError("; ".join(failures) or "exit probe failed")


def _recent_refusals(exit_id: str) -> str:
    """What tun2socks logged about CONNECTs the exit's proxy refused: the one
    thing a box cannot see from inside, and the usual reason for 'SSL errors'
    on an otherwise working exit."""
    try:
        lines = podman.logs(paths.tunnel_name(exit_id), tail=200).splitlines()
    except Exception:  # noqa: BLE001
        return ""
    hits = [ln for ln in lines if "SOCKS server failure" in ln or "CONNECT:" in ln]
    hosts = []
    for ln in hits[-5:]:
        if "dial " in ln:
            hosts.append(ln.split("dial ", 1)[1].split(":", 1)[0])
    return ", ".join(dict.fromkeys(hosts)) if hosts else ""


def delete(box: Box) -> None:
    """Stop it, take its desktop entries away, remove the record and the home."""
    from . import apps, desktop

    stop(box, keep=False)
    forget_snapshot(box)
    apps.unexport_all(box)
    desktop.remove_entry(box.id)
    store.delete(box.id)


def reset(box: Box) -> None:
    """Back to the base image: the container and its snapshot go, the home
    stays; the next start installs the baseline again."""
    stop(box, keep=False)
    forget_snapshot(box)
    import shutil

    shutil.rmtree(paths.box_rebuild_dir(box.id), ignore_errors=True)


def reap() -> list[str]:
    """Containers of boxes that no longer exist, sidecars without a running box,
    and then whatever kiwi-proxy finds unused."""
    if not podman.available():
        return []
    cleaned: list[str] = []
    known = {paths.box_name(b.id): b for b in store.list_boxes()}
    for row in ours():
        name = (row.get("Names") or [""])[0]
        lab = row.get("Labels") or {}
        role = lab.get(paths.ROLE_LABEL)
        if role == "box" and (name not in known or row.get("State") != "running"):
            podman.rm(name)
            cleaned.append(name)
        elif role == "tunnel":
            exit_id = lab.get(paths.EXIT_LABEL, "")
            if not any(podman.is_running(paths.box_name(b.id)) for b in store.boxes_on(exit_id)):
                podman.rm(name)
                cleaned.append(name)
                with contextlib.suppress(Exception):
                    gateway.release(exit_id, ignore=(name,))
    names = {paths.gateway_name(e.id): e.name for e in exits.list_exits()}
    cleaned += [names.get(n, n) for n in gateway.reap()]
    return cleaned
