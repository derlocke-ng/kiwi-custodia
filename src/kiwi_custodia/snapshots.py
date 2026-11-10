"""Kiwi Custodia boxes in the snapshot folder that kiwi-proxy keeps.

A box's snapshot holds its record (``box.json``), its home without ``.cache``, and
what was added to its system (``recipe``): the packages, the repositories and
keys, the system files, all read from the box's committed image. Not the image
itself (1.9 GB for fedora1): on another device the box is rebuilt from its base
image at its first start, through its own exit.

When: after a box ran and stopped (``boxes.stop`` calls :func:`after_stop`), and
when asked. A running box is committed first, so a snapshot always reads a
consistent image; its home is copied as it is.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import kiwi_proxy

from . import __version__, boxes, paths, recipe, store
from .models import Box

NEEDS_PROXY = (0, 8, 1)


def _version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split(".")[:3])
    except ValueError:
        return (0,)


try:
    from kiwi_proxy import snapshots as snap
except ImportError:  # pragma: no cover - an older kiwi-proxy
    snap = None  # type: ignore[assignment]
if _version(getattr(kiwi_proxy, "__version__", "0")) < NEEDS_PROXY:
    snap = None  # type: ignore[assignment]

KIND = "box"
NEEDS = "snapshots need kiwi-proxy 0.8.1 or later (kiwi update kiwi-proxy)"
HOME_SKIP = (".cache",)


class RestoreError(store.StoreError):
    pass


def available() -> bool:
    return snap is not None


def _require() -> None:
    if snap is None:
        raise store.StoreError(NEEDS)


def _settings():
    return snap.load_settings() if snap is not None else None


# --------------------------------------------------------------------- take
def _home_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    relative = info.name.removeprefix("home").lstrip("/")
    if relative and relative.split("/")[0] in HOME_SKIP:
        return None
    if not (info.isfile() or info.isdir() or info.issym()):
        return None
    return info


def _fill(box: Box, rec: recipe.Recording | None, files_tar: Path | None):
    def fill(tar: tarfile.TarFile) -> None:
        snap.add_bytes(tar, "box.json", box.model_dump_json(indent=2).encode())
        home = paths.box_home(box.id)
        if home.is_dir():
            tar.add(home, arcname="home", filter=_home_filter)
        if rec is not None:
            snap.add_bytes(tar, "system/recipe.json", rec.to_json().encode())
            if files_tar is not None and files_tar.exists():
                tar.add(files_tar, arcname="system/files.tar")

    return fill


def home_size(box: Box) -> int:
    """The bytes of the box's home a snapshot takes (no caches)."""
    total = 0
    home = paths.box_home(box.id)
    for root, dirs, files in os.walk(home):
        if Path(root) == home:
            dirs[:] = [d for d in dirs if d not in HOME_SKIP]
        for name in files:
            with contextlib.suppress(OSError):
                st = os.lstat(os.path.join(root, name))
                total += st.st_size
    return total


def _extra(box: Box, rec: recipe.Recording | None, files_size: int) -> dict:
    ex_name = None
    with contextlib.suppress(Exception):
        ex_name = store.exit_of(box).name
    extra = {
        "distro": box.distro,
        "image": box.image,
        "exit": box.exit,
        "exit_name": ex_name,
        "home_size": home_size(box),
        "setup_script": bool(box.setup_script.strip()),
    }
    if rec is not None:
        extra |= {
            "family": rec.family,
            "packages": rec.packages,
            "local": rec.local,
            "files": len(rec.files),
            "files_size": files_size,
            "files_summary": recipe.summary(rec.files, rec.family),
            "notes": rec.notes,
        }
    return extra


@dataclass
class Travels:
    """What the box's newest snapshot carries, for its editor."""

    state: str  # off | locked | none | taken
    when: str = ""
    packages: list[str] = field(default_factory=list)
    local: list[str] = field(default_factory=list)
    files: int = 0
    files_size: int = 0
    files_summary: str = ""
    home_size: int = 0
    image_size: int = 0
    recorded: bool = False  # the system was recorded (False: only the home travels)
    notes: list[str] = field(default_factory=list)


def travels(box: Box) -> Travels:
    """From the box's newest snapshot in the folder; the home's and the image's
    size from this device."""
    out = Travels(state="off")
    with contextlib.suppress(OSError):
        out.home_size = home_size(box)
    if boxes.has_snapshot(box):
        with contextlib.suppress(Exception):
            out.image_size = boxes.image_size(box)
    if snap is None or _settings() is None:
        return out
    if not snap.unlocked():
        out.state = "locked"
        return out
    metas = [m for m in snap.history(KIND, box.id) if not m.aside]
    if not metas:
        out.state = "none"
        return out
    head = metas[0]
    extra = head.extra
    out.state = "taken"
    out.when = snap.when_text(head.created)
    out.recorded = "packages" in extra
    out.packages = list(extra.get("packages", [])) + list(extra.get("local", []))
    out.local = list(extra.get("local", []))
    out.files = int(extra.get("files", 0))
    out.files_size = int(extra.get("files_size", 0))
    out.files_summary = str(extra.get("files_summary", ""))
    out.notes = list(extra.get("notes", []))
    return out


def take(box: Box, *, aside: bool = False, supersede=None):
    """Snapshot a box now. A running one is committed to its image first."""
    _require()
    if boxes.running(box):
        boxes.snapshot(box)
    rec = None
    files_tar = None
    files_size = 0
    work = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=paths.box_dir(box.id)))
    try:
        if boxes.has_snapshot(box):
            rec = recipe.record(box, paths.box_image(box.id))
            files_tar = work / "files.tar"
            files_size = recipe.write_files(rec, files_tar)
        elif (paths.box_rebuild_dir(box.id) / "recipe.json").is_file():
            # restored here and not yet rebuilt and stopped: what it came with
            rebuild = paths.box_rebuild_dir(box.id)
            rec = recipe.Recording.from_json((rebuild / "recipe.json").read_text())
            files_tar = rebuild / "files.tar"
            files_size = files_tar.stat().st_size if files_tar.exists() else 0
        return snap.take(
            KIND,
            box.id,
            box.name,
            _fill(box, rec, files_tar),
            extra=_extra(box, rec, files_size),
            aside=aside,
            supersede=supersede,
            app="kiwi-custodia",
            version=__version__,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def after_stop(box: Box) -> str | None:
    """The box stopped: say so in the folder, and snapshot it when it ran (or
    changed) since its last snapshot. A line to show when that did not work;
    never raises."""
    s = _settings()
    if s is None:
        return None
    with contextlib.suppress(snap.SnapshotError, OSError):
        snap.clear_in_use(KIND, box.id)
    if not s.automatic or boxes.running(box):
        return None
    try:
        rel = snap.relation(KIND, box.id, here=True)
        if rel.state in ("same", "folder_newer"):
            return None
        take(box)
    except snap.Locked:
        return f"{box.name}: no snapshot taken, snapshots are locked on this device"
    except (snap.SnapshotError, recipe.RecipeError, OSError) as exc:
        return f"{box.name}: no snapshot taken: {exc}"
    return None


def started(box: Box) -> None:
    """The box is up: its copy changes from now on, and the folder may say where
    it is in use. Best effort."""
    if _settings() is None:
        return
    snap.mark_changed(KIND, box.id)
    with contextlib.suppress(snap.SnapshotError, OSError):
        snap.mark_in_use(KIND, box.id)


def changed(box: Box) -> None:
    """The box's record changed (a package declared, the setup script): the next
    stop takes it."""
    if _settings() is not None:
        snap.mark_changed(KIND, box.id)


@dataclass
class StartCheck:
    relation: object | None = None
    in_use: list | None = None

    @property
    def newer_elsewhere(self) -> bool:
        return bool(self.relation and self.relation.newer_elsewhere)

    @property
    def needs_asking(self) -> bool:
        return self.newer_elsewhere or bool(self.in_use)


def before_start(box: Box) -> StartCheck:
    s = _settings()
    if s is None:
        return StartCheck(None, [])
    try:
        rel = snap.relation(KIND, box.id, here=True)
        in_use = snap.in_use_elsewhere(KIND, box.id)
    except (snap.SnapshotError, OSError):
        return StartCheck(None, [])
    return StartCheck(rel if s.ask_older else None, in_use)


def keep_mine(box: Box, check: StartCheck):
    return take(box, supersede=getattr(check.relation, "heads", None))


# ------------------------------------------------------------------- restore
def missing_exit(meta) -> str | None:
    from kiwi_proxy import exits

    exit_id = meta.extra.get("exit")
    if exit_id and not exits.exists(exit_id):
        return meta.extra.get("exit_name") or exit_id[:8]
    return None


def _write_rebuild(box: Box, system: Path, sid: str) -> None:
    """What kc-init reads at the box's first start, from the snapshot's recipe."""
    target = paths.box_rebuild_dir(box.id)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    rec_file = system / "recipe.json"
    if rec_file.is_file():
        rec = recipe.Recording.from_json(rec_file.read_text())
        shutil.copy(rec_file, target / "recipe.json")
        (target / "packages.txt").write_text(
            "\n".join(rec.packages) + ("\n" if rec.packages else "")
        )
        (target / "requires.txt").write_text(
            "\n".join(rec.requires) + ("\n" if rec.requires else "")
        )
        (target / "repo-files.txt").write_text(
            "\n".join(rec.repo_files) + ("\n" if rec.repo_files else "")
        )
        if (system / "files.tar").is_file():
            os.rename(system / "files.tar", target / "files.tar")
    if box.exported:
        (target / "reexport").write_text("\n".join(box.exported) + "\n")
    (target / "id").write_text(sid + "\n")


def restore(box_id: str, sid: str) -> Box:
    """Put snapshot `sid` of a box in place: its record and home now, its system
    at its next start (rebuilt from its base image). Refused while it runs, and
    when its exit is not on this device (Kiwi Proxy restores exits). This
    device's copy, when it changed since its last snapshot, is kept as a
    snapshot first."""
    _require()
    metas = snap.history(KIND, box_id)
    meta = next((m for m in metas if m.id == sid or m.id.startswith(sid)), None)
    if meta is None:
        raise RestoreError(f"no snapshot {sid} of this box in the folder")
    if name := missing_exit(meta):
        raise RestoreError(
            f"{meta.name} goes out through the exit {name}, which is not on this device: "
            f"restore {name} in Kiwi Proxy first"
        )
    here = store.exists(box_id)
    if here:
        current = store.load(box_id)
        if boxes.running(current):
            raise RestoreError(f"{current.name} is running; stop it first")

    def apply(staging: Path, _meta) -> None:
        restored = Box.model_validate_json((staging / "box.json").read_text())
        if restored.id != box_id:
            raise RestoreError("the snapshot holds a different box than it says")
        clash = store.find_by_name(restored.name)
        if clash and clash.id != box_id:
            raise RestoreError(
                f"a box named {restored.name} already exists here; rename one of them first"
            )
        directory = paths.box_dir(box_id)
        directory.mkdir(parents=True, exist_ok=True)
        home = paths.box_home(box_id)
        incoming = staging / "home"
        incoming.mkdir(exist_ok=True)
        old = home.with_name(f".home.old-{os.urandom(4).hex()}")
        if home.exists():
            os.rename(home, old)
        try:
            os.rename(incoming, home)
        except OSError:
            if old.exists():
                os.rename(old, home)
            raise
        shutil.rmtree(old, ignore_errors=True)
        # the system comes back at the next start, from the base image: an image
        # or container of this box left here (this device's older copy, or one a
        # crash left behind) would start instead of the rebuild
        with contextlib.suppress(Exception):
            from kiwi_proxy import podman

            podman.rm(paths.box_name(box_id))
        boxes.forget_snapshot(restored)
        _write_rebuild(restored, staging / "system", meta.id)
        store.save(restored)

    keep = (lambda: take(store.load(box_id), aside=True)) if here else None
    snap.restore(
        KIND, box_id, meta.id, apply, here=here, keep_current=keep, staging_root=paths.data_dir()
    )
    box = store.load(box_id)
    with contextlib.suppress(Exception):
        from . import desktop
        from .cli import describe

        desktop.sync_entry(box, describe(box))
    return box


def rebuilt(box: Box) -> None:
    """The box came up after a restore: its exported apps go back into the app
    grid. The rebuild folder stays until the box's own snapshot image holds the
    result (the next stop)."""
    rebuild = paths.box_rebuild_dir(box.id)
    marker = rebuild / "reexport"
    if not marker.is_file():
        return
    from . import apps

    for app_id in marker.read_text().split():
        with contextlib.suppress(Exception):
            apps.export(box, app_id)
    marker.unlink(missing_ok=True)


def settled(box: Box) -> None:
    """After a stop that committed the box: the rebuild material is no longer
    needed; its own image holds the result now."""
    if boxes.has_snapshot(box):
        shutil.rmtree(paths.box_rebuild_dir(box.id), ignore_errors=True)


# ------------------------------------------------------------------- listing
def away() -> list[tuple[str, str, list]]:
    """Boxes in the folder that are not on this device: (id, name, snapshots)."""
    if _settings() is None:
        return []
    here = {b.id for b in store.list_boxes()}
    out = []
    for (kind, item), metas in snap.catalog((KIND,)).items():
        if kind == KIND and item not in here:
            out.append((item, metas[0].name, metas))
    return sorted(out, key=lambda a: a[1])


def find_in_folder(ref: str) -> tuple[str, str]:
    _require()
    metas = [m for m in snap.folder().metas() if m.kind == KIND]
    named = [m for m in metas if m.name == ref] or [m for m in metas if m.item.startswith(ref)]
    items = {m.item for m in named}
    if not items:
        raise RestoreError(f"no box {ref!r} in the snapshot folder")
    if len(items) > 1:
        raise RestoreError(f"{ref!r} names {len(items)} different boxes in the folder; use its id")
    return named[0].item, named[0].name


def take_all() -> str:
    taken = size = 0
    for box in store.list_boxes():
        size += take(box).size
        taken += 1
    if not taken:
        return "nothing to snapshot yet"
    return f"{taken} box{'es' if taken != 1 else ''} · {snap.size_text(size)}"
