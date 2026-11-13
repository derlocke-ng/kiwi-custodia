"""Main window: the boxes, whether each runs, and the setup state behind them."""

from __future__ import annotations

import contextlib
import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from kiwi_proxy import podman  # noqa: E402

from .. import boxes, desktop, distros, paths, setup, store  # noqa: E402
from .. import snapshots as box_snapshots  # noqa: E402
from ..cli import describe  # noqa: E402
from ..models import Box  # noqa: E402
from . import worker  # noqa: E402
from .dialogs import AppsDialog, BoxDetails, BoxEditor, LogsDialog  # noqa: E402
from .help import APP, explain, widen  # noqa: E402

REFRESH_SECONDS = 4
# How often the snapshot folder is looked at (in window ticks).
SNAPSHOT_TICKS = 5

if box_snapshots.available():
    from kiwi_proxy import snapshots as snap  # noqa: E402
    from kiwi_proxy.ui import snapshots as snapshot_ui  # noqa: E402
else:  # pragma: no cover - kiwi-proxy older than 0.8.1
    snap = snapshot_ui = None
try:
    from kiwi_proxy.ui import storage as storage_ui  # noqa: E402
except ImportError:  # pragma: no cover - kiwi-proxy older than 0.8.2
    storage_ui = None


# A window large enough for the largest dialog (the apps dialog is 720×520, the
# editor 600×640) to open at its own size instead of being squeezed; the size it
# had when last closed wins.
DEFAULT_SIZE = (1040, 840)
MIN_SIZE = (640, 480)


def saved_geometry() -> tuple[int, int, bool]:
    """(width, height, maximized) from config/window.json, else the default."""
    try:
        d = json.loads((paths.config_dir() / "window.json").read_text())
        width = max(int(d["width"]), MIN_SIZE[0])
        height = max(int(d["height"]), MIN_SIZE[1])
        return width, height, bool(d.get("maximized"))
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SIZE[0], DEFAULT_SIZE[1], False


def remember_geometry(window) -> None:
    """Keep the window's size for the next start. GTK 4 tracks the user's resizing
    in the default size, and keeps the un-maximized one while maximized."""
    width, height = window.get_default_size()
    try:
        paths.config_dir().mkdir(parents=True, exist_ok=True)
        (paths.config_dir() / "window.json").write_text(
            json.dumps({"width": width, "height": height, "maximized": window.is_maximized()})
        )
    except OSError:
        pass


class Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        width, height, maximized = saved_geometry()
        super().__init__(
            default_width=width, default_height=height, title="Kiwi Custodia", **kwargs
        )
        if maximized:
            self.maximize()
        self.connect("close-request", self._on_close_request)
        self._rows: dict[str, Adw.ActionRow] = {}
        self._busy: set[str] = set()
        self._state: dict[str, str] = {}  # box id -> running | stopped | gateway-down
        self._silent: set[str] = set()  # running boxes whose VPN is not answering
        self._polling = False
        self._relations: dict[str, object] = {}
        self._in_use: dict[str, list] = {}
        self._away: list = []
        self._away_rows: list[Adw.ActionRow] = []
        self._snap_polling = False
        self._ticks = 0

        self.toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New box")
        new_button.connect("clicked", self._on_new)
        header.pack_start(new_button)

        # The menu keeps what acts on the boxes now; snapshots and setting up,
        # checking, repairing and tidying are in Preferences, behind the gear.
        menu = Gio.Menu()
        menu.append("Stop every box", "win.stop-all")
        menu.append("About Kiwi Custodia", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        prefs_button = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Preferences")
        prefs_button.connect("clicked", lambda *_: self._open_preferences())
        header.pack_end(prefs_button)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)

        self.status_banner = Adw.Banner(revealed=False)
        self.status_banner.set_button_label("Set up")
        self.status_banner.connect("button-clicked", lambda *_: self._run_setup())
        self.snap_banner = Adw.Banner(
            title="Snapshots are locked on this device", button_label="Unlock", revealed=False
        )
        if snapshot_ui is not None:
            self.snap_banner.connect(
                "button-clicked", lambda *_: snapshot_ui.ask_unlock(self, self._snapshots_changed)
            )

        self.page = Adw.PreferencesPage()
        widen(self.page)
        self.group = Adw.PreferencesGroup(title="Boxes")
        explain(
            self.group,
            "Each box is a distribution with a home of its own, joined to one kiwi-proxy "
            "exit. Everything in it (packages, updates, its apps on this desktop) leaves "
            "through that exit and nothing else.",
            app=APP,
        )
        self.page.add(self.group)
        self.away_group = Adw.PreferencesGroup(
            title="In your snapshot folder, not on this device", visible=False
        )
        self.page.add(self.away_group)

        self.empty = Adw.StatusPage(
            icon_name="package-x-generic-symbolic",
            title="No boxes yet",
            description="A distribution whose only route is an exit",
        )
        create = Gtk.Button(label="New box", halign=Gtk.Align.CENTER)
        create.add_css_class("suggested-action")
        create.add_css_class("pill")
        create.connect("clicked", self._on_new)
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(create)
        if snapshot_ui is not None:
            from_folder = Gtk.Button(label="Use a snapshot folder", halign=Gtk.Align.CENTER)
            from_folder.add_css_class("pill")
            from_folder.set_tooltip_text("Bring the boxes of another device here, from snapshots")
            from_folder.connect(
                "clicked", lambda *_: snapshot_ui.choose_folder(self, self._snapshots_changed)
            )
            buttons.append(from_folder)
        self.empty.set_child(buttons)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.page, "list")
        self.stack.add_named(self.empty, "empty")

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.status_banner)
        view.add_top_bar(self.snap_banner)
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        for name, handler in (
            ("setup", lambda *_: self._run_setup()),
            ("doctor", lambda *_: self._check_environment(announce=True)),
            ("reap", lambda *_: self._reap()),
            ("stop-all", lambda *_: self._stop_all()),
            ("preferences", lambda *_: self._open_preferences()),
            ("snapshot-all", lambda *_: self._snapshot_all()),
            ("storage", lambda *_: storage_ui and storage_ui.check_and_repair(self, self.refresh)),
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
            ("snapshots", self._act_snapshots),
            ("forget-snapshots", self._act_forget_snapshots),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", handler)
            self.add_action(action)

        self.refresh()
        self._check_environment()
        self._repair_on_start()
        self._catch_up()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # ------------------------------------------------------------------ list

    def _on_close_request(self, *_args) -> bool:
        remember_geometry(self)
        return False  # and close

    def _tick(self) -> bool:
        self._ticks += 1
        if self._ticks % SNAPSHOT_TICKS == 0:
            self._poll_snapshots()
        self.refresh(rebuild=False)
        return True

    def refresh(self, rebuild: bool = True) -> None:
        found = store.list_boxes()
        self.stack.set_visible_child_name("list" if found or self._away else "empty")
        self.group.set_visible(bool(found))
        if rebuild:
            self._poll_snapshots()
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
                return {}, set()
            found = {b.id: boxes.state(b) for b in store.list_boxes()}
            silent = {
                b.id
                for b in store.list_boxes()
                if found.get(b.id) == "running" and boxes.vpn_silent(b)
            }
            return found, silent

        def done(result) -> None:
            self._polling = False
            state, silent = result
            if state != self._state or silent != self._silent:
                self._state, self._silent = state, silent
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
        if snapshot_ui is not None:
            menu.append("Snapshots…", f"win.snapshots::{box.id}")
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
        subtitle = describe(box)
        silent = st == "running" and box.id in self._silent
        if silent:
            subtitle += " · VPN not answering"
        if note := self._snapshot_note(box):
            subtitle += f"\n{note}"
        row.set_subtitle(subtitle)
        row.set_subtitle_lines(0)
        icon = row.state_icon  # type: ignore[attr-defined]
        for css in ("success", "warning", "dim-label"):
            icon.remove_css_class(css)
        if silent:
            icon.add_css_class("warning")
            icon.set_tooltip_text(
                "running; its VPN server is not answering. The tunnel comes back by "
                "itself once it does, and nothing leaves meanwhile"
            )
        elif st == "running":
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
        """Look before starting (a newer copy in the folder, the box in use
        elsewhere), then start."""
        if snapshot_ui is None:
            self._start_now(box, then)
            return

        def decide(check) -> None:
            if not check.needs_asking:
                self._start_now(box, then)
                return
            self._ask_before_start(box, check, then)

        worker.run(
            lambda: box_snapshots.before_start(box),
            decide,
            lambda _exc: self._start_now(box, then),
        )

    def _ask_before_start(self, box: Box, check, then) -> None:
        def newer() -> None:
            rel = check.relation
            if not (rel and rel.newer_elsewhere):
                self._start_now(box, then)
                return

            def restore_then_start() -> None:
                worker.run(
                    lambda: box_snapshots.restore(box.id, rel.head.id),
                    lambda restored: (self._snapshots_changed(), self._start_now(restored, then)),
                    lambda exc: self._alert(f"Could not restore {box.name}", str(exc)),
                )

            def keep_mine() -> None:
                worker.run(
                    lambda: box_snapshots.keep_mine(box, check),
                    lambda _m: (self._snapshots_changed(), self._start_now(box, then)),
                    lambda exc: self._alert("No snapshot taken", str(exc)),
                )

            snapshot_ui.ask_newer(
                self,
                box.name,
                rel,
                verb="start",
                on_restore=restore_then_start,
                on_as_is=lambda: self._start_now(box, then),
                on_keep_mine=keep_mine,
            )

        if check.in_use:
            from .start_prompt import in_use_dialog

            in_use_dialog(
                box.name, check.in_use, lambda r: newer() if r == "start" else None
            ).present(self)
        else:
            newer()

    def _start_now(self, box: Box, then=None) -> None:
        missing = setup.ready() if podman.available() else ["podman"]
        if missing:
            self._alert("Not set up yet", "Missing: " + "; ".join(missing))
            return
        self._busy.add(box.id)
        self.refresh(rebuild=False)
        if boxes.has_snapshot(box):
            self._toast(f"Starting {box.name} from its snapshot")
        elif boxes.rebuild_pending(box):
            self._toast(
                f"Starting {box.name} — it is rebuilt from its snapshot, give it some minutes"
            )
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

        def done(note) -> None:
            self._busy.discard(box.id)
            self._state[box.id] = "stopped"
            self.refresh()
            self._toast(f"{box.name} is stopped")
            if note:
                self._toast(note)
            self._poll_snapshots()

        def failed(exc: Exception) -> None:
            self._busy.discard(box.id)
            self.refresh()
            self._alert(f"Could not stop {box.name}", str(exc))

        worker.run(lambda: boxes.stop(box), done, failed)

    def _stop_all(self) -> None:
        def work():
            notes = []
            for box in store.list_boxes():
                if boxes.running(box) and (note := boxes.stop(box)):
                    notes.append(note)
            return notes

        def done(notes) -> None:
            self.refresh()
            self._toast("Every box is stopped")
            for note in notes:
                self._toast(note)

        worker.run(work, done)

    def _reap(self) -> None:
        def done(cleaned) -> None:
            self.refresh()
            self._toast(", ".join(cleaned) + " removed" if cleaned else "Nothing to tidy up")

        worker.run(boxes.reap, done, lambda exc: self._alert("Could not tidy up", str(exc)))

    # ------------------------------------------------------------- snapshots
    def _snapshot_note(self, box: Box) -> str:
        if snap is None:
            return ""
        bits = []
        if boxes.rebuild_pending(box):
            bits.append("restored: rebuilt at its next start")
        for device, since in self._in_use.get(box.id, []):
            bits.append(f"in use on {device} since {snap.when_text(since)}")
        rel = self._relations.get(box.id)
        if rel is not None and rel.state != "only_here":
            bits.append(rel.describe())
        return " · ".join(bits)

    def _poll_snapshots(self) -> None:
        if snap is None or self._snap_polling:
            return
        self._snap_polling = True

        def work():
            st = snap.status()
            if st.settings is None or not st.folder_present or not st.unlocked:
                return st, {}, {}, []
            opened = snap.folder()
            here = {b.id for b in store.list_boxes()}
            grouped: dict[str, list] = {}
            for meta in opened.metas():
                if meta.kind == box_snapshots.KIND:
                    grouped.setdefault(meta.item, []).append(meta)
            relations, in_use, away = {}, {}, []
            for bid in here:
                relations[bid] = snap.relation(
                    box_snapshots.KIND,
                    bid,
                    here=True,
                    metas=grouped.get(bid, []),
                    folder_id=opened.id,
                )
                if bid in grouped:
                    in_use[bid] = snap.in_use_elsewhere(box_snapshots.KIND, bid)
            for bid, metas in grouped.items():
                if bid not in here:
                    away.append((bid, metas[0].name, metas))
            away.sort(key=lambda a: a[1])
            return st, relations, in_use, away

        def done(result) -> None:
            self._snap_polling = False
            st, relations, in_use, away = result
            self.snap_banner.set_revealed(
                bool(st.settings and st.folder_present and not st.unlocked)
            )

            def key(rels):
                return {k: (v.state, v.head.id if v.head else None) for k, v in rels.items()}

            changed = (
                key(relations) != key(self._relations)
                or in_use != self._in_use
                or [a[:2] for a in away] != [a[:2] for a in self._away]
            )
            self._relations, self._in_use, self._away = relations, in_use, away
            if changed:
                self._show_away()
                self.refresh(rebuild=False)

        def failed(_exc: Exception) -> None:
            self._snap_polling = False

        worker.run(work, done, failed)

    def _show_away(self) -> None:
        for row in self._away_rows:
            self.away_group.remove(row)
        self._away_rows = []
        for bid, name, metas in self._away:
            head = metas[0]
            extra = head.extra
            distro = extra.get("distro", "")
            bits = [distros.DISTROS[distro].title if distro in distros.DISTROS else distro]
            if "packages" in extra:
                bits.append(f"{len(extra['packages'])} packages added")
            bits += [
                f"from {head.device}, {snap.when_text(head.created)}",
                snap.size_text(head.size),
            ]
            row = Adw.ActionRow(use_markup=False)
            row.set_title(name)
            row.set_subtitle(" · ".join(b for b in bits if b))
            restore = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
            restore.connect("clicked", self._on_restore_away, bid, name, head)
            row.add_suffix(restore)
            menu = Gio.Menu()
            menu.append("Snapshots…", f"win.snapshots::{bid}")
            menu.append("Delete from the snapshot folder", f"win.forget-snapshots::{bid}")
            more = Gtk.MenuButton(
                icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, menu_model=menu
            )
            more.add_css_class("flat")
            row.add_suffix(more)
            self.away_group.add(row)
            self._away_rows.append(row)
        self.away_group.set_visible(bool(self._away))
        self.stack.set_visible_child_name("list" if self._away or store.list_boxes() else "empty")

    def _on_restore_away(self, _button, bid: str, name: str, head) -> None:
        if exit_name := box_snapshots.missing_exit(head):
            self._alert(
                f"Restore {exit_name} in Kiwi Proxy first",
                f"{name} goes out through the exit {exit_name}, which is not on this device. "
                f"Kiwi Proxy restores exits from the same snapshot folder; then restore {name} here.",
            )
            return

        def done(box) -> None:
            self._toast(f"Restored {box.name}: it is rebuilt when you start it")
            self._snapshots_changed()

        worker.run(
            lambda: box_snapshots.restore(bid, head.id),
            done,
            lambda exc: self._alert(f"Could not restore {name}", str(exc)),
        )

    def _repair_on_start(self) -> None:
        from .. import settings

        if not settings.load().repair_on_start:
            return

        def done(notes) -> None:
            for note in notes[:3]:
                self._toast(note[0].upper() + note[1:])
            if notes:
                self.refresh()

        worker.run(boxes.repair, done, lambda _exc: None)

    def _catch_up(self) -> None:
        """At start: snapshot stopped boxes that changed since their last snapshot."""
        if snap is None or snap.load_settings() is None:
            return
        stopped = [b for b in store.list_boxes() if not boxes.running(b)]

        def work():
            return [n for b in stopped if (n := box_snapshots.after_stop(b))]

        def done(notes) -> None:
            for note in notes[:3]:
                self._toast(note)
            self._poll_snapshots()

        worker.run(work, done, lambda _exc: None)

    def _snapshots_changed(self) -> None:
        self._relations = {}
        self.refresh()

    def _general_page(self) -> Adw.PreferencesPage:
        from .. import settings

        s = settings.load()
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")

        boxes_group = Adw.PreferencesGroup(title="Boxes")
        repair = Adw.SwitchRow(title="Repair on start", active=s.repair_on_start)
        explain(
            repair,
            "Before anything starts, remove this app's containers an unclean shutdown left. "
            "A box's is committed first, so nothing installed in it is lost.",
            app=APP,
        )

        def on_repair(row, _param) -> None:
            cur = settings.load()
            cur.repair_on_start = row.get_active()
            settings.save(cur)

        repair.connect("notify::active", on_repair)
        boxes_group.add(repair)
        page.add(boxes_group)

        new = Adw.PreferencesGroup(title="New boxes")
        keys = list(distros.DISTROS)
        distro = Adw.ComboRow(
            title="Distribution",
            model=Gtk.StringList.new([distros.DISTROS[k].title for k in keys]),
        )
        distro.set_selected(keys.index(s.new_distro) if s.new_distro in keys else 0)

        def on_distro(row, _param) -> None:
            cur = settings.load()
            cur.new_distro = keys[row.get_selected()]
            settings.save(cur)

        distro.connect("notify::selected", on_distro)
        new.add(distro)
        from kiwi_proxy import exits

        found = sorted(exits.list_exits(), key=lambda e: e.name)
        choices = [("", "Ask every time")] + [(e.id, e.name) for e in found]
        exit_keys = [k for k, _l in choices]
        exit_row = Adw.ComboRow(
            title="Exit", model=Gtk.StringList.new([label for _k, label in choices])
        )
        exit_row.set_selected(exit_keys.index(s.new_exit) if s.new_exit in exit_keys else 0)

        def on_exit(row, _param) -> None:
            cur = settings.load()
            cur.new_exit = exit_keys[row.get_selected()]
            settings.save(cur)

        exit_row.connect("notify::selected", on_exit)
        new.add(exit_row)
        page.add(new)

        window = Adw.PreferencesGroup(title="Window")
        size = Adw.ActionRow(title="Size")

        def show() -> None:
            w, h, maxed = saved_geometry()
            size.set_subtitle("maximized" if maxed else f"{w} × {h}, kept when you close it")

        reset = Gtk.Button(label="Reset", valign=Gtk.Align.CENTER)

        def on_reset(*_a) -> None:
            with contextlib.suppress(OSError):
                (paths.config_dir() / "window.json").unlink()
            self.unmaximize()
            self.set_default_size(*DEFAULT_SIZE)
            show()

        reset.connect("clicked", on_reset)
        size.add_suffix(reset)
        show()
        window.add(size)
        page.add(window)
        return page

    def _open_preferences(self) -> None:
        from .maintenance import MaintenancePage

        general = self._general_page()
        jobs = [
            ("Set up environment", "images and DNS data", "Set up", "win.setup"),
            ("Check environment", "what is missing", "Check", "win.doctor"),
        ]
        if storage_ui is not None:
            jobs.append(("Check and repair", "Podman's storage, leftovers", "Open…", "win.storage"))
        jobs.append(("Tidy up", "containers nobody uses", "Tidy up", "win.reap"))
        upkeep = MaintenancePage(self, jobs)
        if snapshot_ui is None:
            dialog = Adw.PreferencesDialog(title="Preferences")
            dialog.add(general)
            dialog.add(upkeep)
            dialog.present(self)
            return
        page = snapshot_ui.SnapshotsPage(
            "after a box ran",
            on_changed=self._snapshots_changed,
            take_all=box_snapshots.take_all,
            take_all_text="every box",
        )
        snapshot_ui.preferences_dialog(general, page, upkeep).present(self)

    def _snapshot_all(self) -> None:
        if snap is None:
            return
        if not snap.load_settings():
            self._open_preferences()
            return
        if not snap.unlocked():
            snapshot_ui.ask_unlock(self, self._snapshot_all)
            return
        self._toast("Taking snapshots…")
        worker.run(
            box_snapshots.take_all,
            lambda summary: (self._toast(f"Snapshots taken: {summary}"), self._snapshots_changed()),
            lambda exc: self._alert("No snapshot taken", str(exc)),
        )

    def _act_snapshots(self, _action, param) -> None:
        if snap is None:
            return
        bid = param.get_string()
        if not snap.load_settings():
            self._open_preferences()
            return
        if not snap.unlocked():
            snapshot_ui.ask_unlock(self, lambda: self._act_snapshots(_action, param))
            return
        box = self._box(bid)
        here = box is not None
        name = box.name if here else next((a[1] for a in self._away if a[0] == bid), bid)
        take = (lambda: box_snapshots.take(store.load(bid))) if here else None
        snapshot_ui.HistoryDialog(
            box_snapshots.KIND,
            bid,
            name,
            here=here,
            take=take,
            restore=lambda sid: box_snapshots.restore(bid, sid),
            on_changed=self._snapshots_changed,
            toast=self._toast,
        ).present(self)

    def _act_forget_snapshots(self, _action, param) -> None:
        bid = param.get_string()
        name = next((a[1] for a in self._away if a[0] == bid), bid)
        dialog = Adw.AlertDialog(
            heading=f"Delete the snapshots of {name}?",
            body="Every snapshot of it is deleted from the snapshot folder, on every device "
            "that syncs the folder. This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "delete":
                return
            worker.run(
                lambda: snap.forget(box_snapshots.KIND, bid),
                lambda n: (
                    self._toast(f"Deleted {n} snapshot(s) of {name}"),
                    self._snapshots_changed(),
                ),
                lambda exc: self._alert("Could not delete", str(exc)),
            )

        dialog.connect("response", on_response)
        dialog.present(self)

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
