"""kiwi-custodia command line. The GUI is a layer over this; the CLI is the truth."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kiwi_proxy import exits, gateway, podman

from . import __version__, apps, boxes, desktop, distros, paths, recipe, setup, store, tunnel
from . import snapshots as box_snapshots
from .models import Box


def _p(*args: object) -> None:
    print(*args)


def _fail(msg: str) -> int:
    print(f"kiwi-custodia: {msg}", file=sys.stderr)
    return 1


def _box(ref: str) -> Box:
    return store.resolve_ref(ref)


def describe(box: Box) -> str:
    """One line: the distro and the exit, for listings and desktop entries."""
    d = distros.get(box.distro)
    try:
        ex = store.exit_of(box)
        where = f"{ex.name} ({ex.endpoint.label})"
    except store.StoreError:
        where = f"exit {box.exit[:8]} (missing)"
    return f"{d.title}, through {where}"


def box_dict(box: Box) -> dict:
    d = box.model_dump(mode="json")
    d["container"] = paths.box_name(box.id)
    d["state"] = boxes.state(box) if podman.available() else "unknown"
    try:
        ex = store.exit_of(box)
        d["exit_name"] = ex.name
        d["gateway"] = paths.gateway_name(ex.id)
    except store.StoreError:
        d["exit_name"] = None
        d["gateway"] = None
    return d


# ------------------------------------------------------------------ commands
def cmd_setup(a: argparse.Namespace) -> int:
    try:
        for step in setup.run(progress=_p):
            _p(f"  {step}")
    except setup.SetupError as exc:
        return _fail(str(exc))
    return 0


def cmd_distros(a: argparse.Namespace) -> int:
    if a.json:
        _p(json.dumps([d.__dict__ for d in distros.DISTROS.values()], indent=2))
        return 0
    for d in distros.DISTROS.values():
        star = " (default)" if d.key == distros.DEFAULT else ""
        note = f"  — {d.notes}" if d.notes else ""
        _p(f"{d.key:15} {d.title:22} {d.image or '(--image)'}{star}{note}")
    return 0


def cmd_new(a: argparse.Namespace) -> int:
    try:
        ex = exits.resolve_ref(a.exit)
    except exits.ExitError as exc:
        return _fail(f"{exc} (kiwi-proxy list shows them; kiwi-proxy add makes one)")
    try:
        box = store.create(
            a.name,
            distro=a.distro,
            exit_id=ex.id,
            hostname=a.hostname,
            packages=a.package or [],
            gpu=not a.no_gpu,
            image=a.image,
            shell=a.shell,
        )
    except store.StoreError as exc:
        return _fail(str(exc))
    if a.desktop_entry:
        box.desktop_entry = True
        store.save(box)
        desktop.sync_entry(box, describe(box))
    _p(f"created {box.name} ({box.id[:8]}): {describe(box)}")
    if a.no_start:
        _p(f"next:  kiwi-custodia enter {box.name}")
        return 0
    return _up_and_report(box, enter=a.enter)


def _up_and_report(
    box: Box, *, enter: bool = False, as_is: bool = False, restore: bool = False
) -> int:
    missing = setup.ready()
    if missing:
        return _fail("not set up yet: " + "; ".join(missing))
    if box_snapshots.available() and not as_is:
        looked = _look_before_start(box, restore=restore)
        if looked is None:
            return 1
        box = looked
    if boxes.has_snapshot(box):
        _p(f"bringing {box.name} up from its snapshot")
    elif boxes.rebuild_pending(box):
        _p(
            f"bringing {box.name} up — it is rebuilt from its snapshot: the baseline, then "
            "the packages and files that were added to it; give it some minutes"
        )
    else:
        _p(f"bringing {box.name} up — the first start installs the baseline, give it a minute")
    try:
        up = boxes.up(box)
    except boxes.BoxError as exc:
        return _fail(str(exc))
    for note in up.notes:
        _p(f"  note: {note}")
    _p(
        f"{box.name} is up: {up.container} in {up.gateway}, default route through {up.tunnel}"
        + (" (already was)" if up.reused else "")
    )
    if enter:
        return cmd_enter(argparse.Namespace(box=box.id))
    _p(f"enter:  kiwi-custodia enter {box.name}")
    return 0


def cmd_up(a: argparse.Namespace) -> int:
    try:
        return _up_and_report(_box(a.box), as_is=a.as_is, restore=a.restore)
    except store.StoreError as exc:
        return _fail(str(exc))


def cmd_enter(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not boxes.running(box):
        code = _up_and_report(box)
        if code:
            return code
    args = boxes.exec_args(box, None, tty=sys.stdin.isatty())
    os.execvp("podman", ["podman", *args])  # noqa: S606 - replaces this process on purpose


def cmd_run(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not a.command:
        return _fail("run needs a command: kiwi-custodia run BOX -- COMMAND…")
    if not boxes.running(box):
        if a.quiet:
            if box_snapshots.available():
                check = box_snapshots.before_start(box)
                if check.needs_asking and (
                    os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
                ):
                    from .ui import start_prompt

                    choice = start_prompt.ask(box.name, check)
                    if choice == "cancel":
                        return 1
                    if choice == "restore" and check.relation and check.relation.head:
                        box = box_snapshots.restore(box.id, check.relation.head.id)
                    elif choice == "mine":
                        box_snapshots.keep_mine(box, check)
            try:
                boxes.up(box)
            except boxes.BoxError as exc:
                return _fail(str(exc))
        else:
            code = _up_and_report(box)
            if code:
                return code
    args = boxes.exec_args(box, a.command, tty=sys.stdin.isatty())
    os.execvp("podman", ["podman", *args])  # noqa: S606


def cmd_stop(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    try:
        note = boxes.stop(box)
    except boxes.BoxError as exc:
        return _fail(str(exc))
    kept = " — kept as a snapshot, the next start has everything" if boxes.has_snapshot(box) else ""
    _p(f"stopped {box.name}{kept}")
    if note:
        _p(f"  {note}")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    found = store.list_boxes()
    if a.json:
        _p(json.dumps([box_dict(b) for b in found], indent=2))
        return 0
    if not found:
        _p("no boxes yet: kiwi-custodia new NAME --exit EXIT")
        return 0
    for b in found:
        st = boxes.state(b) if podman.available() else "-"
        _p(f"{b.name:20} {st:13} {describe(b)}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    d = box_dict(box)
    if a.json:
        _p(json.dumps(d, indent=2))
        return 0
    for key in (
        "name",
        "id",
        "state",
        "distro",
        "image",
        "exit_name",
        "exit",
        "gateway",
        "container",
        "hostname",
        "gpu",
        "packages",
        "exported",
        "desktop_entry",
        "created",
    ):
        _p(f"{key:14} {d.get(key)}")
    _p(f"{'home':14} {paths.box_home(box.id)}")
    if box.setup_script.strip():
        _p(f"{'setup script':14} {len(box.setup_script.splitlines())} lines")
    return 0


def cmd_set(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    changed = []
    was_running = boxes.running(box)
    if a.name:
        try:
            store.rename(box, a.name)
        except store.StoreError as exc:
            return _fail(str(exc))
        changed.append(f"name {a.name}")
    if a.exit:
        try:
            ex = exits.resolve_ref(a.exit)
        except exits.ExitError as exc:
            return _fail(str(exc))
        if ex.id != box.exit:
            if was_running:
                boxes.stop(box)  # committed to its snapshot first: nothing installed is lost
                was_running = False
                changed.append(
                    "stopped — a box cannot change its exit while up; it starts again on the "
                    "new one with everything that was installed in it"
                )
            box.exit = ex.id
            changed.append(f"exit {ex.name}")
    if a.hostname is not None:
        box.hostname = a.hostname or None
        changed.append(f"hostname {box.host}")
    if a.shell is not None:
        box.shell = a.shell or None
        changed.append(f"shell {box.shell or 'default (bash)'}")
    if a.gpu is not None:
        box.gpu = a.gpu
        changed.append(f"gpu {'on' if a.gpu else 'off'}")
    for pkg in a.package or []:
        if pkg not in box.packages:
            box.packages.append(pkg)
            changed.append(f"+{pkg}")
    if a.desktop_entry is not None:
        box.desktop_entry = a.desktop_entry
        changed.append("in the app grid" if a.desktop_entry else "not in the app grid")
    if a.setup_script is not None:
        if a.setup_script == "":
            box.setup_script = ""
            changed.append("no setup script")
        else:
            try:
                text = (
                    sys.stdin.read()
                    if a.setup_script == "-"
                    else Path(a.setup_script).expanduser().read_text()
                )
            except OSError as exc:
                return _fail(f"cannot read {a.setup_script}: {exc}")
            box.setup_script = text.rstrip() + "\n" if text.strip() else ""
            changed.append(f"setup script ({len(box.setup_script.splitlines())} lines)")
    store.save(box)
    desktop.sync_entry(box, describe(box))
    if not changed:
        _p("nothing to change")
        return 0
    box_snapshots.changed(box)
    _p(f"{box.name}: " + ", ".join(changed))
    if (
        a.hostname is not None or a.gpu is not None or a.package or a.shell is not None
    ) and was_running:
        _p("applies at the next start: kiwi-custodia stop && kiwi-custodia up")
    if a.setup_script:
        _p(
            "the setup script runs once when the box is built: on another device when it "
            "is rebuilt from a snapshot, here after kiwi-custodia reset"
        )
    if a.package and boxes.running(box):
        _p(
            "note: added packages are installed when the box is next created; "
            "install them now with sudo inside the box"
        )
    return 0


def cmd_rm(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not a.yes:
        home = paths.box_home(box.id)
        _p(f"this deletes {box.name} and its home at {home}")
        answer = input("delete? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            _p("kept")
            return 0
    boxes.delete(box)
    _p(f"deleted {box.name}")
    return 0


def cmd_reset(a: argparse.Namespace) -> int:
    """Back to the base image: the container and the snapshot go, the home stays."""
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not a.yes:
        _p(f"this throws away everything installed in {box.name} (its home stays)")
        answer = input("reset? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            _p("kept")
            return 0
    boxes.reset(box)
    _p(f"{box.name} reset: the next start installs the baseline again")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not boxes.running(box):
        code = _up_and_report(box)
        if code:
            return code
    try:
        info = boxes.check(box)
    except boxes.BoxError as exc:
        return _fail(str(exc))
    if a.json:
        _p(json.dumps(info.model_dump(mode="json"), indent=2))
        return 0
    place = ", ".join(p for p in (info.city, info.country) if p)
    _p(
        f"{box.name} leaves as {info.ip}"
        + (f" ({place})" if place else "")
        + (f", {info.asn}" if info.asn else "")
    )
    return 0


def cmd_apps(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if not boxes.running(box):
        code = _up_and_report(box)
        if code:
            return code
    try:
        found = apps.list_apps(box, include_hidden=a.all)
    except apps.AppError as exc:
        return _fail(str(exc))
    if a.json:
        _p(json.dumps([x.model_dump(mode="json") for x in found], indent=2))
        return 0
    if not found:
        _p(f"no desktop applications in {box.name} yet; install some with its package manager")
        return 0
    for app in found:
        mark = "*" if app.id in box.exported else " "
        _p(f"{mark} {app.id:40} {app.name}")
    _p("* exported to the app grid")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    try:
        box = _box(a.box)
    except store.StoreError as exc:
        return _fail(str(exc))
    if a.rm:
        apps.unexport(box, a.app)
        _p(f"removed {a.app} ({box.name}) from the app grid")
        return 0
    if not boxes.running(box):
        code = _up_and_report(box)
        if code:
            return code
    try:
        path = apps.export(box, a.app)
    except apps.AppError as exc:
        return _fail(str(exc))
    _p(f"exported {a.app}: {path}")
    return 0


def cmd_desktop(a: argparse.Namespace) -> int:
    with_entry, removed = desktop.sync_all(store.list_boxes(), describe)
    _p(f"entries: {', '.join(with_entry) or 'none'}")
    if removed:
        _p(f"removed stale: {', '.join(removed)}")
    return 0


def cmd_reap(a: argparse.Namespace) -> int:
    cleaned = boxes.reap()
    _p("cleaned: " + (", ".join(cleaned) if cleaned else "nothing"))
    return 0


def cmd_ps(a: argparse.Namespace) -> int:
    rows = []
    for row in boxes.ours():
        lab = row.get("Labels") or {}
        rows.append(
            {
                "name": (row.get("Names") or [""])[0],
                "role": lab.get(paths.ROLE_LABEL),
                "state": row.get("State"),
                "box": lab.get(paths.BOX_LABEL),
                "exit": lab.get(paths.EXIT_LABEL),
            }
        )
    if a.json:
        _p(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        _p(f"{r['name']:28} {r['role'] or '':8} {r['state'] or '':10} exit {str(r['exit'])[:8]}")
    if not rows:
        _p("nothing running")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    ok = True
    _p(f"podman: {'ok, ' + podman.version() if podman.available() else 'MISSING'}")
    ok &= podman.available()
    if podman.available():
        st = setup.image_state()
        _p(f"tunnel image: {st}")
        ok &= st != "missing"
        from kiwi_proxy import setup as proxy_setup

        gst = proxy_setup.image_state(proxy_setup.paths.GATEWAY_IMAGE, "gateway")
        _p(f"kiwi-proxy gateway image: {gst}")
        ok &= gst != "missing"
    from . import session

    s = session.current()
    _p(
        f"display: {'Wayland ' + s.env['WAYLAND_DISPLAY'] if 'WAYLAND_DISPLAY' in s.env else 'none'}"
        + (f", X11 {s.env['DISPLAY']}" if "DISPLAY" in s.env else "")
    )
    _p(f"session bus: {'yes' if 'DBUS_SESSION_BUS_ADDRESS' in s.env else 'no'}")
    _p(f"gpu: {'/dev/dri' if s.devices else 'none'}")
    for note in s.notes:
        _p(f"  note: {note}")
    term = desktop.terminal_command(["true"])
    _p(f"terminal: {term[0] if term else 'none found'}")
    _p(f"exits: {len(exits.list_exits())} in kiwi-proxy")
    _p(
        f"tunnel sidecars up: {[t for t in (paths.tunnel_name(e.id) for e in exits.list_exits()) if podman.available() and podman.is_running(t)]}"
    )
    return 0 if ok else 1


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="kiwi-custodia",
        description="Distro containers whose every byte leaves through a kiwi-proxy exit.",
    )
    ap.add_argument("--version", action="version", version=f"kiwi-custodia {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="build the tunnel image and set kiwi-proxy up")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("distros", help="the distributions a box can be")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_distros)

    p = sub.add_parser("new", help="create a box")
    p.add_argument("name")
    p.add_argument("--exit", required=True, help="the kiwi-proxy exit it leaves through")
    p.add_argument(
        "--distro",
        default=distros.DEFAULT,
        choices=list(distros.DISTROS),
        help="a preset (kiwi-custodia distros lists them), or custom with --image",
    )
    p.add_argument("--image", help="an image instead of the preset's; required for --distro custom")
    p.add_argument("--shell", help="the login shell in the box (default: bash when it has it)")
    p.add_argument("--hostname")
    p.add_argument("--package", action="append", help="installed by the first start (repeatable)")
    p.add_argument("--no-gpu", action="store_true", help="do not pass /dev/dri in")
    p.add_argument("--desktop-entry", action="store_true", help="a terminal entry in the app grid")
    p.add_argument("--no-start", action="store_true", help="create only")
    p.add_argument("--enter", action="store_true", help="open a shell in it once it is up")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("up", help="bring a box up without entering it")
    p.add_argument("box")
    p.add_argument(
        "--as-is",
        action="store_true",
        help="start without asking, even when the snapshot folder holds a newer copy",
    )
    p.add_argument(
        "--restore",
        action="store_true",
        help="when the snapshot folder holds a newer copy, restore it first",
    )
    p.set_defaults(fn=cmd_up)

    p = sub.add_parser("enter", help="a shell in the box (brings it up)")
    p.add_argument("box")
    p.set_defaults(fn=cmd_enter)

    p = sub.add_parser("run", help="a command in the box (brings it up)")
    p.add_argument("box")
    p.add_argument("--quiet", action="store_true", help="no bring-up chatter (desktop entries)")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("stop", help="stop a box; its exit goes unless still in use")
    p.add_argument("box")
    p.set_defaults(fn=cmd_stop)

    p = sub.add_parser("list", help="every box and its state")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="one box")
    p.add_argument("box")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("set", help="change a box")
    p.add_argument("box")
    p.add_argument("--name")
    p.add_argument("--exit", help="another kiwi-proxy exit")
    p.add_argument("--hostname", help="'' for the box's name")
    p.add_argument("--shell", help="the login shell in the box; '' for the default (bash)")
    p.add_argument("--package", action="append")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--gpu", dest="gpu", action="store_true", default=None)
    g.add_argument("--no-gpu", dest="gpu", action="store_false")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--desktop-entry", dest="desktop_entry", action="store_true", default=None)
    g.add_argument("--no-desktop-entry", dest="desktop_entry", action="store_false")
    p.add_argument(
        "--setup-script",
        metavar="FILE",
        help="a shell script run once as root after the packages when the box is built "
        "('-' reads it from stdin, '' removes it)",
    )
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("rm", help="delete a box and its home")
    p.add_argument("box")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(fn=cmd_rm)

    p = sub.add_parser(
        "reset", help="back to the base image: what was installed goes, the home stays"
    )
    p.add_argument("box")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("check", help="what the world sees from inside the box")
    p.add_argument("box")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("apps", help="desktop applications installed in the box")
    p.add_argument("box")
    p.add_argument("--all", action="store_true", help="hidden ones too")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_apps)

    p = sub.add_parser("export", help="put one of the box's apps into the app grid")
    p.add_argument("box")
    p.add_argument("app", help="its desktop file id (kiwi-custodia apps BOX)")
    p.add_argument("--rm", action="store_true", help="take it out again")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("desktop", help="rewrite every box's app-grid entry")
    p.add_argument("action", choices=["sync"])
    p.set_defaults(fn=cmd_desktop)

    p = sub.add_parser("ps", help="kiwi-custodia's containers")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ps)

    p = sub.add_parser("reap", help="tidy containers nobody uses")
    p.set_defaults(fn=cmd_reap)

    p = sub.add_parser("doctor", help="is this machine ready?")
    p.set_defaults(fn=cmd_doctor)

    sn = sub.add_parser("snapshot", help="encrypted snapshots of boxes, for your other devices")
    ssub = sn.add_subparsers(dest="snapshot_cmd", required=True)
    for name, text in (
        ("setup", "choose the snapshot folder (kiwi-proxy's, shared by every kiwi app)"),
        ("status", "folder, device, locked or not"),
        ("unlock", "enter the passphrase on this device"),
        ("lock", "forget the passphrase on this device"),
        ("set", "change how snapshots are taken"),
    ):
        ssub.add_parser(name, help=text, add_help=False)
    ssub.add_parser("list", help="the boxes in the folder, and how they relate to here")
    q = ssub.add_parser("now", help="snapshot boxes now")
    q.add_argument("refs", nargs="*", metavar="BOX", help="default: every box")
    q = ssub.add_parser("history", help="the snapshots of one box")
    q.add_argument("ref", metavar="BOX")
    q = ssub.add_parser(
        "restore", help="restore a box from the folder; it is rebuilt at its next start"
    )
    q.add_argument("ref", metavar="BOX")
    q.add_argument("--id", help="which snapshot (see history); default the newest")
    q.add_argument("--yes", action="store_true", help="replace this device's copy without asking")
    q = ssub.add_parser("forget", help="delete every snapshot of a box from the folder")
    q.add_argument("ref", metavar="BOX")
    q.add_argument("--yes", action="store_true")
    q = ssub.add_parser("show", help="what the newest snapshot of a box carries")
    q.add_argument("ref", metavar="BOX")
    sn.set_defaults(fn=cmd_snapshot)
    return ap


PROXY_SNAPSHOT_COMMANDS = ("setup", "status", "unlock", "lock", "set")


def _ask_tty(question: str, choices: dict[str, str], default: str) -> str:
    while True:
        answer = input(question).strip().lower() or default
        if answer in choices:
            return choices[answer]


def _look_before_start(box: Box, *, restore: bool = False) -> Box | None:
    """Before a box starts: a newer copy in the folder, or the box in use on
    another device. Returns the box to start (restored, perhaps), or None."""
    check = box_snapshots.before_start(box)
    if not check.needs_asking:
        return box
    snap = box_snapshots.snap
    rel = check.relation
    if restore and rel and rel.newer_elsewhere:
        choice = "restore"
    elif sys.stdin.isatty():
        for device, since in check.in_use or []:
            if (
                _ask_tty(
                    f"{box.name} is in use on {device} since {snap.when_text(since)} (as far as the "
                    "snapshot folder knows). Start anyway? [y/N] ",
                    {"y": "go", "n": "cancel"},
                    "n",
                )
                == "cancel"
            ):
                _p("not started")
                return None
        choice = "asis"
        if rel and rel.newer_elsewhere:
            head = rel.head
            when = f"{head.device}, {snap.when_text(head.created)}"
            if rel.state == "diverged":
                _p(f"{box.name} changed here and on {head.device} ({when}) since they parted.")
                choice = _ask_tty(
                    "  [u] use the snapshot (this copy is kept as a snapshot)\n"
                    "  [k] keep this device's (it becomes the newest)\n  [c] cancel\nChoice [c]: ",
                    {"u": "restore", "k": "mine", "c": "cancel"},
                    "c",
                )
            else:
                _p(f"A newer snapshot of {box.name} exists: from {when}.")
                choice = _ask_tty(
                    "  [r] restore it and start (this copy is kept as a snapshot)\n"
                    "  [s] start as it is\n  [c] cancel\nChoice [r]: ",
                    {"r": "restore", "s": "asis", "c": "cancel"},
                    "r",
                )
    else:
        if rel and rel.newer_elsewhere:
            _p(f"note: {rel.describe()} — kiwi-custodia snapshot restore {box.name}")
        for device, _since in check.in_use or []:
            _p(f"note: the snapshot folder says {box.name} is in use on {device}")
        choice = "asis"
    if choice == "cancel":
        _p("not started")
        return None
    if choice == "restore" and rel and rel.head:
        box = box_snapshots.restore(box.id, rel.head.id)
        _p(f"restored {box.name} from {rel.head.device}")
    elif choice == "mine":
        box_snapshots.keep_mine(box, check)
        _p(f"this device's {box.name} is the newest snapshot now")
    return box


def _box_ref(ref: str) -> tuple[str, str]:
    try:
        b = store.resolve_ref(ref)
        return b.id, b.name
    except store.StoreError:
        return box_snapshots.find_in_folder(ref)


def cmd_snapshot(a: argparse.Namespace) -> int:
    if not box_snapshots.available():
        return _fail(box_snapshots.NEEDS)
    snap = box_snapshots.snap
    cmd = a.snapshot_cmd
    kind = box_snapshots.KIND
    if cmd == "list":
        opened = snap.folder()
        here = {b.id: b for b in store.list_boxes()}
        grouped = snap.catalog((kind,))
        ids = set(here) | {item for _k, item in grouped}
        rows = []
        for bid in ids:
            metas = grouped.get((kind, bid), [])
            name = here[bid].name if bid in here else metas[0].name
            rel = snap.relation(kind, bid, here=bid in here, metas=metas, folder_id=opened.id)
            newest = (
                f"{metas[0].device}, {snap.when_text(metas[0].created)} · {len(metas)} kept"
                if metas
                else ""
            )
            rows.append((name, rel.describe(), newest))
        if not rows:
            _p("no boxes")
            return 0
        rows.sort()
        width = max(len(r[0]) for r in rows)
        state_width = max(len(r[1]) for r in rows)
        for name, state, newest in rows:
            _p(f"{name:{width}}  {state:{state_width}}  {newest}".rstrip())
        return 0
    if cmd == "now":
        targets = [_box(r) for r in a.refs] if a.refs else store.list_boxes()
        for box in targets:
            _p(f"{box.name}: reading what was added to it…")
            meta = box_snapshots.take(box)
            extra = meta.extra
            what = ""
            if "packages" in extra:
                what = f" — {len(extra['packages'])} packages, {extra.get('files', 0)} system files"
            _p(f"{box.name}: snapshot taken ({snap.size_text(meta.size)}){what}")
        return 0
    if cmd == "history":
        bid, name = _box_ref(a.ref)
        metas = snap.history(kind, bid)
        if not metas:
            _p(f"no snapshot of {name} yet")
            return 0
        for meta in metas:
            aside = " · kept before a restore" if meta.aside else ""
            _p(
                f"{meta.id}  {snap.when_text(meta.created):20} {meta.device:12} {snap.size_text(meta.size):>8}{aside}"
            )
        return 0
    if cmd == "show":
        bid, name = _box_ref(a.ref)
        metas = snap.history(kind, bid)
        if not metas:
            _p(f"no snapshot of {name} yet")
            return 0
        extra = metas[0].extra
        _p(
            f"{name}, from {metas[0].device}, {snap.when_text(metas[0].created)} ({snap.size_text(metas[0].size)})"
        )
        _p(f"  packages added  {', '.join(extra.get('packages', [])) or 'none'}")
        if extra.get("local"):
            _p(f"  from files      {', '.join(extra['local'])} (travel as their files)")
        _p(
            f"  system files    {extra.get('files', 0)} ({snap.size_text(extra.get('files_size', 0))})"
        )
        for note in extra.get("notes", []):
            _p(f"  note            {note}")
        return 0
    if cmd == "restore":
        bid, name = _box_ref(a.ref)
        here = store.exists(bid)
        if a.id:
            sid = a.id
        else:
            rel = snap.relation(kind, bid, here=here)
            if rel.head is None:
                return _fail(f"no snapshot of {name} in the folder")
            if here and rel.state == "same":
                _p(f"{name} is the newest snapshot already")
                return 0
            sid = rel.head.id
        if here and not a.yes:
            if not sys.stdin.isatty():
                return _fail(f"{name} is on this device; restoring replaces it — pass --yes")
            if input(
                f"Replace this device's {name} with snapshot {sid[:8]}? It is rebuilt at its next start. [y/N] "
            ).strip().lower() not in ("y", "yes"):
                _p("nothing changed")
                return 1
        box = box_snapshots.restore(bid, sid)
        _p(
            f"restored {box.name}: its home is here; its packages and files come back at its next start"
        )
        if here:
            _p(f"  what was here is kept as a snapshot: kiwi-custodia snapshot history {box.name}")
        _p(f"  start it: kiwi-custodia up {box.name}")
        return 0
    if cmd == "forget":
        bid, name = _box_ref(a.ref)
        if not a.yes:
            return _fail(f"this deletes every snapshot of {name} from the folder — pass --yes")
        _p(f"deleted {snap.forget(kind, bid)} snapshot(s) of {name}")
        return 0
    return _fail(f"unknown snapshot command {cmd}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["snapshot"] and argv[1:2] and argv[1] in PROXY_SNAPSHOT_COMMANDS:
        if not box_snapshots.available():
            return _fail(box_snapshots.NEEDS)
        from kiwi_proxy import cli as proxy_cli

        return proxy_cli.main(argv)
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd == "run" and a.command and a.command[0] == "--":
        a.command = a.command[1:]
    paths.ensure_tree()
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except (
        store.StoreError,
        boxes.BoxError,
        tunnel.TunnelError,
        apps.AppError,
        recipe.RecipeError,
    ) as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - the snapshot library's errors, worded for people
        if box_snapshots.available() and isinstance(exc, box_snapshots.snap.SnapshotError):
            return _fail(str(exc))
        raise
    except gateway.GatewayError as exc:
        return _fail(str(exc))
