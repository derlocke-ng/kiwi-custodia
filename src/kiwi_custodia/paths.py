"""Where everything lives on disk, and what every podman object is called.

XDG, user scope only. Gateways, exits and DNS data are kiwi-proxy's
(``kiwi_proxy.paths``); this is the box side: box records, their homes, the
tunnel sidecars, and the desktop entries written for a box's apps.
"""

from __future__ import annotations

import os
from pathlib import Path

from kiwi_proxy import paths as proxy_paths

APP = "kiwi-custodia"
PREFIX = "kc"  # every podman object name starts with this

# Every container kiwi-custodia starts carries kiwi-custodia.role, so this one
# filter finds all of them; "app" is the shared convention across kiwi apps.
ROLE_LABEL = "kiwi-custodia.role"  # box | tunnel
BOX_LABEL = "kiwi-custodia.box"  # box id, on a box
EXIT_LABEL = "kiwi-custodia.exit"  # exit id, on a box and on a tunnel
DISTRO_LABEL = "kiwi-custodia.distro"  # distro key, on a box
FILTER = f"label={ROLE_LABEL}"

TUNNEL_IMAGE = f"{APP}/tunnel:latest"


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def runtime_dir() -> Path:
    rt = os.environ.get("XDG_RUNTIME_DIR")
    return Path(rt) / APP if rt else cache_dir() / "run"


def applications_dir() -> Path:
    """Where the desktop reads user entries from: exported apps go here."""
    return _xdg("XDG_DATA_HOME", ".local/share") / "applications"


def icons_dir() -> Path:
    """The user's hicolor theme, where exported apps' icons go."""
    return _xdg("XDG_DATA_HOME", ".local/share") / "icons" / "hicolor"


def boxes_dir() -> Path:
    return data_dir() / "boxes"


def box_dir(box_id: str) -> Path:
    return boxes_dir() / box_id


def box_home(box_id: str) -> Path:
    """The box's home directory, kept on the host so the container is disposable."""
    return box_dir(box_id) / "home"


def box_runtime_dir(box_id: str) -> Path:
    d = runtime_dir() / "boxes" / box_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def tunnel_runtime_dir(exit_id: str) -> Path:
    d = runtime_dir() / "tunnels" / exit_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_tree() -> None:
    for d in (data_dir(), config_dir(), boxes_dir(), runtime_dir()):
        d.mkdir(parents=True, exist_ok=True)


def gateway_name(exit_id: str) -> str:
    """The gateway of an exit, as kiwi-proxy names it."""
    return proxy_paths.gateway_name(exit_id)


def box_name(box_id: str) -> str:
    return f"{PREFIX}-box-{box_id[:12]}"


def tunnel_name(exit_id: str) -> str:
    """One tunnel sidecar per exit, shared by every box on it — it sits in the
    gateway's namespace, so there can only be one default route anyway."""
    return f"{PREFIX}-tun-{exit_id[:12]}"
