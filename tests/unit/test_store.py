import pytest

from kiwi_custodia import distros, paths, store


def test_create_and_load(an_exit):
    box = store.create("work", distro="fedora", exit_id=an_exit.id, packages=["vim"])
    assert store.load(box.id).name == "work"
    assert box.image == distros.get("fedora").image
    assert box.packages == ["vim"]
    assert paths.box_home(box.id).is_dir()
    assert store.resolve_ref("work").id == box.id
    assert store.resolve_ref(box.id[:6]).id == box.id


def test_names_are_hostnames_and_file_names(an_exit):
    for bad in ("Work", "my box", "-x", "a.b", ""):
        with pytest.raises(store.StoreError):
            store.create(bad, distro="fedora", exit_id=an_exit.id)
    store.create("ok-1", distro="fedora", exit_id=an_exit.id)
    with pytest.raises(store.StoreError, match="exists"):
        store.create("ok-1", distro="fedora", exit_id=an_exit.id)


def test_exit_must_exist():
    with pytest.raises(store.StoreError, match="no kiwi-proxy exit"):
        store.create("x", distro="fedora", exit_id="nope")


def test_unknown_distro(an_exit):
    with pytest.raises(store.StoreError, match="unknown distro"):
        store.create("x", distro="gentoo", exit_id=an_exit.id)


def test_exit_of_missing_is_explained(a_box):
    from kiwi_proxy import exits

    exits.delete(a_box.exit)
    with pytest.raises(store.StoreError, match="no longer has"):
        store.exit_of(a_box)


def test_delete_removes_home(a_box):
    home = paths.box_home(a_box.id)
    (home / "file").write_text("x")
    store.delete(a_box.id)
    assert not home.exists()
    assert store.list_boxes() == []


def test_rename(a_box, an_exit):
    other = store.create("other", distro="debian", exit_id=an_exit.id)
    with pytest.raises(store.StoreError):
        store.rename(a_box, "other")
    store.rename(a_box, "renamed")
    assert store.load(a_box.id).name == "renamed"
    assert store.boxes_on(an_exit.id) == sorted([a_box, other], key=lambda b: b.name)


def test_each_new_box_gets_a_colour_and_its_entry_shows_it(monkeypatch):
    from conftest import make_exit
    from kiwi_proxy import exits

    from kiwi_custodia import APP_ID, desktop, icons, store

    ex = make_exit("colours")
    monkeypatch.setattr(exits, "exists", lambda ref: True)
    a = store.create("one", distro="debian", exit_id=ex.id)
    b = store.create("two", distro="debian", exit_id=ex.id)
    assert a.color and b.color and a.color != b.color
    svg = icons.colored_icon(a).read_text()
    assert svg.startswith("<svg") and "M64 52.5l10.5 5.5" in svg  # Custodia's cube, coloured
    assert f"Icon={icons.colored_icon(a)}\n" in desktop.render_entry(a, "a box")
    a.color = ""
    assert f"Icon={APP_ID}\n" in desktop.render_entry(a, "a box")
    store.save(a)
    assert '"color"' not in (store.paths.box_dir(a.id) / store.RECORD).read_text()
