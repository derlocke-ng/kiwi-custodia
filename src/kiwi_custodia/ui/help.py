"""Short text on screen, the rest behind a (?): kiwi-proxy's shared helper
(0.8.3 on), with a plain stand-in for an older kiwi-proxy that shows no (?)."""

from __future__ import annotations

try:
    from kiwi_proxy.ui.help import explain, info_button, widen  # noqa: F401
except ImportError:  # pragma: no cover - kiwi-proxy older than 0.8.3

    def explain(widget, text, *, app="", anchor="", link=True):
        return None

    def info_button(text, *, app="", anchor="", link=True):
        return None

    def widen(page, width=920):
        return None


APP = "kiwi-custodia"
