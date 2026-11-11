"""Kiwi Custodia's own preferences (the General page): what a new box starts
with, and whether leftovers are repaired when the app starts.

Kept in ``~/.config/kiwi-custodia/settings.json``; a missing or broken file means
the defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import distros, paths


@dataclass
class Settings:
    # Before anything starts: remove this app's containers an unclean shutdown
    # left (a box's committed first).
    repair_on_start: bool = True
    # What the New box dialog starts with: a distribution, and an exit id or ""
    # to leave the choice to the dialog.
    new_distro: str = distros.DEFAULT
    new_exit: str = ""


def path():
    return paths.config_dir() / "settings.json"


def load() -> Settings:
    try:
        data = json.loads(path().read_text())
        s = Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return Settings()
    if s.new_distro not in distros.DISTROS:
        s.new_distro = distros.DEFAULT
    return s


def save(s: Settings) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2) + "\n")
    tmp.replace(p)
