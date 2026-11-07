"""Desktop files out of a box, and entries on the host."""

from __future__ import annotations

import subprocess

import pytest

from kiwi_custodia import APP_ID, apps, boxes, desktop, paths, store

FIREFOX = """[Desktop Entry]
Version=1.0
Name=Firefox
Name[de]=Firefox (de)
Comment=Browse the Web
Exec=firefox %u
Icon=firefox
Terminal=false
Type=Application
Categories=Network;WebBrowser;
StartupWMClass=firefox

[Desktop Action new-window]
Name=New Window
Exec=firefox --new-window %u
"""

HIDDEN = """[Desktop Entry]
Name=Helper
Exec=helper
NoDisplay=true
Type=Application
"""

LINK = """[Desktop Entry]
Type=Link
Name=A link
URL=https://example.org
"""


def test_parse_entry():
    app = apps.parse_entry(FIREFOX, "firefox")
    assert app is not None
    assert (app.name, app.exec, app.icon) == ("Firefox", "firefox %u", "firefox")
    assert app.categories == ["Network", "WebBrowser"]
    assert app.startup_wm_class == "firefox"
    assert not app.terminal and not app.nodisplay
    assert apps.parse_entry(HIDDEN, "helper").nodisplay
    assert apps.parse_entry(LINK, "link") is None


def _dump(*files: tuple[str, str]) -> str:
    return "".join(f"\x01{path}\n{body}" for path, body in files)


def test_list_apps(a_box, fake_podman):
    boxes.up(a_box)
    fake_podman.exec_result = subprocess.CompletedProcess(
        [],
        0,
        stdout=_dump(
            ("/usr/share/applications/firefox.desktop", FIREFOX),
            ("/usr/share/applications/helper.desktop", HIDDEN),
        ),
        stderr="",
    )
    found = apps.list_apps(a_box)
    assert [a.id for a in found] == ["firefox"]
    assert [a.id for a in apps.list_apps(a_box, include_hidden=True)] == ["firefox", "helper"]


def test_list_apps_needs_a_running_box(a_box, fake_podman):
    with pytest.raises(apps.AppError, match="not running"):
        apps.list_apps(a_box)


def test_export_writes_entry_and_icon(a_box, fake_podman, monkeypatch):
    boxes.up(a_box)
    results = {
        "dump": subprocess.CompletedProcess(
            [], 0, stdout=_dump(("/usr/share/applications/firefox.desktop", FIREFOX)), stderr=""
        ),
        "icons": subprocess.CompletedProcess(
            [],
            0,
            stdout="/usr/share/icons/hicolor/48x48/apps/firefox.png\n/usr/share/icons/hicolor/scalable/apps/firefox.svg\n",
            stderr="",
        ),
    }

    def exec_(name, args, timeout=60):
        return results["icons"] if "find" in args[-1] else results["dump"]

    monkeypatch.setattr(apps.podman, "exec_", exec_)
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)  # not the machine's install
    path = apps.export(a_box, "firefox")
    assert path == paths.applications_dir() / f"{APP_ID}.box-work-firefox.desktop"
    text = path.read_text()
    assert "Name=Firefox (work)" in text
    assert f"Exec=kiwi-custodia run {a_box.id} -- firefox\n" in text  # %u stripped
    assert "Icon=kc-work-firefox" in text
    assert "StartupWMClass=firefox" in text
    assert (paths.icons_dir() / "48x48" / "apps" / "kc-work-firefox.png").exists()
    assert (paths.icons_dir() / "scalable" / "apps" / "kc-work-firefox.svg").exists()
    assert store.load(a_box.id).exported == ["firefox"]

    apps.unexport(store.load(a_box.id), "firefox")
    assert not path.exists()
    assert not (paths.icons_dir() / "48x48" / "apps" / "kc-work-firefox.png").exists()
    assert store.load(a_box.id).exported == []


def test_export_without_icon_uses_ours(a_box, fake_podman, monkeypatch):
    boxes.up(a_box)
    no_icon = FIREFOX.replace("Icon=firefox\n", "")
    fake_podman.exec_result = subprocess.CompletedProcess(
        [], 0, stdout=_dump(("/usr/share/applications/firefox.desktop", no_icon)), stderr=""
    )
    text = apps.export(a_box, "firefox").read_text()
    assert f"Icon={APP_ID}" in text


def test_box_desktop_entry(a_box):
    a_box.desktop_entry = True
    assert desktop.sync_entry(a_box, "Fedora, through work")
    text = desktop.entry_path(a_box.id).read_text()
    assert "Terminal=true" in text
    assert f"enter {a_box.id}" in text
    assert "[Desktop Action stop]" in text
    a_box.desktop_entry = False
    assert not desktop.sync_entry(a_box, "")
    assert not desktop.entry_path(a_box.id).exists()


def test_sync_all_removes_stale(a_box):
    stale = paths.applications_dir() / f"{desktop.ENTRY_PREFIX}deadbeef.desktop"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("x")
    a_box.desktop_entry = True
    store.save(a_box)
    with_entry, removed = desktop.sync_all(store.list_boxes(), lambda b: "d")
    assert with_entry == ["work"]
    assert removed == [stale.name]


def test_terminal_command(monkeypatch):
    monkeypatch.setattr(
        desktop.shutil, "which", lambda exe: "/usr/bin/kgx" if exe == "kgx" else None
    )
    assert desktop.terminal_command(["kiwi-custodia", "enter", "x"]) == [
        "/usr/bin/kgx",
        "--",
        "kiwi-custodia",
        "enter",
        "x",
    ]
    monkeypatch.setattr(desktop.shutil, "which", lambda exe: None)
    assert desktop.terminal_command(["x"]) is None
