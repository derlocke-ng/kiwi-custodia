"""The box itself on the desktop: a terminal entry in the app grid, and opening
a terminal into it from the app."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import APP_ID, paths
from .models import Box

ENTRY_PREFIX = f"{APP_ID}.enter-"


def entry_path(box_id: str) -> Path:
    return paths.applications_dir() / f"{ENTRY_PREFIX}{box_id[:8]}.desktop"


def launcher() -> str:
    return shutil.which("kiwi-custodia") or "kiwi-custodia"


def _exec_arg(value: str) -> str:
    if re.search(r"""[\s"'\\><~|&;$*?#()`]""", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def render_entry(box: Box, describe: str) -> str:
    """A terminal into the box, from the app grid; GNOME opens it in the
    default terminal because the entry says Terminal=true."""
    cmd = _exec_arg(launcher())
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={box.name}",
        "GenericName=Kiwi Custodia box",
        f"Comment={describe} — a terminal in the box",
        f"Exec={cmd} enter {box.id}",
        f"Icon={APP_ID}",
        "Terminal=true",
        "Categories=System;TerminalEmulator;",
        f"Keywords=kiwi;custodia;box;{box.distro};{box.name};",
        "StartupNotify=false",
        f"X-KiwiCustodia-Box={box.id}",
        "Actions=stop;",
        "",
        "[Desktop Action stop]",
        "Name=Stop",
        f"Exec={cmd} stop {box.id}",
        "",
    ]
    return "\n".join(lines)


def sync_entry(box: Box, describe: str) -> bool:
    path = entry_path(box.id)
    try:
        if box.desktop_entry:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(render_entry(box, describe))
            tmp.replace(path)
            return True
        path.unlink(missing_ok=True)
        return False
    except OSError:
        return path.exists()


def remove_entry(box_id: str) -> None:
    with contextlib.suppress(OSError):
        entry_path(box_id).unlink(missing_ok=True)


def sync_all(boxes: list[Box], describe: Callable[[Box], str]) -> tuple[list[str], list[str]]:
    with_entry = [b.name for b in boxes if sync_entry(b, describe(b))]
    keep = {entry_path(b.id) for b in boxes if b.desktop_entry}
    removed = []
    for stale in sorted(paths.applications_dir().glob(f"{ENTRY_PREFIX}*.desktop")):
        if stale not in keep:
            with contextlib.suppress(OSError):
                stale.unlink()
                removed.append(stale.name)
    return with_entry, removed


# ------------------------------------------------------------- a terminal
# Terminal emulators and how each takes a command, for when the desktop has no
# xdg-terminal-exec. GNOME's own first.
TERMINALS: tuple[tuple[str, list[str]], ...] = (
    ("xdg-terminal-exec", []),
    ("ptyxis", ["--"]),
    ("kgx", ["--"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("foot", []),
    ("alacritty", ["-e"]),
    ("kitty", []),
    ("wezterm", ["start", "--"]),
    ("xterm", ["-e"]),
)


def terminal_command(command: list[str]) -> list[str] | None:
    """A command line that opens the desktop's terminal running `command`, or
    None when no terminal emulator was found."""
    for exe, sep in TERMINALS:
        if path := shutil.which(exe):
            return [path, *sep, *command]
    return None


def open_terminal(box: Box) -> None:
    """A terminal with a shell in the box, detached from this process."""
    cmd = terminal_command([launcher(), "enter", box.id])
    if cmd is None:
        raise RuntimeError("no terminal emulator found (xdg-terminal-exec, ptyxis, kgx, …)")
    subprocess.Popen(  # noqa: S603
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ},
    )
