"""A box's Kiwi Custodia icon in a colour of its own, from the kiwi-icons kit
(kiwi_icon.py, copied unchanged from github.com/derlocke-ng/kiwi-icons, kit/),
so boxes can be told apart in the app grid, the dash and the list. The kit has no
Custodia glyph; the cube from Custodia's own icon is registered with it here."""

from __future__ import annotations

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


def icon_for(box: Box) -> str:
    """What an entry's Icon= says: the coloured file, or the app's own icon name."""
    colored = colored_icon(box)
    return str(colored) if colored else APP_ID
