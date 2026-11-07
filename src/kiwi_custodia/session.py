"""What of the desktop session a box is given, so its apps open on this desktop.

Each is a socket or device of the running session, mounted at the same path
inside the box so toolkits find it where they expect it. A box gets the session
bus and the display: it is network custody, not a sandbox from the desktop —
say so where people read it (README, the app's New box page).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    uid: int
    gid: int
    user: str
    runtime_dir: str  # /run/user/<uid>, inside the box
    volumes: list[tuple[str, str, str]] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    devices: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_display(self) -> bool:
        return "WAYLAND_DISPLAY" in self.env or "DISPLAY" in self.env


def current(*, gpu: bool = True) -> Session:
    uid, gid = os.getuid(), os.getgid()
    user = os.environ.get("USER") or _passwd_name(uid)
    inside = f"/run/user/{uid}"
    s = Session(uid=uid, gid=gid, user=user, runtime_dir=inside)
    s.env["XDG_RUNTIME_DIR"] = inside
    rt = os.environ.get("XDG_RUNTIME_DIR")
    host_rt = Path(rt) if rt else None

    # Wayland: the compositor's socket.
    disp = os.environ.get("WAYLAND_DISPLAY")
    if host_rt and disp and (host_rt / disp).exists():
        s.volumes.append((str(host_rt / disp), f"{inside}/{disp}", "rw"))
        s.env["WAYLAND_DISPLAY"] = disp
    else:
        s.notes.append("no Wayland socket found; graphical apps cannot open a window")

    # X11, for Xwayland clients: the display socket and the auth cookie.
    x11 = os.environ.get("DISPLAY")
    xsock = Path("/tmp/.X11-unix")
    if x11 and xsock.is_dir():
        s.volumes.append((str(xsock), "/tmp/.X11-unix", "rw"))
        s.env["DISPLAY"] = x11
        xauth = os.environ.get("XAUTHORITY")
        if xauth and Path(xauth).exists():
            s.volumes.append((xauth, f"{inside}/.Xauthority", "ro"))
            s.env["XAUTHORITY"] = f"{inside}/.Xauthority"

    # The session bus: portals (file chooser, settings, notifications), and the
    # desktop's colour scheme reach the box through it.
    if host_rt and (host_rt / "bus").exists():
        s.volumes.append((str(host_rt / "bus"), f"{inside}/bus", "rw"))
        s.env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={inside}/bus"
    else:
        s.notes.append("no session bus; portals and desktop settings will not reach the box")

    # Sound: PipeWire, and its PulseAudio shim for apps that only know that.
    if host_rt and (host_rt / "pipewire-0").exists():
        s.volumes.append((str(host_rt / "pipewire-0"), f"{inside}/pipewire-0", "rw"))
    if host_rt and (host_rt / "pulse" / "native").exists():
        s.volumes.append((str(host_rt / "pulse" / "native"), f"{inside}/pulse/native", "rw"))
        s.env["PULSE_SERVER"] = f"unix:{inside}/pulse/native"

    # Rendering on the real GPU.
    if gpu and Path("/dev/dri").is_dir():
        s.devices.append("/dev/dri")
    elif gpu:
        s.notes.append("no /dev/dri; apps render in software")

    # The clock the apps show. The host's: a box is for using software, and a
    # browser identity that must follow its exit is kiwi-fox's job.
    if Path("/etc/localtime").exists():
        s.volumes.append(("/etc/localtime", "/etc/localtime", "ro"))

    # The theme the desktop uses, by name only; the box's own GTK reads it.
    for key in ("GTK_THEME", "QT_QPA_PLATFORMTHEME", "XCURSOR_THEME", "XCURSOR_SIZE"):
        if val := os.environ.get(key):
            s.env[key] = val
    s.env.setdefault("TERM", os.environ.get("TERM", "xterm-256color"))
    return s


def _passwd_name(uid: int) -> str:
    try:
        import pwd

        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return f"user{uid}"
