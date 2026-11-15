"""A box's Kiwi Custodia icon in a colour of its own, from the kiwi-icons kit
(kiwi_icon.py, copied unchanged from github.com/derlocke-ng/kiwi-icons, kit/),
so boxes can be told apart in the app grid, the dash and the list. The kit has no
Custodia glyph; the cube from Custodia's own icon is registered with it here."""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from . import APP_ID, kiwi_icon, paths
from .models import Box

kiwi_icon.GLYPHS.setdefault(
    "custodia",
    {"s": "M64 52.5l10.5 5.5v12L64 75.5l-10.5-5.5V58ZM53.5 58L64 63.5L74.5 58M64 63.5v12", "f": ""},
)
COLORS = list(kiwi_icon.COLORWAYS)
# The order new ones get them in: far apart on the colour wheel first, so the
# first few already look different side by side (the kit's own order runs
# through the warm hues first).
SPREAD = [
    c
    for c in (
        "ember",
        "ocean",
        "forest",
        "violet",
        "honey",
        "teal",
        "crimson",
        "indigo",
        "kiwi",
        "orchid",
        "rose",
        "graphite",
    )
    if c in kiwi_icon.COLORWAYS
] + [
    c
    for c in kiwi_icon.COLORWAYS
    if c
    not in {
        "ember",
        "ocean",
        "forest",
        "violet",
        "honey",
        "teal",
        "crimson",
        "indigo",
        "kiwi",
        "orchid",
        "rose",
        "graphite",
    }
]


def color_label(key: str) -> str:
    return (
        kiwi_icon.COLORWAYS[key]["label"] if key in kiwi_icon.COLORWAYS else "Kiwi Custodia's own"
    )


def next_color(used: Iterable[str]) -> str:
    """The first colourway no box has yet; once every one is taken, the least used."""
    count = Counter(c for c in used if c)
    return min(SPREAD, key=lambda c: (count[c], SPREAD.index(c)))


def colored_icon(box: Box) -> Path | None:
    """The box's coloured Custodia kiwi as a file, rendered once per colour; None
    for Kiwi Custodia's own."""
    if box.color not in kiwi_icon.COLORWAYS:
        return None
    folder = paths.data_dir() / "icons"
    f = folder / f"{box.id}-{box.color}.svg"
    if not f.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(f"{box.id}-*.svg"):
                old.unlink()
            f.write_text(kiwi_icon.render("custodia", colorway=box.color, title=box.name))
        except OSError:
            return None
    return f


def custom_dir() -> Path:
    """Your own icons: PNG or SVG files put here are offered for every box."""
    return paths.config_dir() / "icons"


def choices() -> list[tuple[str, str]]:
    """(key, title): the Custodia kiwi in the box's colour, then your own files."""
    out = [("", "Kiwi Custodia, in its colour")]
    folder = custom_dir()
    if folder.is_dir():
        out += [
            (f"custom:{f.name}", f.stem)
            for f in sorted(folder.iterdir())
            if f.is_file() and f.suffix.lower() in (".svg", ".png")
        ]
    return out


def _custom(box: Box) -> Path | None:
    """The box's own icon, copied beside the app's data so the entry keeps it when
    the file in the folder goes."""
    if not box.icon.startswith("custom:"):
        return None
    source = custom_dir() / box.icon.removeprefix("custom:")
    kept = paths.data_dir() / "icons" / f"{box.id}-own{source.suffix.lower() or '.png'}"
    try:
        if source.is_file():
            kept.parent.mkdir(parents=True, exist_ok=True)
            if not kept.exists() or kept.read_bytes() != source.read_bytes():
                shutil.copyfile(source, kept)
    except OSError:
        pass
    return kept if kept.exists() else None


def icon_for(box: Box) -> str:
    """The one icon a box has everywhere, the list and the app grid alike: your
    own file, else the Custodia kiwi in its colour, else the app's icon name."""
    if own := _custom(box):
        return str(own)
    colored = colored_icon(box)
    return str(colored) if colored else APP_ID
