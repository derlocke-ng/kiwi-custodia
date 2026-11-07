"""The window's size: a large default, the last one kept, never unusably small."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("gi")

from kiwi_custodia import paths  # noqa: E402
from kiwi_custodia.ui import window as w  # noqa: E402


class FakeWindow:
    def __init__(self, size, maximized=False):
        self.size, self.maximized = size, maximized

    def get_default_size(self):
        return self.size

    def is_maximized(self):
        return self.maximized


def test_default_then_the_remembered_size_then_a_floor():
    assert w.saved_geometry() == (*w.DEFAULT_SIZE, False)
    w.remember_geometry(FakeWindow((900, 700), maximized=True))
    saved = json.loads((paths.config_dir() / "window.json").read_text())
    assert saved == {"width": 900, "height": 700, "maximized": True}
    assert w.saved_geometry() == (900, 700, True)
    (paths.config_dir() / "window.json").write_text('{"width": 10, "height": "x"}')
    assert w.saved_geometry() == (*w.DEFAULT_SIZE, False)  # garbage: the default
    (paths.config_dir() / "window.json").write_text('{"width": 10, "height": 10}')
    assert w.saved_geometry() == (640, 480, False)
