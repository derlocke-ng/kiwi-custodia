"""The distributions a box can be, and what each is built from.

``family`` is the package manager the box's first-run init drives
(containers/box/kc-init.sh knows each family's baseline: sudo, a locale, Mesa for
GPU rendering, a font, xdg-utils — what a desktop app needs to start). A box pins
the image it was made from, so changing a default here changes new boxes only.
"""

from __future__ import annotations

from dataclasses import dataclass

Family = str  # dnf | apt | pacman | zypper | apk


@dataclass(frozen=True)
class Distro:
    key: str
    title: str
    image: str
    family: Family
    notes: str = ""


DISTROS: dict[str, Distro] = {
    d.key: d
    for d in (
        Distro("fedora", "Fedora", "registry.fedoraproject.org/fedora:latest", "dnf"),
        Distro("ubuntu", "Ubuntu 24.04 LTS", "docker.io/library/ubuntu:24.04", "apt"),
        Distro("debian", "Debian stable", "docker.io/library/debian:stable", "apt"),
        Distro("arch", "Arch Linux", "docker.io/library/archlinux:latest", "pacman"),
        Distro(
            "opensuse",
            "openSUSE Tumbleweed",
            "registry.opensuse.org/opensuse/tumbleweed:latest",
            "zypper",
        ),
        Distro(
            "alpine",
            "Alpine Linux",
            "docker.io/library/alpine:latest",
            "apk",
            "musl, not glibc: many proprietary desktop apps will not run here",
        ),
    )
}

DEFAULT = "fedora"


def get(key: str) -> Distro:
    try:
        return DISTROS[key]
    except KeyError:
        raise KeyError(f"unknown distro {key!r}; one of: {', '.join(DISTROS)}") from None


def titles() -> list[tuple[str, str]]:
    return [(d.key, d.title) for d in DISTROS.values()]
