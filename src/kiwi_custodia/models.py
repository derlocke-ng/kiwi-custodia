"""Data model: what a box is. Nothing that runs, nothing secret."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box(Strict):
    """One distribution with a home of its own, exiting through one kiwi-proxy
    exit. ``exit`` is the exit's id (kiwi-proxy's store has the rest); the box has
    no route but that exit, which is the whole point, so it is not optional.

    ``image`` is pinned at creation from the distro's default so a box keeps the
    base it was made from; ``packages`` is what the first-run init added on top
    of the distro's baseline, replayed if the container is ever rebuilt."""

    id: str
    name: str
    created: dt.datetime
    distro: str  # key into distros.DISTROS
    image: str
    exit: str  # kiwi-proxy exit id
    hostname: str | None = None  # the box's hostname; its name when None
    packages: list[str] = Field(default_factory=list)  # extra packages the init installs
    gpu: bool = True  # pass /dev/dri in, for hardware rendering
    desktop_entry: bool = False  # a terminal entry for the box in the app grid
    exported: list[str] = Field(default_factory=list)  # desktop file ids exported to the host
    notes: str = ""

    @property
    def host(self) -> str:
        return self.hostname or self.name


class ExportedApp(Strict):
    """A desktop file read out of a box, enough to show it and export it."""

    id: str  # the desktop file's basename without .desktop
    name: str
    exec: str
    icon: str | None = None
    comment: str | None = None
    categories: list[str] = Field(default_factory=list)
    terminal: bool = False
    nodisplay: bool = False
    startup_wm_class: str | None = None


BoxState = Literal["running", "stopped", "gateway-down"]
