"""Main window: the boxes, whether each runs, and the setup state behind them."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from kiwi_proxy import podman  # noqa: E402

from .. import boxes, desktop, paths, setup, store  # noqa: E402
from ..cli import describe  # noqa: E402
from ..models import Box  # noqa: E402
from . import worker  # noqa: E402
from .dialogs import AppsDialog, BoxDetails, BoxEditor, LogsDialog  # noqa: E402

REFRESH_SECONDS = 4


class Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(default_width=760, default_height=600, title="Kiwi Custodia", **kwargs)
        self._rows: dict[str, Adw.ActionRow] = {}
        self._busy: set[str] = set()
        self._state: dict[str, str] = {}  # box id -> running | stopped | gateway-down
        self._polling = False

        self.toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New box")
        new_button.connect("clicked", self._on_new)
        header.pack_start(new_button)

        menu = Gio.Menu()
        menu.append("Set up environment", "win.setup")
        menu.append("Check environment", "win.doctor")
        menu.append("Tidy up unused containers", "win.reap")
        menu.append("Stop every box", "win.stop-all")
        menu.append("About Kiwi Custodia", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)

        self.status_banner = Adw.Banner(revealed=False)
        self.status_banner.set_button_label("Set up")
        self.status_banner.connect("button-clicked", lambda *_: self._run_setup())

        self.page = Adw.PreferencesPage()
        self.group = Adw.PreferencesGroup(
            title="Boxes",
            description="Each box is a distribution with a home of its own, joined to one "
            "kiwi-proxy exit. Everything in it — packages, updates, its apps on this "
            "desktop — leaves through that exit and nothing else.",
        )
        self.page.add(self.group)

        self.empty = Adw.StatusPage(
            icon_name="package-x-generic-symbolic",
            title="No boxes yet",
            description="A box is Fedora, Ubuntu, Debian, Arch, openSUSE or Alpine in a "
            "container whose only route is an exit from Kiwi Proxy. Install anything in it.",
        )
        create = Gtk.Button(label="New box", halign=Gtk.Align.CENTER)
        create.add_css_class("suggested-action")
        create.add_css_class("pill")
        create.connect("clicked", self._on_new)
        self.empty.set_child(create)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.page, "list")
        self.stack.add_named(self.empty, "empty")

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.status_banner)
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        for name, handler in (
            ("setup", lambda *_: self._run_setup()),
            ("doctor", lambda *_: self._check_environment(announce=True)),
            ("reap", lambda *_: self._reap()),
            ("stop-all", lambda *_: self._stop_all()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        for name, handler in (
            ("details", self._act_details),
            ("edit", self._act_edit),
            ("apps", self._act_apps),
            ("check", self._act_check),
            ("logs", self._act_logs),
            ("open-home", self._act_open_home),
            ("delete", self._act_delete),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", handler)
            self.add_action(action)

        self.refresh()
        self._check_environment()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # ------------------------------------------------------------------ list
    def _tick(self) -> bool:
        self.refresh(rebuild=False)
        return True

    def refresh(self, rebuild: bool = True) -> None:
        found = store.list_boxes()
        self.stack.set_visible_child_name("list" if found else "empty")
        if rebuild:
            for row in self._rows.values():
                self.group.remove(row)
            self._rows.clear()
            for box in found:
                row = self._build_row(box)
                self._rows[box.id] = row
                self.group.add(row)
        for box in found:
            if row := self._rows.get(box.id):
                self._update_row(row, box)
        self._poll()

    def _poll(self) -> None:
        if self._polling:
            return
        self._polling = True

        def work():
            if not podman.available():
                return {}
            return {b.id: boxes.state(b) for b in store.list_boxes()}

        def done(state) -> None:
            self._polling = False
            if state != self._state:
                self._state = state
                for box in store.list_boxes():
                    if row := self._rows.get(box.id):
                        self._update_row(row, box)

        def failed(_exc: Exception) -> None:
            self._polling = False

        worker.run(work, done, failed)

    def _build_row(self, box: Box) -> Adw.ActionRow:
        row = Adw.ActionRow(title=box.name, activatable=True, use_markup=False)
        row.connect("activated", lambda *_: self._open_details(box.id))
        state = Gtk.Image(icon_name="package-x-generic-symbolic")
        row.add_prefix(state)
        row.state_icon = state  # type: ignore[attr-defined]

        term = Gtk.Button(
            icon_name="utilities-terminal-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Open a terminal in the box",
        )
        term.add_css_class("flat")
        term.connect("clicked", self._on_terminal, box.id)
        row.add_suffix(term)

        toggle = Gtk.Button(valign=Gtk.Align.CENTER)
        toggle.connect("clicked", self._on_toggle, box.id)
        row.add_suffix(toggle)
        row.toggle_button = toggle  # type: ignore[attr-defined]

        menu = Gio.Menu()
        menu.append("Applications…", f"win.apps::{box.id}")
        menu.append("Details", f"win.details::{box.id}")
        menu.append("Edit…", f"win.edit::{box.id}")
        menu.append("Check the exit", f"win.check::{box.id}")
        menu.append("Open the home folder", f"win.open-home::{box.id}")
        menu.append("Logs", f"win.logs::{box.id}")
        menu.append("Delete", f"win.delete::{box.id}")
        more = Gtk.MenuButton(
            icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, menu_model=menu
        )
        more.add_css_class("flat")
        row.add_suffix(more)
        return row

    def _update_row(self, row: Adw.ActionRow, box: Box) -> None:
        st = self._state.get(box.id, "stopped")
        row.set_title(box.name)
        row.set_subtitle(describe(box))
        icon = row.state_icon  # type: ignore[attr-defined]
        for css in ("success", "warning", "dim-label"):
            icon.remove_css_class(css)
        if st == "running":
            icon.add_css_class("success")
            icon.set_tooltip_text("running, through its exit")
        elif st == "gateway-down":
            icon.add_css_class("warning")
            icon.set_tooltip_text("running, but its gateway or tunnel is gone: no route")
        else:
            icon.add_css_class("dim-label")
            icon.set_tooltip_text("stopped")
        button = row.toggle_button  # type: ignore[attr-defined]
        if box.id in self._busy:
            button.set_label("Working…")
            button.set_sensitive(False)
            return
        button.set_sensitive(True)
        button.set_label("Stop" if st != "stopped" else "Start")
        for css in ("suggested-action", "destructive-action"):
            button.remove_css_class(css)
        button.add_css_class("destructive-action" if st != "stopped" else "suggested-action")

    # --------------------------------------------------------------- actions
    def _box(self, ident: str) -> Box | None:
        return next((b for b in store.list_boxes() if b.id == ident), None)

    def _open_details(self, ident: str) -> None:
        if box := self._box(ident):
            BoxDetails(box, self._toast).present(self)

    def _act_details(self, _action, param) -> None:
        self._open_details(param.get_string())

    def _act_edit(self, _action, param) -> None:
        if box := self._box(param.get_string()):
            BoxEditor(box, self._after_edit).present(self)

    def _after_edit(self, box: Box) -> None:
        self.refresh()
        note = " — stop and start it to apply" if self._state.get(box.id) == "running" else ""
        self._toast(f"Saved {box.name}{note}")

    def _act_apps(self, _action, param) -> None:
        box = self._box(param.get_string())
        if not box:
            return
        if self._state.get(box.id) != "running":
            self._start(box, then=lambda: AppsDialog(box, self._toast, self._alert).present(self))
            return
        AppsDialog(box, self._toast, self._alert).present(self)

    def _act_check(self, _action, param) -> None:
        box = self._box(param.get_string())
        if not box:
            return
        if self._state.get(box.id) != "running":
            self._toast(f"{box.name} is stopped; start it first")
            return

        def done(info) -> None:
            place = " ".join(x for x in (info.country, info.city) if x)
            self._toast(f"{box.name} leaves as {info.ip} {place}".rstrip())

        worker.run(
            lambda: boxes.check(box),
            done,
            lambda exc: self._alert(f"Could not check {box.name}", str(exc)),
        )

    def _act_logs(self, _action, param) -> None:
        box = self._box(param.get_string())
        if not box:
            return

        def work():
            out = []
            for name in (
                paths.box_name(box.id),
                paths.tunnel_name(box.exit),
                paths.gateway_name(box.exit),
            ):
                if podman.exists(name):
                    out.append(f"=== {name}\n{podman.logs(name, tail=150)}")
            return "\n\n".join(out)

        worker.run(work, lambda text: LogsDialog(f"Logs — {box.name}", text).present(self))

    def _act_open_home(self, _action, param) -> None:
        if box := self._box(param.get_string()):
            home = paths.box_home(box.id)
            home.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(f"file://{home}", None)

    def _act_delete(self, _action, param) -> None:
        box = self._box(param.get_string())
        if not box:
            return
        dialog = Adw.AlertDialog(
            heading=f"Delete {box.name}?",
            body=f"The box is stopped and removed with its home folder "
            f"({paths.box_home(box.id)}) and its entries in the app grid. The exit stays.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "delete":
                return
            self._busy.add(box.id)
            self.refresh(rebuild=False)

            def done(_r) -> None:
                self._busy.discard(box.id)
                self.refresh()
                self._toast(f"Deleted {box.name}")

            def failed(exc: Exception) -> None:
                self._busy.discard(box.id)
                self.refresh()
                self._alert(f"Could not delete {box.name}", str(exc))

            worker.run(lambda: boxes.delete(box), done, failed)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_new(self, *_args) -> None:
        BoxEditor(None, self._after_create).present(self)

    def _after_create(self, box: Box) -> None:
        self.refresh()
        self._toast(f"Created {box.name} — start it to install its baseline")

    def _on_terminal(self, _button, ident: str) -> None:
        box = self._box(ident)
        if not box:
            return

        def open_() -> None:
            try:
                desktop.open_terminal(box)
            except RuntimeError as exc:
                self._alert("No terminal", f"{exc}\n\nRun: kiwi-custodia enter {box.name}")

        if self._state.get(box.id) != "running":
            self._start(box, then=open_)
        else:
            open_()

    def _on_toggle(self, _button, ident: str) -> None:
        box = self._box(ident)
        if not box:
            return
        if self._state.get(ident, "stopped") != "stopped":
            self._stop(box)
        else:
            self._start(box)

    def _start(self, box: Box, then=None) -> None:
        missing = setup.ready() if podman.available() else ["podman"]
        if missing:
            self._alert("Not set up yet", "Missing: " + "; ".join(missing))
            return
        self._busy.add(box.id)
        self.refresh(rebuild=False)
        if boxes.has_snapshot(box):
            self._toast(f"Starting {box.name} from its snapshot")
        else:
            self._toast(
                f"Starting {box.name} — the first start installs its baseline, give it a minute"
            )

        def done(up) -> None:
            self._busy.discard(box.id)
            self._state[box.id] = "running"
            self.refresh()
            for note in up.notes:
                self._toast(note)
            self._toast(f"{box.name} is up, through its exit")
            if then:
                then()

        def failed(exc: Exception) -> None:
            self._busy.discard(box.id)
            self.refresh()
            self._alert(f"Could not start {box.name}", str(exc))

        worker.run(lambda: boxes.up(box), done, failed)

    def _stop(self, box: Box) -> None:
        self._busy.add(box.id)
        self.refresh(rebuild=False)

        def done(_r) -> None:
            self._busy.discard(box.id)
            self._state[box.id] = "stopped"
            self.refresh()
            self._toast(f"{box.name} is stopped")

        def failed(exc: Exception) -> None:
            self._busy.discard(box.id)
            self.refresh()
            self._alert(f"Could not stop {box.name}", str(exc))

        worker.run(lambda: boxes.stop(box), done, failed)

    def _stop_all(self) -> None:
        def work():
            for box in store.list_boxes():
                if boxes.running(box):
                    boxes.stop(box)

        worker.run(work, lambda _r: (self.refresh(), self._toast("Every box is stopped")))

    def _reap(self) -> None:
        def done(cleaned) -> None:
            self.refresh()
            self._toast(", ".join(cleaned) + " removed" if cleaned else "Nothing to tidy up")

        worker.run(boxes.reap, done, lambda exc: self._alert("Could not tidy up", str(exc)))

    # ----------------------------------------------------------- environment
    def _check_environment(self, announce: bool = False) -> None:
        def work():
            return setup.ready()

        def done(missing) -> None:
            if missing:
                self.status_banner.set_title("Setup incomplete: " + ", ".join(missing))
                self.status_banner.set_revealed(True)
            else:
                self.status_banner.set_revealed(False)
                if announce:
                    self._toast("Environment is ready")

        worker.run(work, done)

    def _run_setup(self) -> None:
        progress = Adw.AlertDialog(heading="Setting up", body="Starting…")
        progress.add_response("close", "Run in background")
        progress.present(self)

        def say(message: str) -> None:
            GLib.idle_add(progress.set_body, message)

        def done(steps) -> None:
            progress.close()
            self._check_environment()
            self.refresh()
            self._alert("Setup finished", "\n".join(steps))

        def failed(exc: Exception) -> None:
            progress.close()
            self._alert("Setup failed", str(exc))

        worker.run(lambda: setup.run(progress=say), done, failed)

    # ---------------------------------------------------------------- toasts
    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def _alert(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)
