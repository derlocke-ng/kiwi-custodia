"""The box store: one directory per box with its record and its home."""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import uuid
from pathlib import Path

from kiwi_proxy import exits
from kiwi_proxy.models import Exit

from . import distros, paths
from .models import Box

RECORD = "box.json"
# A box name is also its hostname and part of desktop file names, so keep it to
# what every one of those accepts.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class StoreError(RuntimeError):
    pass


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def _write_json(path: Path, payload: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def create(
    name: str,
    *,
    distro: str,
    exit_id: str,
    hostname: str | None = None,
    packages: list[str] | None = None,
    gpu: bool = True,
    image: str | None = None,
    shell: str | None = None,
) -> Box:
    if not valid_name(name):
        raise StoreError(
            f"{name!r} is not a usable box name: lower-case letters, digits and dashes, "
            "starting with a letter or digit"
        )
    if find_by_name(name):
        raise StoreError(f"a box named {name!r} exists")
    try:
        d = distros.get(distro)
    except KeyError as exc:
        raise StoreError(str(exc)) from exc
    if not exits.exists(exit_id):
        raise StoreError(f"no kiwi-proxy exit with id {exit_id!r}")
    if not (image or d.image):
        raise StoreError(f"distro {d.key!r} needs an image: --image registry/name:tag")
    box = Box(
        id=str(uuid.uuid4()),
        name=name,
        created=dt.datetime.now(dt.UTC),
        distro=d.key,
        image=image or d.image,
        exit=exit_id,
        hostname=hostname,
        packages=list(packages or []),
        gpu=gpu,
        shell=shell or None,
    )
    paths.box_home(box.id).mkdir(parents=True, exist_ok=True)
    save(box)
    return box


def save(box: Box) -> None:
    d = paths.box_dir(box.id)
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / RECORD, box.model_dump_json(indent=2))


def load(box_id: str) -> Box:
    path = paths.box_dir(box_id) / RECORD
    if not path.exists():
        raise StoreError(f"no box with id {box_id!r}")
    return Box.model_validate_json(path.read_text())


def exists(box_id: str) -> bool:
    return (paths.box_dir(box_id) / RECORD).exists()


def list_boxes() -> list[Box]:
    root = paths.boxes_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / RECORD).exists():
            try:
                out.append(load(d.name))
            except Exception:  # noqa: BLE001 - a broken box must not hide the others
                continue
    return sorted(out, key=lambda b: b.name)


def find_by_name(name: str) -> Box | None:
    return next((b for b in list_boxes() if b.name == name), None)


def resolve_ref(ref: str) -> Box:
    """A name or an id prefix, the way git accepts a short sha."""
    if found := find_by_name(ref):
        return found
    matches = [b for b in list_boxes() if b.id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise StoreError(f"no box matches {ref!r}")
    raise StoreError(f"{ref!r} is ambiguous: {[b.name for b in matches]}")


def delete(box_id: str) -> None:
    """The record and the home. The exit is kiwi-proxy's and stays."""
    shutil.rmtree(paths.box_dir(box_id), ignore_errors=True)


def rename(box: Box, name: str) -> Box:
    if not valid_name(name):
        raise StoreError(f"{name!r} is not a usable box name")
    other = find_by_name(name)
    if other and other.id != box.id:
        raise StoreError(f"a box named {name!r} exists")
    box.name = name
    save(box)
    return box


def exit_of(box: Box) -> Exit:
    """The kiwi-proxy exit the box leaves through."""
    try:
        return exits.load(box.exit)
    except exits.ExitError as exc:
        raise StoreError(
            f"box {box.name!r} exits through {box.exit[:8]}, which kiwi-proxy no longer has "
            "(`kiwi-custodia set NAME --exit OTHER` moves it)"
        ) from exc


def boxes_on(exit_id: str) -> list[Box]:
    return [b for b in list_boxes() if b.exit == exit_id]
