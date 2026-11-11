"""Dialogs: a new box, editing one, its details, and its applications."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402
from kiwi_proxy import exits  # noqa: E402

from .. import apps, boxes, distros, paths, store  # noqa: E402
from ..models import Box  # noqa: E402
from . import worker  # noqa: E402
from .help import APP, explain  # noqa: E402

PROXY_APP_ID = "eu.kiwinetwork.KiwiProxy"


def exit_line(ex) -> str:
    bits = [ex.endpoint.label]
    if ex.endpoint.lease or ex.endpoint.country:
        bits[0] += f" ({ex.endpoint.lease or ex.endpoint.country})"
    if ex.dns.mode == "remote":
        bits.append("remote DNS")
    if ex.last_exit and ex.last_exit.country:
        bits.append(ex.last_exit.country)
    return " · ".join(bits)


def _row(title: str, subtitle: str, *, copy: str | None = None, toast=None) -> Adw.ActionRow:
    row = Adw.ActionRow(use_markup=False, title=title, subtitle=subtitle or "—")
    row.add_css_class("property")
    if copy:
        button = Gtk.Button(
            icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy"
        )
        button.add_css_class("flat")

        def on_copy(*_a) -> None:
            Gdk.Display.get_default().get_clipboard().set(copy)
            if toast:
                toast(f"Copied {copy}")

        button.connect("clicked", on_copy)
        row.add_suffix(button)
    return row


def _dialog_header(primary: str, on_primary) -> tuple[Adw.HeaderBar, Gtk.Button, Gtk.Button]:
    header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
    cancel = Gtk.Button(label="Cancel")
    header.pack_start(cancel)
    button = Gtk.Button(label=primary)
    button.add_css_class("suggested-action")
    button.connect("clicked", on_primary)
    header.pack_end(button)
    return header, cancel, button


class ExitPicker:
    """Which kiwi-proxy exit a box leaves through. The exits are kiwi-proxy's:
    making or changing one is done there (the Kiwi Proxy app opens from here)."""

    def __init__(self, group: Adw.PreferencesGroup, selected: str | None = None) -> None:
        self._exits: list = []
        self.row = Adw.ComboRow(title="Exit")
        self.row.set_subtitle_lines(0)
        refresh = Gtk.Button(
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Read kiwi-proxy's exits again",
        )
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self.reload())
        self.row.add_suffix(refresh)
        group.add(self.row)
        self.proxy_row = Adw.ActionRow(
            title="Exits are defined in Kiwi Proxy",
            subtitle="Add or change one there; this list follows",
        )
        explain(
            self.proxy_row,
            "A SOCKS5 you were given, or a provider module: Tor, a VPN, 9proxy, Mysterium.",
            app="kiwi-proxy",
        )
        self.proxy_row.set_subtitle_lines(0)
        open_button = Gtk.Button(label="Open Kiwi Proxy", valign=Gtk.Align.CENTER)
        open_button.connect("clicked", self._on_open_kiwi_proxy)
        self.proxy_row.add_suffix(open_button)
        group.add(self.proxy_row)
        self.note = Adw.ActionRow(use_markup=False, visible=False)
        self.note.set_subtitle_lines(0)
        group.add(self.note)
        self.reload(selected)

    def reload(self, selected: str | None = None) -> None:
        current = selected or self.selected_id
        self._exits = exits.list_exits()
        labels = [f"{e.name} — {exit_line(e)}" for e in self._exits] or ["(no exits yet)"]
        self.row.set_model(Gtk.StringList.new(labels))
        self.row.set_sensitive(bool(self._exits))
        idx = next((i for i, e in enumerate(self._exits) if e.id == current), 0)
        self.row.set_selected(idx)
        if not self._exits:
            self.row.set_subtitle("Make one in Kiwi Proxy first")
        else:
            self.row.set_subtitle("")

    @property
    def selected_id(self) -> str | None:
        if not self._exits:
            return None
        idx = self.row.get_selected()
        return self._exits[idx].id if 0 <= idx < len(self._exits) else None

    def _on_open_kiwi_proxy(self, *_args) -> None:
        info = Gio.DesktopAppInfo.new(f"{PROXY_APP_ID}.desktop")
        try:
            if info is not None:
                info.launch([], None)
            else:
                import subprocess

                subprocess.Popen(["kiwi-proxy-gui"])  # noqa: S603, S607
        except Exception:  # noqa: BLE001 - say so, instead of a silent button
            self.note.set_title("Kiwi Proxy could not be opened")
            self.note.set_subtitle("kiwi install kiwi-proxy, or run kiwi-proxy-gui")
            self.note.set_visible(True)


class BoxEditor(Adw.Dialog):
    """New box, or edit one. `box` None makes one."""

    def __init__(self, box: Box | None, on_saved) -> None:
        super().__init__(title="New box" if box is None else f"Edit {box.name}")
        self.set_content_width(560)
        self.set_content_height(640)
        self._box = box
        self._on_saved = on_saved

        header, cancel, self.save_button = _dialog_header(
            "Create" if box is None else "Save", self._on_save
        )
        cancel.connect("clicked", lambda *_: self.close())

        page = Adw.PreferencesPage()

        group = Adw.PreferencesGroup(title="Box")
        self.name_row = Adw.EntryRow(title="Name", text=box.name if box else "")
        group.add(self.name_row)
        keys = list(distros.DISTROS)
        self.distro_row = Adw.ComboRow(title="Distribution")
        self.distro_row.set_model(Gtk.StringList.new([distros.DISTROS[k].title for k in keys]))
        from .. import settings

        prefer = settings.load()
        self.distro_row.set_selected(keys.index(box.distro if box else prefer.new_distro))
        self.distro_row.set_sensitive(box is None)
        self.distro_row.set_subtitle(
            "" if box is None else "Fixed once the box exists; make a new box for another"
        )
        self.distro_row.connect("notify::selected", lambda *_: self._distro_note())
        group.add(self.distro_row)
        self.distro_note = Adw.ActionRow(use_markup=False, visible=False)
        self.distro_note.set_subtitle_lines(0)
        group.add(self.distro_note)
        self.image_row = Adw.EntryRow(
            title="Image (optional; required for Custom image)",
            text=(box.image if box else ""),
        )
        self.image_row.set_sensitive(box is None)  # pinned once the box exists
        group.add(self.image_row)
        self.hostname_row = Adw.EntryRow(
            title="Hostname (optional)", text=(box.hostname or "") if box else ""
        )
        group.add(self.hostname_row)
        page.add(group)

        group = Adw.PreferencesGroup(title="Network", description="Its only route")
        explain(
            group,
            "The box has no route but this exit. Packages, updates, apps: everything leaves "
            "through it, nothing can go around it.",
            app=APP,
        )
        self.exit_picker = ExitPicker(group, box.exit if box else (prefer.new_exit or None))
        page.add(group)

        group = Adw.PreferencesGroup(title="Desktop", description="Its apps open here")
        explain(
            group,
            "The box gets the display, sound and the session bus, so its apps open on this "
            "desktop. That is network custody, not a sandbox from the desktop.",
            app=APP,
            anchor="what-it-is-not",
        )
        self.gpu_row = Adw.SwitchRow(
            title="Hardware rendering",
            subtitle="Pass the GPU (/dev/dri) in",
            active=box.gpu if box else True,
        )
        group.add(self.gpu_row)
        self.entry_row = Adw.SwitchRow(
            title="Show in the app grid",
            subtitle="A terminal into the box, as an app",
            active=box.desktop_entry if box else False,
        )
        group.add(self.entry_row)
        self.packages_row = Adw.EntryRow(
            title="Extra packages, space-separated",
            text=" ".join(box.packages) if box else "",
        )
        group.add(self.packages_row)
        self.shell_row = Adw.EntryRow(
            title="Shell (optional; bash when the box has it)",
            text=(box.shell or "") if box else "",
        )
        group.add(self.shell_row)
        page.add(group)

        if box is not None:
            self._add_travels(page, box)

        group = Adw.PreferencesGroup(
            title="Extra setup script", description="Optional, runs once as root"
        )
        explain(
            group,
            "Runs after the packages whenever the box is built: at its first start here, "
            "and on another device when it is rebuilt from a snapshot. For anything the "
            "lists above cannot express.",
            app=APP,
            anchor="how-a-box-is-built",
        )
        self.script_view = Gtk.TextView(
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=10,
            bottom_margin=10,
            left_margin=12,
            right_margin=12,
            height_request=90,
            accepts_tab=False,
        )
        self.script_view.add_css_class("card")
        self.script_view.update_property([Gtk.AccessibleProperty.LABEL], ["Extra setup script"])
        self.script_view.get_buffer().set_text(box.setup_script if box else "")
        group.add(self.script_view)
        page.add(group)

        self.error = Adw.Banner(revealed=False)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.error)
        view.set_content(Gtk.ScrolledWindow(child=page, vexpand=True))
        self.set_child(view)
        self._distro_note()

    def _add_travels(self, page: Adw.PreferencesPage, box: Box) -> None:
        """What the box's snapshots carry to another device (mock-up 14)."""
        self.travels_group = Adw.PreferencesGroup(
            title="What travels to another device",
            description="Recorded at every snapshot",
        )
        self._travels_help = explain(
            self.travels_group,
            "On another device the box is rebuilt from its base image with these, then its "
            "home is put back. The image itself stays on this device.",
            app=APP,
            anchor="how-a-box-is-built",
        )

        def tag() -> Gtk.Label:
            label = Gtk.Label(valign=Gtk.Align.CENTER)
            label.add_css_class("dim-label")
            label.add_css_class("numeric")
            return label

        self.travel_packages = Adw.ActionRow(title="Packages you added", use_markup=False)
        self.travel_files = Adw.ActionRow(
            title="System files you added or changed", use_markup=False
        )
        self.travel_home = Adw.ActionRow(title="Home", use_markup=False)
        self.travel_home.set_subtitle("everything in it except caches")
        self.travel_tags = []
        for row in (self.travel_packages, self.travel_files, self.travel_home):
            row.set_subtitle_lines(2)
            label = tag()
            row.add_suffix(label)
            self.travel_tags.append(label)
            self.travels_group.add(row)
        page.add(self.travels_group)
        self.travel_packages.set_subtitle("…")
        self.travel_files.set_subtitle("…")
        from .. import snapshots as box_snapshots

        worker.run(lambda: box_snapshots.travels(box), self._show_travels, lambda _e: None)

    def _show_travels(self, t) -> None:
        from .. import snapshots as box_snapshots

        def size(n: int) -> str:
            if n >= 1024**3:
                return f"{n / 1024**3:.1f} GB"
            return box_snapshots.snap.size_text(n) if box_snapshots.snap else f"{n} B"

        pkg_tag, files_tag, home_tag = self.travel_tags
        home_tag.set_label(size(t.home_size))
        stays = f" · the {size(t.image_size)} image stays here" if t.image_size else ""
        if t.state == "off":
            text = "Set up a snapshot folder in Preferences"
            waiting = "recorded at the first snapshot"
        elif t.state == "locked":
            text = "Snapshots are locked on this device"
            waiting = "unlock snapshots to see it"
        elif t.state == "none":
            text = "Recorded at every snapshot · none yet" + stays
            waiting = "recorded at the first snapshot"
        else:
            text = f"Recorded at every snapshot · last {t.when}" + stays
            waiting = ""
        self.travels_group.set_description(text)
        if waiting:
            self.travel_packages.set_subtitle(waiting)
            self.travel_files.set_subtitle(waiting)
            return
        if not t.recorded:
            note = t.notes[0] if t.notes else "not recorded for this box"
            self.travel_packages.set_subtitle(f"only the home and its declared packages: {note}")
            self.travel_files.set_subtitle("none recorded")
            return
        names = t.packages
        shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
        self.travel_packages.set_subtitle(shown or "none")
        pkg_tag.set_label(str(len(names)))
        self.travel_files.set_subtitle(t.files_summary or "none")
        files_tag.set_label(size(t.files_size) if t.files else "")

    def _distro_note(self) -> None:
        key = list(distros.DISTROS)[self.distro_row.get_selected()]
        d = distros.DISTROS[key]
        self.distro_note.set_title(d.image or "type the image below (registry/name:tag)")
        self.distro_note.set_subtitle(d.notes or "")
        self.distro_note.set_visible(True)

    def _fail(self, text: str) -> None:
        self.error.set_title(text)
        self.error.set_revealed(True)
        self.save_button.set_sensitive(True)

    def _on_save(self, *_args) -> None:
        self.error.set_revealed(False)
        self.save_button.set_sensitive(False)
        name = self.name_row.get_text().strip()
        exit_id = self.exit_picker.selected_id
        if not exit_id:
            self._fail("Pick an exit — make one in Kiwi Proxy if there is none")
            return
        packages = self.packages_row.get_text().split()
        hostname = self.hostname_row.get_text().strip() or None
        gpu = self.gpu_row.get_active()
        entry = self.entry_row.get_active()
        key = list(distros.DISTROS)[self.distro_row.get_selected()]
        image = self.image_row.get_text().strip() or None
        shell = self.shell_row.get_text().strip() or None
        buf = self.script_view.get_buffer()
        script = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        script = script.rstrip() + "\n" if script.strip() else ""

        def work():
            from .. import desktop
            from ..cli import describe

            if self._box is None:
                box = store.create(
                    name,
                    distro=key,
                    exit_id=exit_id,
                    hostname=hostname,
                    packages=packages,
                    gpu=gpu,
                    image=image,
                    shell=shell,
                )
            else:
                box = self._box
                if name != box.name:
                    store.rename(box, name)
                if exit_id != box.exit and boxes.running(box):
                    boxes.stop(box)
                box.exit = exit_id
                box.hostname = hostname
                box.packages = packages
                box.gpu = gpu
                box.shell = shell
            box.desktop_entry = entry
            box.setup_script = script
            store.save(box)
            desktop.sync_entry(box, describe(box))
            from .. import snapshots as box_snapshots

            box_snapshots.changed(box)
            return box

        def done(box) -> None:
            self.close()
            self._on_saved(box)

        worker.run(work, done, lambda exc: self._fail(str(exc)))


class BoxDetails(Adw.Dialog):
    def __init__(self, box: Box, toast) -> None:
        super().__init__(title=box.name)
        self.set_content_width(560)
        self.set_content_height(520)
        d = distros.get(box.distro)
        try:
            ex = store.exit_of(box)
            exit_text = f"{ex.name} — {exit_line(ex)}"
        except store.StoreError:
            ex = None
            exit_text = f"{box.exit[:8]} (missing in kiwi-proxy)"
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Box")
        group.add(_row("Distribution", f"{d.title} ({box.image})"))
        group.add(_row("Hostname", box.host))
        group.add(
            _row("Home", str(paths.box_home(box.id)), copy=str(paths.box_home(box.id)), toast=toast)
        )
        group.add(
            _row("Container", paths.box_name(box.id), copy=paths.box_name(box.id), toast=toast)
        )
        group.add(_row("Extra packages", " ".join(box.packages)))
        group.add(_row("Exported apps", ", ".join(box.exported)))
        page.add(group)
        group = Adw.PreferencesGroup(title="Network")
        group.add(_row("Exit", exit_text))
        if ex:
            group.add(
                _row(
                    "Gateway",
                    paths.gateway_name(ex.id),
                    copy=paths.gateway_name(ex.id),
                    toast=toast,
                )
            )
            group.add(_row("Tunnel", paths.tunnel_name(ex.id)))
            group.add(
                _row(
                    "DNS",
                    "the gateway's resolver, ad-blocking"
                    if ex.dns.mode == "resolver"
                    else "resolved beyond the exit (remote)",
                )
            )
        page.add(group)
        group = Adw.PreferencesGroup(title="Command line")
        group.add(
            _row(
                "Enter",
                f"kiwi-custodia enter {box.name}",
                copy=f"kiwi-custodia enter {box.name}",
                toast=toast,
            )
        )
        group.add(_row("Run", f"kiwi-custodia run {box.name} -- COMMAND"))
        page.add(group)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(Gtk.ScrolledWindow(child=page, vexpand=True))
        self.set_child(view)


class AppsDialog(Adw.Dialog):
    """The applications a running box has, to open or put in the app grid."""

    def __init__(self, box: Box, toast, alert) -> None:
        super().__init__(title=f"Apps in {box.name}")
        self.set_content_width(600)
        self.set_content_height(640)
        self._box = box
        self._toast = toast
        self._alert = alert
        self._rows: list[Adw.ActionRow] = []

        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Read again")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_end(refresh)
        self.group = Adw.PreferencesGroup(title="Installed applications")
        explain(
            self.group,
            "What the box's packages put in its app directories. Open one here, or put it "
            "in this desktop's app grid; it runs in the box, through the exit.",
            app=APP,
        )
        page = Adw.PreferencesPage()
        page.add(self.group)
        self.status = Adw.StatusPage(icon_name="view-app-grid-symbolic", title="Reading…")
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=page, vexpand=True), "list")
        self.stack.add_named(self.status, "status")
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        self.set_child(view)
        self.reload()

    def reload(self) -> None:
        self.stack.set_visible_child_name("status")
        self.status.set_title("Reading…")
        self.status.set_description("")

        def done(found) -> None:
            for row in self._rows:
                self.group.remove(row)
            self._rows.clear()
            box = store.load(self._box.id)
            self._box = box
            if not found:
                self.status.set_title("No desktop applications yet")
                self.status.set_description("Install some with the box's package manager")
                return
            for app in found:
                row = Adw.ActionRow(
                    title=app.name, subtitle=app.comment or app.id, use_markup=False
                )
                run = Gtk.Button(
                    icon_name="media-playback-start-symbolic",
                    valign=Gtk.Align.CENTER,
                    tooltip_text="Open",
                )
                run.add_css_class("flat")
                run.connect("clicked", self._on_run, app)
                row.add_suffix(run)
                exported = app.id in box.exported
                btn = Gtk.Button(
                    label="Remove from app grid" if exported else "Add to app grid",
                    valign=Gtk.Align.CENTER,
                )
                btn.connect("clicked", self._on_toggle_export, app, exported)
                row.add_suffix(btn)
                self.group.add(row)
                self._rows.append(row)
            self.stack.set_visible_child_name("list")

        def failed(exc: Exception) -> None:
            self.status.set_title("Could not read the box's applications")
            self.status.set_description(str(exc))

        worker.run(lambda: apps.list_apps(self._box), done, failed)

    def _on_run(self, _button, app) -> None:
        import shlex
        import subprocess

        command = shlex.split(apps._FIELD_CODES.sub("", app.exec))
        args = boxes.exec_args(self._box, command, tty=False)
        try:
            subprocess.Popen(  # noqa: S603
                ["podman", *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._toast(f"Opening {app.name}")
        except OSError as exc:
            self._alert(f"Could not open {app.name}", str(exc))

    def _on_toggle_export(self, button, app, exported: bool) -> None:
        button.set_sensitive(False)

        def work():
            if exported:
                apps.unexport(self._box, app.id)
            else:
                apps.export(self._box, app.id)

        def done(_r) -> None:
            self._toast(
                f"{app.name} removed from the app grid"
                if exported
                else f"{app.name} is in the app grid"
            )
            self.reload()

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            self._alert("Could not change the app grid", str(exc))

        worker.run(work, done, failed)


class LogsDialog(Adw.Dialog):
    def __init__(self, title: str, text: str) -> None:
        super().__init__(title=title)
        self.set_content_width(720)
        self.set_content_height(520)
        buf = Gtk.TextBuffer(text=text or "(nothing logged)")
        tv = Gtk.TextView(
            buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR
        )
        tv.set_left_margin(12)
        tv.set_right_margin(12)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(Gtk.ScrolledWindow(child=tv, vexpand=True))
        self.set_child(view)
        GLib.idle_add(lambda: tv.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0) and False)
