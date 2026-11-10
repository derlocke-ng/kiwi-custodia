"""Boxes in the snapshot folder: what is recorded, what travels, how a box is
rebuilt on another device.

Real gpg and zstd through kiwi-proxy's snapshot library, the passphrase stretching
turned down; two devices are two sets of XDG directories over one folder. Podman
is the fake from conftest; what kc-record would read from an image is faked too.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest
from conftest import make_exit

from kiwi_custodia import boxes, cli, paths, recipe, store
from kiwi_custodia import snapshots as kc

PASS = "correct horse battery staple"
ROOT = Path(__file__).resolve().parents[2]

needs_snapshots = pytest.mark.skipif(
    not kc.available() or bool(kc.snap and kc.snap.missing_tools()),
    reason="box snapshots need kiwi-proxy 0.8.1, gpg and zstd",
)


# ------------------------------------------------------------------ recipe
def test_candidates_keep_what_you_added_and_leave_the_machines_own():
    from kiwi_custodia import boxes

    assert boxes.INIT_SCRIPT in recipe.SKIP  # a bind mount leaves its file in the image
    diff = {
        "added": [
            "/etc/yum.repos.d/claude-desktop.repo",
            "/etc/pki/rpm-gpg/RPM-GPG-KEY-claude",
            "/opt/tool/bin/tool",
            "/usr/local/bin/helper",
            "/home/tester/notes.txt",
            "/var/cache/dnf/x",
            "/etc/sudoers.d/kiwi-custodia",
            "/usr/local/bin/kc-shell",
            "/usr/local/bin/kc-init",
            "/etc/ssl/certs/ca-bundle.crt",
            "/root/.cache/x",
        ],
        "changed": ["/etc/bashrc", "/etc/passwd", "/etc/hostname", "/usr/bin/ls"],
    }
    assert recipe.candidates(diff) == [
        "/etc/bashrc",
        "/etc/pki/rpm-gpg/RPM-GPG-KEY-claude",
        "/etc/yum.repos.d/claude-desktop.repo",
        "/opt/tool/bin/tool",
        "/usr/local/bin/helper",
    ]
    assert recipe.candidates({"added": None, "changed": None}) == []


def test_repository_files_per_family():
    files = [
        "/etc/yum.repos.d/a.repo",
        "/etc/pki/rpm-gpg/KEY",
        "/etc/bashrc",
        "/etc/apt/sources.list.d/b.list",
        "/usr/share/keyrings/b.gpg",
    ]
    assert recipe.repo_files("dnf", files) == ["etc/yum.repos.d/a.repo", "etc/pki/rpm-gpg/KEY"]
    assert recipe.repo_files("apt", files) == [
        "etc/apt/sources.list.d/b.list",
        "usr/share/keyrings/b.gpg",
    ]
    assert recipe.repo_files("apk", files) == []


def test_summary_names_repositories_counts_keys_and_folds_folders():
    files = [
        "/etc/yum.repos.d/claude-desktop.repo",
        "/etc/pki/rpm-gpg/KEY-1",
        "/etc/pki/rpm-gpg/KEY-2",
        "/opt/tool/bin/tool",
        "/opt/tool/lib/libtool.so",
        "/etc/bashrc",
        "/usr/local/share/man/man1/x.1",
        "/srv/www/index.html",
    ]
    text = recipe.summary(files, "dnf")
    assert text.startswith("/etc/yum.repos.d/claude-desktop.repo, 2 signing keys, /opt/tool")
    assert text.endswith("/opt/tool, /etc/bashrc and 2 more")
    assert recipe.summary([], "dnf") == ""
    assert recipe.summary(["/etc/pki/rpm-gpg/K"], "dnf") == "1 signing key"


def test_the_baseline_comes_from_kc_init_itself():
    dnf = recipe.baseline("dnf")
    assert {"sudo", "tar", "bash"} <= dnf
    assert "tar" in recipe.baseline("apt") and "tar" in recipe.baseline("apk")
    assert recipe.baseline("nonsense") == set()


class FakeImages:
    """What kc-record answers for the box's image and its base image."""

    def __init__(self, monkeypatch, fake_podman):
        self.calls: list[tuple[str, list[str], str | None]] = []
        self.packages = {
            "BASE": "bash -\ncoreutils -\n",
            "BOX": "bash -\ncoreutils -\nsudo -\ncowsay fedora\nclaude-desktop claude\n"
            "mytool @local\ngit fedora\n",
        }
        self.keep = {
            "/etc/yum.repos.d/claude.repo",
            "/etc/pki/rpm-gpg/CLAUDE",
            "/etc/bashrc",
            "/opt/thing/run",
        }
        self.diff = {
            "added": [
                "/etc/yum.repos.d/claude.repo",
                "/etc/pki/rpm-gpg/CLAUDE",
                "/opt/thing/run",
                "/usr/bin/cowsay",
                "/home/tester/x",
            ],
            "changed": ["/etc/bashrc", "/etc/passwd", "/etc/dnf/dnf.conf"],
        }
        monkeypatch.setattr(recipe, "_in_image", self.in_image)
        original = fake_podman._run

        def run(args, *, check=True, timeout=120):
            if args[:1] == ["diff"]:
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.diff))
            if args[:2] == ["image", "inspect"]:
                return subprocess.CompletedProcess(args, 0, stdout="1900000000\n")
            return original(args, check=check, timeout=timeout)

        monkeypatch.setattr(recipe.podman, "_run", run)

    def in_image(self, image, family, args, *, stdin=None, timeout=600, binary=False):
        which = "BASE" if "box-" not in image else "BOX"
        self.calls.append((which, args, stdin))
        out: str | bytes = ""
        if args[:2] == ["/run/kc-record", "packages"]:
            out = self.packages[which]
        elif args[:2] == ["/run/kc-record", "files"]:
            out = "".join(f"keep {p}\n" for p in stdin.split() if p in self.keep)
        elif args[:2] == ["/run/kc-record", "local"]:
            out = "file /usr/bin/mytool\nfile /usr/share/mytool/data\nreq libfoo.so.1\nreq bash\n"
        elif args[:1] == ["-c"]:  # tar of the recorded files
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for name in stdin.split():
                    data = f"content of /{name}\n".encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            out = buf.getvalue()
        if binary and isinstance(out, str):
            out = out.encode()
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr=b"")


@pytest.fixture
def images(monkeypatch, fake_podman):
    return FakeImages(monkeypatch, fake_podman)


def test_record_reads_what_was_added_over_the_base_image(a_box, fake_podman, images):
    fake_podman.images.add(a_box.image)
    a_box.packages = ["git"]  # declared: installed anyway, not recorded again
    rec = recipe.record(a_box, paths.box_image(a_box.id))
    assert rec.family == "dnf"
    # sudo is kc-init's baseline, bash and coreutils the base image's
    assert rec.packages == ["claude-desktop", "cowsay"]
    assert rec.local == ["mytool"]
    assert rec.requires == ["bash", "libfoo.so.1"]
    assert "/usr/bin/mytool" in rec.files and "/opt/thing/run" in rec.files
    assert "/etc/passwd" not in rec.files and "/home/tester/x" not in rec.files
    assert rec.repo_files == ["etc/pki/rpm-gpg/CLAUDE", "etc/yum.repos.d/claude.repo"]
    # files kc-record was asked about: the candidates only, no home, no machine files
    asked = next(stdin for which, args, stdin in images.calls if args[1:2] == ["files"])
    assert "/home/tester/x" not in asked and "/etc/passwd" not in asked


def test_record_without_the_base_image_says_so(a_box, fake_podman, images):
    rec = recipe.record(a_box, paths.box_image(a_box.id))
    assert any("not here" in n for n in rec.notes)
    # nothing to subtract but kc-init's baseline (bash and sudo are in it)
    assert "coreutils" in rec.packages
    assert "bash" not in rec.packages and "sudo" not in rec.packages


def test_write_files_reads_them_out_of_the_image(a_box, fake_podman, images, tmp_path):
    rec = recipe.Recording(family="dnf", files=["/etc/bashrc", "/opt/thing/run"], image="x/box-1")
    dest = tmp_path / "files.tar"
    assert recipe.write_files(rec, dest) == dest.stat().st_size
    with tarfile.open(dest) as tar:
        assert sorted(tar.getnames()) == ["etc/bashrc", "opt/thing/run"]
    empty = recipe.write_files(recipe.Recording(family="dnf"), tmp_path / "empty.tar")
    assert empty > 0
    with tarfile.open(tmp_path / "empty.tar") as tar:
        assert tar.getnames() == []


def test_kc_record_reads_rpm_verify_flags():
    script = ROOT / "containers" / "box" / "kc-record.sh"
    body = script.read_text()
    awk = body.split("awk '", 1)[1].split("'", 1)[0]
    lines = (
        "S.5....T.  c /etc/bashrc\n"
        ".M.......    /usr/bin/x\n"
        "..?......    /etc/secret\n"
        "missing     /etc/gone\n"
        "....L....    /etc/alternatives/y\n"
    )
    out = subprocess.run(["awk", awk], input=lines, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["/etc/bashrc", "/etc/alternatives/y"]


def test_kc_record_local_skips_files_the_image_left_out(tmp_path):
    """A package installed from a file lists docs the image never unpacked
    (tsflags=nodocs); kc-record must go on past them, not end quietly with
    set -e (found on the VM)."""
    present = tmp_path / "usr-bin-sl"
    present.write_text("binary")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "rpm").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  "-ql sl") printf "%s\\n" {present} /usr/share/doc/sl/README /usr/share/man/man1/sl.1.gz ;;\n'
        '  "-q --requires sl") printf "libc.so.6()(64bit)\\nrpmlib(X) <= 1\\n/bin/sh\\nncurses-libs\\n" ;;\n'
        "esac\n"
    )
    (fake / "rpm").chmod(0o755)
    script = ROOT / "containers" / "box" / "kc-record.sh"
    out = subprocess.run(
        ["sh", str(script), "local", "sl"],
        env={"KC_FAMILY": "dnf", "PATH": f"{fake}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == [
        f"file {present}",
        "req libc.so.6()(64bit)",
        "req ncurses-libs",
    ]


def test_kc_scripts_are_posix_sh():
    for name in ("kc-init.sh", "kc-record.sh"):
        subprocess.run(["sh", "-n", str(ROOT / "containers" / "box" / name)], check=True)


# ------------------------------------------------------------ the folder
@pytest.fixture(scope="session")
def _gpg_home():
    home = tempfile.mkdtemp(prefix="kc-test-gpg-")
    yield home
    subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def fast(monkeypatch, _gpg_home):
    from kiwi_proxy.snapshots import crypt
    from kiwi_proxy.snapshots.folder import Folder

    monkeypatch.setattr(crypt, "S2K_COUNT", 1024)
    monkeypatch.setattr(crypt, "_gpg_home", lambda: contextlib.nullcontext(_gpg_home))
    kc.snap._session.clear()
    Folder.forget_unlocked()
    yield
    kc.snap._session.clear()
    Folder.forget_unlocked()


def device(tmp_path: Path, monkeypatch, name: str) -> None:
    from kiwi_proxy import paths as proxy_paths
    from kiwi_proxy.snapshots.folder import Folder

    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(var, str(tmp_path / name / var.lower()))
    proxy_paths.ensure_tree()
    paths.ensure_tree()
    kc.snap._session.clear()
    Folder.forget_unlocked()


def a_used_box(fake_podman, name="dev"):
    ex = make_exit("work")
    box = store.create(name, distro="fedora", exit_id=ex.id)
    box.setup_script = "echo hello > /etc/motd\n"
    box.exported = ["org.gnome.gedit"]
    store.save(box)
    home = paths.box_home(box.id)
    (home / ".cache" / "big").mkdir(parents=True)
    (home / ".cache" / "big" / "blob").write_text("x" * 5000)
    (home / ".bashrc").write_text("alias ll='ls -l'\n")
    (home / "work" / "notes.md").parent.mkdir(parents=True)
    (home / "work" / "notes.md").write_text("notes\n")
    # it ran and stopped: its committed image is what kc-record reads
    fake_podman.images.add(paths.box_image(box.id))
    fake_podman.images.add(box.image)
    return box, ex


def archive_names(meta) -> list[str]:
    out = Path(tempfile.mkdtemp())
    kc.snap.folder().extract(meta, out)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if not p.is_dir())


@needs_snapshots
def test_a_box_snapshot_holds_record_home_and_system(
    tmp_path, monkeypatch, fast, fake_podman, images
):
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(tmp_path / "shared", PASS, device_name="lime")
    box, _ex = a_used_box(fake_podman)
    meta = kc.take(box)
    names = archive_names(meta)
    assert "box.json" in names and "system/recipe.json" in names and "system/files.tar" in names
    assert "home/.bashrc" in names and "home/work/notes.md" in names
    assert not any(n.startswith("home/.cache") for n in names)
    extra = meta.extra
    assert extra["packages"] == ["claude-desktop", "cowsay", "git"]
    assert extra["local"] == ["mytool"] and extra["exit_name"] == "work"
    assert extra["files"] == 6 and extra["files_size"] > 0
    assert extra["files_summary"].startswith("/etc/yum.repos.d/claude.repo, 1 signing key")
    assert extra["home_size"] < 5000 and extra["setup_script"] is True
    assert meta.app == "kiwi-custodia"


@needs_snapshots
def test_after_stop_takes_what_ran_and_nothing_else(
    tmp_path, monkeypatch, fast, fake_podman, images
):
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(tmp_path / "shared", PASS)
    box, _ex = a_used_box(fake_podman)
    assert kc.after_stop(box) is None
    assert len(kc.snap.history("box", box.id)) == 1
    assert kc.after_stop(box) is None
    assert len(kc.snap.history("box", box.id)) == 1
    kc.started(box)
    assert kc.after_stop(box) is None
    assert len(kc.snap.history("box", box.id)) == 2
    kc.changed(box)  # its record was edited
    kc.after_stop(box)
    assert len(kc.snap.history("box", box.id)) == 3


@needs_snapshots
def test_a_locked_folder_is_a_note_not_an_error(tmp_path, monkeypatch, fast, fake_podman, images):
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(tmp_path / "shared", PASS, remember=False)
    box, _ex = a_used_box(fake_podman)
    kc.snap.lock()
    note = kc.after_stop(box)
    assert note and "locked" in note


@needs_snapshots
def test_a_box_is_rebuilt_on_another_device(
    tmp_path, monkeypatch, fast, fake_podman, images, a_session
):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(shared, PASS, device_name="lime")
    box, _ex = a_used_box(fake_podman)
    meta = kc.take(box)

    device(tmp_path, monkeypatch, "titan")
    fake_podman.images = {i for i in fake_podman.images if "box-" not in i and i != box.image}
    kc.snap.setup(shared, PASS, device_name="titan")
    assert [a[1] for a in kc.away()] == ["dev"]
    with pytest.raises(kc.RestoreError, match="restore work in Kiwi Proxy first"):
        kc.restore(box.id, meta.id)
    make_exit("work")  # Kiwi Proxy restored the exit
    restored = kc.restore(box.id, meta.id)
    assert restored.name == "dev" and restored.setup_script.startswith("echo hello")
    home = paths.box_home(box.id)
    assert (home / "work" / "notes.md").read_text() == "notes\n"
    assert not (home / ".cache").exists()
    rebuild = paths.box_rebuild_dir(box.id)
    assert (rebuild / "packages.txt").read_text().split() == ["claude-desktop", "cowsay", "git"]
    assert (rebuild / "requires.txt").read_text().split() == ["bash", "libfoo.so.1"]
    assert (rebuild / "repo-files.txt").read_text().split() == [
        "etc/pki/rpm-gpg/CLAUDE",
        "etc/yum.repos.d/claude.repo",
    ]
    with tarfile.open(rebuild / "files.tar") as tar:
        assert tar.getnames()
    assert (rebuild / "reexport").read_text().split() == ["org.gnome.gedit"]
    assert (rebuild / "id").read_text().strip() == meta.id
    assert boxes.rebuild_pending(restored) and not boxes.has_snapshot(restored)
    assert kc.away() == []

    # the first start mounts the recipe and the setup script, from the base image
    fake_podman.images.add(restored.image)
    exported = []
    monkeypatch.setattr("kiwi_custodia.apps.export", lambda b, app: exported.append(app))
    up = boxes.up(restored)
    run = fake_podman.runs[-1]
    volumes = [run[i + 1] for i, a in enumerate(run) if a == "--volume"]
    assert f"{rebuild}:{boxes.REBUILD_DIR}:ro" in volumes
    assert f"{paths.box_setup_script(box.id)}:{boxes.SETUP_FILE}:ro" in volumes
    assert run[-2] == restored.image
    assert paths.box_setup_script(box.id).read_text() == "echo hello > /etc/motd\n"
    assert any("restored from a snapshot" in n for n in up.notes)
    assert exported == ["org.gnome.gedit"] and not (rebuild / "reexport").exists()

    # stopped: committed to its own image, the rebuild material goes
    boxes.stop(restored)
    assert boxes.has_snapshot(restored) and not rebuild.exists()
    fake_podman.runs.clear()
    boxes.up(restored)
    volumes = [a for a in fake_podman.runs[-1] if a.endswith(":ro")]
    assert not any(boxes.REBUILD_DIR in v or boxes.SETUP_FILE in v for v in volumes)


@needs_snapshots
def test_restoring_over_a_box_here_keeps_its_copy_aside(
    tmp_path, monkeypatch, fast, fake_podman, images
):
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(tmp_path / "shared", PASS)
    box, _ex = a_used_box(fake_podman)
    first = kc.take(box)
    (paths.box_home(box.id) / "later.txt").write_text("after the snapshot")
    kc.started(box)
    fake_podman.containers[paths.box_name(box.id)] = {"running": True, "labels": {}, "env": {}}
    with pytest.raises(kc.RestoreError, match="running"):
        kc.restore(box.id, first.id)
    fake_podman.containers.clear()
    kc.restore(box.id, first.id)
    assert not (paths.box_home(box.id) / "later.txt").exists()
    metas = kc.snap.history("box", box.id)
    assert any(m.aside for m in metas)
    assert not boxes.has_snapshot(box)  # rebuilt from the base image at its next start


@needs_snapshots
def test_travels_for_the_editor(tmp_path, monkeypatch, fast, fake_podman, images):
    device(tmp_path, monkeypatch, "lime")
    box, _ex = a_used_box(fake_podman)
    assert kc.travels(box).state == "off"
    kc.snap.setup(tmp_path / "shared", PASS, remember=False)
    t = kc.travels(box)
    assert t.state == "none" and t.image_size == 1900000000 and 0 < t.home_size < 5000
    kc.take(box)
    t = kc.travels(box)
    assert t.state == "taken" and t.recorded
    assert t.packages == ["claude-desktop", "cowsay", "git", "mytool"]
    assert t.files == 6 and t.files_summary
    kc.snap.lock()
    assert kc.travels(box).state == "locked"


@needs_snapshots
def test_cli_snapshot_now_show_and_restore(
    tmp_path, monkeypatch, fast, fake_podman, images, capsys
):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    kc.snap.setup(shared, PASS, device_name="lime")
    box, _ex = a_used_box(fake_podman)
    assert cli.main(["snapshot", "now", "dev"]) == 0
    out = capsys.readouterr().out
    assert "snapshot taken" in out and "3 packages, 6 system files" in out
    assert cli.main(["snapshot", "show", "dev"]) == 0
    out = capsys.readouterr().out
    assert "claude-desktop, cowsay, git" in out and "mytool" in out

    device(tmp_path, monkeypatch, "titan")
    kc.snap.setup(shared, PASS, device_name="titan")
    make_exit("work")
    assert cli.main(["snapshot", "list"]) == 0
    assert "dev" in capsys.readouterr().out
    assert cli.main(["snapshot", "restore", "dev", "--yes"]) == 0
    out = capsys.readouterr().out
    assert store.find_by_name("dev") is not None
    assert boxes.rebuild_pending(store.find_by_name("dev")), out


def test_cli_setup_script(a_box, fake_podman, capsys, tmp_path):
    script = tmp_path / "setup.sh"
    script.write_text("dnf -y copr enable x/y\n")
    assert cli.main(["set", "work", "--setup-script", str(script)]) == 0
    assert "setup script (1 lines)" in capsys.readouterr().out
    assert store.load(a_box.id).setup_script == "dnf -y copr enable x/y\n"
    assert cli.main(["set", "work", "--setup-script", ""]) == 0
    assert store.load(a_box.id).setup_script == ""


def test_a_fresh_box_runs_its_setup_script_once(a_box, an_exit, fake_podman, a_session):
    fake_podman.images.add(a_box.image)
    a_box.setup_script = "touch /etc/done\n"
    store.save(a_box)
    boxes.up(a_box)
    assert any(boxes.SETUP_FILE in a for a in fake_podman.runs[-1])
    boxes.stop(a_box)  # committed: the script ran in what the image holds
    boxes.up(a_box)
    assert not any(boxes.SETUP_FILE in a for a in fake_podman.runs[-1])


def test_up_says_which_packages_a_rebuild_could_not_install():
    logs = (
        "kc-init: rebuilding from a snapshot: repositories, packages, files\n"
        "kc-init: WARNING: could not install: lazygit nope (tried again at the next start)\n"
        "kc-init: ready — tester\n"
    )
    assert boxes._could_not_install(logs) == ["lazygit", "nope"]
    assert boxes._could_not_install("kc-init: ready — tester\n") == []
