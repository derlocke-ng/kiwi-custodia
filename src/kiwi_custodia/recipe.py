"""What a box carries to another device besides its home.

A box's system is its base image plus the baseline kc-init installs plus what
you did to it. Only the last part has to travel: the packages you installed, the
repositories and keys you added for them, the system files you added or edited.
All of it is read from the box's committed image (``localhost/kiwi-custodia/
box-…``) by ``kc-record`` in throwaway containers with no network — the box itself
is stopped and consistent, and never touched.

- **Packages:** the package manager's own list of explicitly installed packages,
  minus what the base image already had, minus the baseline, minus the packages
  the box declares (those are in its record and installed anyway). A package
  installed from a file is no repository's to install again: it travels as its
  files, with what it requires.
- **Files:** what changed between the base image and the box's image under /etc,
  /opt, /usr/local, /srv, /root and the apt keyrings, minus files a package owns
  unchanged (the package brings them back), minus what is this machine's or
  kiwi-custodia's own (users, hostname, resolver, sudoers entry, generated
  caches).

On the other device kc-init rebuilds the box from these at its first start:
repositories and keys, packages, files, the setup script.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kiwi_proxy import podman

from . import distros
from .models import Box

KEEP_PREFIXES = ("/etc/", "/opt/", "/usr/local/", "/srv/", "/root/", "/usr/share/keyrings/")
# This machine's, or kiwi-custodia's own: never carried.
SKIP = {
    "/etc/passwd",
    "/etc/passwd-",
    "/etc/group",
    "/etc/group-",
    "/etc/shadow",
    "/etc/shadow-",
    "/etc/gshadow",
    "/etc/gshadow-",
    "/etc/subuid",
    "/etc/subuid-",
    "/etc/subgid",
    "/etc/subgid-",
    "/etc/sudoers",
    "/etc/hostname",
    "/etc/hosts",
    "/etc/resolv.conf",
    "/etc/machine-id",
    "/etc/mtab",
    "/etc/.pwd.lock",
    "/etc/ld.so.cache",
    "/etc/localtime",
    "/etc/kiwi-custodia-box",
    "/etc/sudoers.d/kiwi-custodia",
    "/etc/profile.d/kiwi-custodia.sh",
    "/usr/local/bin/kc-shell",
    # the empty file podman leaves for kc-init's bind mount
    "/usr/local/bin/kc-init",
}
SKIP_PREFIXES = (
    "/etc/pki/ca-trust/extracted/",
    "/etc/ssl/certs/",
    "/etc/alternatives/",
    "/etc/selinux/",
    "/root/.cache/",
    "/var/lib/kiwi-custodia/",
)
# Repositories and their keys: put back before the packages are installed.
REPO_PATTERNS = {
    "dnf": ("etc/yum.repos.d/*", "etc/pki/rpm-gpg/*", "etc/dnf/vars/*"),
    "zypper": ("etc/zypp/repos.d/*", "etc/pki/rpm-gpg/*"),
    "apt": (
        "etc/apt/sources.list",
        "etc/apt/sources.list.d/*",
        "etc/apt/keyrings/*",
        "etc/apt/trusted.gpg",
        "etc/apt/trusted.gpg.d/*",
        "usr/share/keyrings/*",
        "etc/apt/preferences",
        "etc/apt/preferences.d/*",
    ),
    "pacman": ("etc/pacman.conf", "etc/pacman.d/*"),
    "apk": ("etc/apk/repositories", "etc/apk/keys/*"),
}
FAMILIES = tuple(REPO_PATTERNS)


class RecipeError(RuntimeError):
    pass


@dataclass
class Recording:
    """What the box's image says was added to it."""

    family: str
    packages: list[str] = field(default_factory=list)  # from repositories
    local: list[str] = field(default_factory=list)  # from files: they travel as files
    requires: list[str] = field(default_factory=list)  # what the local ones need
    files: list[str] = field(default_factory=list)  # absolute paths to carry
    repo_files: list[str] = field(default_factory=list)  # relative, put back first
    image: str = ""
    base_image: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Recording:
        data = json.loads(text)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _script(name: str) -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "containers", here.parents[1] / "containers"):
        path = candidate / "box" / name
        if path.exists():
            return path
    raise RecipeError(f"cannot find containers/box/{name} next to the package")


def record_script() -> Path:
    return _script("kc-record.sh")


def _in_image(
    image: str,
    family: str,
    args: list[str],
    *,
    stdin: str | bytes | None = None,
    timeout: int = 600,
    binary: bool = False,
) -> subprocess.CompletedProcess:
    """kc-record (or a shell command) in a throwaway container of `image`, with no
    network and nothing kept."""
    cmd = [
        "podman",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--security-opt",
        "label=disable",
        "--env",
        f"KC_FAMILY={family}",
        "--volume",
        f"{record_script()}:/run/kc-record:ro",
        "--entrypoint",
        "/bin/sh",
        image,
        *args,
    ]
    proc = subprocess.run(  # noqa: S603
        cmd,
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip().splitlines()
        raise RecipeError(f"reading {image} failed: {err[-1] if err else proc.returncode}")
    if not binary:
        proc.stdout = proc.stdout.decode(errors="replace")
    return proc


def baseline(family: str) -> set[str]:
    """kc-init's baseline for a family, from kc-init itself (one list, one place)."""
    from .boxes import init_script

    proc = subprocess.run(  # noqa: S603
        ["sh", str(init_script()), "baseline"],
        env={"KC_FAMILY": family, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    return set(proc.stdout.split()) if proc.returncode == 0 else set()


def _packages(image: str, family: str) -> dict[str, str]:
    out = _in_image(image, family, ["/run/kc-record", "packages"]).stdout
    found: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if parts:
            found[parts[0]] = parts[1] if len(parts) > 1 else "-"
    return found


def candidates(diff: dict) -> list[str]:
    """Of an image diff, the paths a snapshot may need to carry."""
    out = []
    for path in sorted(set(diff.get("added", []) or []) | set(diff.get("changed", []) or [])):
        if not path.startswith(KEEP_PREFIXES) or path in SKIP:
            continue
        if path.startswith(SKIP_PREFIXES):
            continue
        out.append(path)
    return out


def repo_files(family: str, files: list[str]) -> list[str]:
    patterns = REPO_PATTERNS.get(family, ())
    rel = [f.lstrip("/") for f in files]
    return [f for f in rel if any(fnmatch.fnmatch(f, p) for p in patterns)]


def family_of(box: Box, image: str) -> str:
    family = distros.get(box.distro).family
    if family in FAMILIES:
        return family
    return _in_image(image, "auto", ["/run/kc-record", "family"]).stdout.strip() or "auto"


def record(box: Box, image: str) -> Recording:
    """Read from `image` (the box's committed image) what was added to the box
    over its base image."""
    family = family_of(box, image)
    rec = Recording(family=family, image=image, base_image=box.image)
    if family not in FAMILIES:
        rec.notes.append(f"no package manager kiwi-custodia knows in {image}")
        return rec
    now = _packages(image, family)
    base: dict[str, str] = {}
    have_base = podman.image_exists(box.image)
    if have_base:
        base = _packages(box.image, family)
    else:
        rec.notes.append(f"the base image {box.image} is not here: everything installed counts")
    skip = set(base) | baseline(family) | set(box.packages)
    for name, source in sorted(now.items()):
        if name in skip:
            continue
        (rec.local if source == "@local" else rec.packages).append(name)

    files: list[str] = []
    if have_base:
        proc = podman._run(["diff", "--format", "json", image, box.image], check=False, timeout=600)
        if proc.returncode == 0 and proc.stdout.strip():
            cands = candidates(json.loads(proc.stdout))
            if cands:
                out = _in_image(
                    image, family, ["/run/kc-record", "files"], stdin="\n".join(cands) + "\n"
                ).stdout
                files = [ln[5:] for ln in out.splitlines() if ln.startswith("keep ")]
        else:
            rec.notes.append("could not compare the box with its base image; no system files")
    if rec.local:
        out = _in_image(image, family, ["/run/kc-record", "local", *rec.local]).stdout
        for line in out.splitlines():
            kind, _, value = line.partition(" ")
            if kind == "file" and value:
                files.append(value)
            elif kind == "req" and value:
                rec.requires.append(value)
    rec.requires = sorted(set(rec.requires))
    rec.files = sorted(set(files))
    rec.repo_files = repo_files(family, rec.files)
    return rec


KEY_PARTS = ("/rpm-gpg/", "/keyrings/", "/trusted.gpg", "/apk/keys/")


def summary(files: list[str], family: str, *, most: int = 3) -> str:
    """A line for people: the repositories by name, the keys counted, the rest
    by their top folder ("/opt/tool"), "and N more"."""
    keys = [f for f in files if any(part in f for part in KEY_PARTS)]
    repos = [f for f in repo_files(family, files) if "/" + f not in keys]
    shown: list[str] = ["/" + r for r in repos if not r.startswith("etc/dnf/vars/")]
    rest: list[str] = []
    for f in files:
        if f in keys or f.lstrip("/") in repos:
            continue
        parts = f.strip("/").split("/")
        if parts[0] in ("opt", "srv") and len(parts) > 2:
            f = "/" + "/".join(parts[:2])
        elif parts[:2] == ["usr", "local"] and len(parts) > 4:
            f = "/" + "/".join(parts[:4])
        if f not in rest:
            rest.append(f)
    bits = shown[:most]
    if keys:
        bits.append(f"{len(keys)} signing key" + ("s" if len(keys) != 1 else ""))
    room = max(most - len(shown), 1)
    bits += rest[:room]
    more = max(len(shown) - most, 0) + max(len(rest) - room, 0)
    return ", ".join(bits) + (f" and {more} more" if more else "")


def write_files(rec: Recording, dest: Path) -> int:
    """The recorded files, as a tar read out of the image, into `dest`. Its size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not rec.files:
        import tarfile

        with tarfile.open(dest, "w"):
            pass
        return dest.stat().st_size
    names = "\n".join(f.lstrip("/") for f in rec.files) + "\n"
    proc = _in_image(
        rec.image,
        rec.family,
        # no directories in the list (kc-record leaves them out), so plain -T is
        # exact, in GNU tar and busybox alike
        ["-c", "tar -cf - -C / -T /dev/stdin"],
        stdin=names,
        binary=True,
    )
    dest.write_bytes(proc.stdout)
    return dest.stat().st_size
