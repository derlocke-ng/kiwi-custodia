"""First-run setup: the tunnel image, and kiwi-proxy's own setup underneath.

Not done at install time, on purpose: building an image needs the network at
the wrong moment and would make `kiwi install` look broken.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from kiwi_proxy import podman
from kiwi_proxy import setup as proxy_setup

from . import paths

SOURCE_LABEL = "kiwi-custodia.source"
Progress = Callable[[str], None]


class SetupError(RuntimeError):
    pass


def containers_dir() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "containers", here.parents[1] / "containers"):
        if (candidate / "tunnel" / "Containerfile").exists():
            return candidate
    raise SetupError("cannot find the containers/ directory next to the package")


def source_hash(name: str) -> str:
    digest = hashlib.sha256()
    root = containers_dir() / name
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def image_state(image: str = paths.TUNNEL_IMAGE, name: str = "tunnel") -> str:
    """missing | stale | current."""
    if not podman.image_exists(image):
        return "missing"
    label = podman._run(
        ["image", "inspect", "--format", f'{{{{index .Labels "{SOURCE_LABEL}"}}}}', image],
        check=False,
    ).stdout.strip()
    return "current" if label == source_hash(name) else "stale"


def build_tunnel(progress: Progress | None = None, force: bool = False) -> bool:
    root = containers_dir()
    if not force and image_state() == "current":
        return False
    if progress:
        progress("Building the tunnel image (tun2socks)…")
    podman.build(
        paths.TUNNEL_IMAGE,
        str(root / "tunnel" / "Containerfile"),
        str(root / "tunnel"),
        labels={SOURCE_LABEL: source_hash("tunnel")},
    )
    return True


def ready() -> list[str]:
    """What is missing before a box can come up; empty when nothing is."""
    missing = []
    if not podman.available():
        return ["podman is not installed"]
    if image_state() == "missing":
        missing.append("the tunnel image (kiwi-custodia setup)")
    if proxy_setup.image_state(proxy_setup.paths.GATEWAY_IMAGE, "gateway") == "missing":
        missing.append("kiwi-proxy's gateway image (kiwi-custodia setup)")
    return missing


def run(progress: Progress | None = None) -> list[str]:
    """Idempotent: safe to run again at any time."""

    def say(message: str) -> None:
        if progress:
            progress(message)

    steps: list[str] = []
    paths.ensure_tree()
    if not podman.available():
        raise SetupError("podman is not installed")
    say("Setting up kiwi-proxy…")
    try:
        steps += [f"kiwi-proxy: {s}" for s in proxy_setup.run(progress)]
    except proxy_setup.SetupError as exc:
        raise SetupError(f"kiwi-proxy setup failed: {exc}") from exc
    built = build_tunnel(progress)
    steps.append(f"tunnel image: {'built' if built else 'already current'}")
    say("Done.")
    return steps
