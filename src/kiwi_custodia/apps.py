"""A box's applications in the host's app grid.

What a box installs lands in its /usr/share/applications; this reads those
entries out, and `export` writes one on the host that runs the app through
`kiwi-custodia run` — with the app's own icon, copied out, and its name
suffixed with the box, so two boxes' Firefoxes are told apart. What distrobox
calls distrobox-export.
"""

from __future__ import annotations

import contextlib
import re
import shlex
import shutil
from pathlib import Path

from kiwi_proxy import podman

from . import APP_ID, paths, store
from .models import Box, ExportedApp

APP_DIRS = ("/usr/share/applications", "/usr/local/share/applications")
ICON_DIRS = ("/usr/share/icons/hicolor", "/usr/share/pixmaps")
ENTRY_PREFIX = f"{APP_ID}.box-"
# %f %F %u %U and friends: the host cannot hand the box its files.
_FIELD_CODES = re.compile(r"\s?%[a-zA-Z%]")


class AppError(RuntimeError):
    pass


# ---------------------------------------------------------------- reading
def parse_entry(text: str, file_id: str) -> ExportedApp | None:
    """The [Desktop Entry] group of one file; None if it is not an application."""
    section = None
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Localised keys (Name[de]) are left to the host's own locale handling;
        # the exported entry carries the untranslated one.
        if "[" in key or key in fields:
            continue
        fields[key] = val.strip()
    if fields.get("Type", "Application") != "Application" or not fields.get("Exec"):
        return None
    if fields.get("Hidden", "").lower() == "true":
        return None
    return ExportedApp(
        id=file_id,
        name=fields.get("Name", file_id),
        exec=fields["Exec"],
        icon=fields.get("Icon") or None,
        comment=fields.get("Comment") or None,
        categories=[c for c in fields.get("Categories", "").split(";") if c],
        terminal=fields.get("Terminal", "").lower() == "true",
        nodisplay=fields.get("NoDisplay", "").lower() == "true",
        startup_wm_class=fields.get("StartupWMClass") or None,
    )


_DUMP = (
    "for f in "
    + " ".join(f"{d}/*.desktop" for d in APP_DIRS)
    + '; do [ -f "$f" ] || continue; printf \'\\001%s\\n\' "$f"; cat "$f"; done'
)


def list_apps(box: Box, *, include_hidden: bool = False) -> list[ExportedApp]:
    """The applications installed in a running box, as its desktop files say."""
    name = paths.box_name(box.id)
    if not podman.is_running(name):
        raise AppError(f"box {box.name!r} is not running")
    proc = podman.exec_(name, ["sh", "-c", _DUMP], timeout=60)
    if proc.returncode != 0:
        raise AppError(f"could not read the box's applications: {proc.stderr.strip()}")
    found: list[ExportedApp] = []
    for chunk in proc.stdout.split("\x01")[1:]:
        path, _, body = chunk.partition("\n")
        file_id = Path(path.strip()).stem
        app = parse_entry(body, file_id)
        if app and (include_hidden or not app.nodisplay):
            found.append(app)
    return sorted(found, key=lambda a: a.name.lower())


def find_app(box: Box, app_id: str) -> ExportedApp:
    for app in list_apps(box, include_hidden=True):
        if app.id == app_id:
            return app
    raise AppError(f"no application {app_id!r} in box {box.name!r}")


# -------------------------------------------------------------------- icons
def _find_icon_paths(box_name: str, icon: str) -> list[str]:
    """Where the box keeps the icon: hicolor sizes and pixmaps, or the path itself."""
    if icon.startswith("/"):
        return [icon]
    q = shlex.quote(icon)
    script = (
        f"find /usr/share/icons/hicolor -path '*/apps/{icon}.*' -type f 2>/dev/null; "
        f"ls /usr/share/pixmaps/{q}.png /usr/share/pixmaps/{q}.svg /usr/share/pixmaps/{q}.xpm 2>/dev/null"
    )
    proc = podman.exec_(box_name, ["sh", "-c", script], timeout=30)
    return [p for p in proc.stdout.split() if p]


def host_icon_name(box: Box, icon: str) -> str:
    stem = Path(icon).stem if icon.startswith("/") else icon
    return f"kc-{box.name}-{stem}"


def copy_icons(box: Box, icon: str | None) -> str:
    """The app's icon into the user's hicolor theme under a box-prefixed name;
    the Kiwi Custodia icon when the box has none."""
    if not icon:
        return APP_ID
    name = paths.box_name(box.id)
    sources = _find_icon_paths(name, icon)
    if not sources:
        return APP_ID
    target_name = host_icon_name(box, icon)
    copied = 0
    for src in sources:
        size = _size_of(src)
        suffix = Path(src).suffix or ".png"
        dest = paths.icons_dir() / size / "apps" / f"{target_name}{suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = podman._run(["cp", f"{name}:{src}", str(dest)], check=False, timeout=60)
        if proc.returncode == 0:
            copied += 1
    if not copied:
        return APP_ID
    refresh_icon_cache()
    return target_name


def _size_of(path: str) -> str:
    """'48x48' from /usr/share/icons/hicolor/48x48/apps/x.png; 'scalable' for an
    svg anywhere else; a pixmap png is filed as 48x48."""
    m = re.search(r"/hicolor/([^/]+)/apps/", path)
    if m:
        return m.group(1)
    return "scalable" if path.endswith(".svg") else "48x48"


def remove_icons(box: Box, icon: str | None) -> None:
    if not icon:
        return
    target_name = host_icon_name(box, icon)
    for found in paths.icons_dir().glob(f"*/apps/{target_name}.*"):
        with contextlib.suppress(OSError):
            found.unlink()


def refresh_icon_cache() -> None:
    if tool := shutil.which("gtk-update-icon-cache"):
        import subprocess

        subprocess.run(  # noqa: S603
            [tool, "-qtf", str(paths.icons_dir())], check=False, capture_output=True, timeout=30
        )


# ------------------------------------------------------------------ entries
def entry_path(box: Box, app_id: str) -> Path:
    return paths.applications_dir() / f"{ENTRY_PREFIX}{box.name}-{app_id}.desktop"


def launcher() -> str:
    return shutil.which("kiwi-custodia") or "kiwi-custodia"


def _exec_arg(value: str) -> str:
    if re.search(r"""[\s"'\\><~|&;$*?#()`]""", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def render_entry(box: Box, app: ExportedApp, icon: str) -> str:
    cmd = _exec_arg(launcher())
    exec_line = _FIELD_CODES.sub("", app.exec).strip()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={app.name} ({box.name})",
        f"Comment={app.comment + ' — ' if app.comment else ''}in the {box.name} box, "
        "through its exit",
        f"Exec={cmd} run {box.id} -- {exec_line}",
        f"Icon={icon}",
        f"Terminal={'true' if app.terminal else 'false'}",
        f"Categories={';'.join(app.categories) + ';' if app.categories else 'Utility;'}",
        f"Keywords=kiwi;custodia;{box.name};",
        "StartupNotify=false",
        # The window announces the app's own id (its desktop file's name on
        # Wayland, or what the original entry says), so the shell links it here.
        f"StartupWMClass={app.startup_wm_class or app.id}",
        f"X-KiwiCustodia-Box={box.id}",
        f"X-KiwiCustodia-App={app.id}",
        "",
    ]
    return "\n".join(lines)


def export(box: Box, app_id: str) -> Path:
    app = find_app(box, app_id)
    icon = copy_icons(box, app.icon)
    path = entry_path(box, app.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render_entry(box, app, icon))
    tmp.replace(path)
    if app.id not in box.exported:
        box.exported.append(app.id)
        store.save(box)
    refresh_desktop_database()
    return path


def unexport(box: Box, app_id: str) -> None:
    path = entry_path(box, app_id)
    icon = None
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("Icon=") and line[5:].startswith(f"kc-{box.name}-"):
                icon = line[5:].removeprefix(f"kc-{box.name}-")
        with contextlib.suppress(OSError):
            path.unlink()
    remove_icons(box, icon)
    if app_id in box.exported:
        box.exported.remove(app_id)
        store.save(box)
    refresh_desktop_database()


def unexport_all(box: Box) -> None:
    for app_id in list(box.exported):
        unexport(box, app_id)
    for stale in paths.applications_dir().glob(f"{ENTRY_PREFIX}{box.name}-*.desktop"):
        with contextlib.suppress(OSError):
            stale.unlink()


def refresh_desktop_database() -> None:
    if tool := shutil.which("update-desktop-database"):
        import subprocess

        subprocess.run(  # noqa: S603
            [tool, "-q", str(paths.applications_dir())],
            check=False,
            capture_output=True,
            timeout=30,
        )
