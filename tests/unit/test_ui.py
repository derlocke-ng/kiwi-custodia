"""The window's notice for newer snapshots: what it says, ✕ until the news
changes, and Import (not while a box runs). Needs a display: run it through
kiwi-fox's docs/plan/tools/gui-tests-headless.sh, as the other apps' UI tests."""

from __future__ import annotations

import types

import pytest

gi = pytest.importorskip("gi", exc_type=ImportError)
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

pytestmark = pytest.mark.skipif(not Gtk.init_check(), reason="no display; GTK cannot initialise")


@pytest.fixture(scope="module", autouse=True)
def _adw():
    Adw.init()


def _window(boxes_here, relations, running=()):
    """The window's notice methods on a stand-in with just what they use."""
    from kiwi_custodia.ui import window as w
    from kiwi_custodia.ui.notice import Notice

    fake = types.SimpleNamespace(
        _relations=relations,
        _state={b.id: "running" for b in boxes_here if b.name in running},
        notice=Notice(),
        toasts=[],
        alerts=[],
        changed=0,
    )
    fake._box = lambda bid: next((b for b in boxes_here if b.id == bid), None)
    fake._newer = lambda: w.Window._newer(fake)
    fake._tell_newer = lambda: w.Window._tell_newer(fake)
    fake._import_newer = lambda: w.Window._import_newer(fake)
    fake._toast = fake.toasts.append
    fake._alert = lambda heading, body: fake.alerts.append((heading, body))

    def changed():
        fake.changed += 1

    fake._snapshots_changed = changed
    return fake


def _rel(state, head="s1"):
    from kiwi_proxy.snapshots import Relation

    head_meta = types.SimpleNamespace(id=head) if head else None
    return Relation(state, head_meta, [head_meta] if head_meta else [])


def test_the_notice_says_imports_and_leaves_running_boxes(monkeypatch):
    from kiwi_custodia import snapshots as box_snapshots
    from kiwi_custodia.ui import window as w
    from kiwi_custodia.ui import worker

    dev = types.SimpleNamespace(id="b1", name="dev")
    web = types.SimpleNamespace(id="b2", name="web")
    mine = types.SimpleNamespace(id="b3", name="mine")
    fake = _window(
        [dev, web, mine],
        {"b1": _rel("folder_newer"), "b2": _rel("folder_newer", "s2"), "b3": _rel("diverged")},
        running=("web",),
    )
    fake._tell_newer()
    assert fake.notice.shown
    assert fake.notice.label.get_text() == "2 newer snapshots in your folder: dev, web"

    fake.notice.close.emit("clicked")
    fake._tell_newer()
    assert not fake.notice.shown, "dismissed until the news changes"
    fake._relations["b1"] = _rel("folder_newer", "s9")
    fake._tell_newer()
    assert fake.notice.shown, "a newer snapshot again is news"

    restored = []
    monkeypatch.setattr(
        box_snapshots, "restore", lambda bid, sid: restored.append((bid, sid)) or dev
    )
    monkeypatch.setattr(worker, "run", lambda work, done, failed=None: done(work()))
    fake.notice.button.emit("clicked")
    assert restored == [("b1", "s9")], "a running box and one changed on both sides are left"
    assert fake.toasts == ["Imported dev; web is running: stop, then import"]
    assert fake.changed == 1 and not fake.notice.shown
    assert w.notice_text(list("abcde")) == "5 newer snapshots in your folder: a, b, c and 2 more"


def test_nothing_newer_says_nothing():
    fake = _window([types.SimpleNamespace(id="b1", name="dev")], {"b1": _rel("same")})
    fake.notice.say("old news")
    fake._tell_newer()
    assert not fake.notice.shown
