"""The question before a box starts from an exported app.

`kiwi-custodia run --quiet BOX` from an app in the app grid has no terminal to ask
in. When the snapshot folder holds a newer copy of the box, or says it is in use
on another device, this asks the same question the Kiwi Custodia window asks, in a
small window of its own, and returns the answer: restore | asis | mine | cancel.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402
from kiwi_proxy import snapshots  # noqa: E402
from kiwi_proxy.ui import snapshots as snapshot_ui  # noqa: E402

from .. import APP_ID  # noqa: E402


def in_use_dialog(name: str, in_use, on_answer) -> Adw.AlertDialog:
    who = ", ".join(f"{device} since {snapshots.when_text(since)}" for device, since in in_use)
    dialog = Adw.AlertDialog(
        heading=f"{name} is in use on another device",
        body=f"The snapshot folder says it is open on {who}. Starting it here as well "
        "makes two copies that both change; only one of them can win later.",
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("start", "Start anyway")
    dialog.set_response_appearance("start", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, r: on_answer(r))
    return dialog


def ask(name: str, check) -> str:
    """Ask, in a window of its own; blocks until answered."""
    answer = {"value": "cancel"}
    app = Adw.Application(
        application_id=f"{APP_ID}.StartPrompt", flags=Gio.ApplicationFlags.NON_UNIQUE
    )

    def finish(value: str) -> None:
        answer["value"] = value
        app.release()
        app.quit()

    def newer() -> None:
        rel = check.relation
        if not (rel and rel.newer_elsewhere):
            finish("asis")
            return
        snapshot_ui.ask_newer(
            None,
            name,
            rel,
            verb="start",
            on_restore=lambda: finish("restore"),
            on_as_is=lambda: finish("asis"),
            on_keep_mine=lambda: finish("mine"),
            on_cancel=lambda: finish("cancel"),
        )

    def activate(_app) -> None:
        app.hold()
        if check.in_use:
            in_use_dialog(
                name, check.in_use, lambda r: newer() if r == "start" else finish("cancel")
            ).present(None)
        else:
            newer()

    app.connect("activate", activate)
    app.run([])
    return answer["value"]
