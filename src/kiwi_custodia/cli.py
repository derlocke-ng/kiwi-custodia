"""kiwi-custodia command line. The GUI is a layer over this; the CLI is the truth."""

from __future__ import annotations

import argparse
import json
import os
import sys

from kiwi_proxy import exits, gateway, podman

from . import __version__, apps, boxes, desktop, distros, paths, setup, store, tunnel
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


def _up_and_report(box: Box, *, enter: bool = False) -> int:
    missing = setup.ready()
    if missing:
        return _fail("not set up yet: " + "; ".join(missing))
    if boxes.has_snapshot(box):
        _p(f"bringing {box.name} up from its snapshot")
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
        return _up_and_report(_box(a.box))
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
        boxes.stop(box)
    except boxes.BoxError as exc:
        return _fail(str(exc))
    kept = " — kept as a snapshot, the next start has everything" if boxes.has_snapshot(box) else ""
    _p(f"stopped {box.name}{kept}")
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
    store.save(box)
    desktop.sync_entry(box, describe(box))
    if not changed:
        _p("nothing to change")
        return 0
    _p(f"{box.name}: " + ", ".join(changed))
    if (
        a.hostname is not None or a.gpu is not None or a.package or a.shell is not None
    ) and was_running:
        _p("applies at the next start: kiwi-custodia stop && kiwi-custodia up")
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
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd == "run" and a.command and a.command[0] == "--":
        a.command = a.command[1:]
    paths.ensure_tree()
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except (store.StoreError, boxes.BoxError, tunnel.TunnelError, apps.AppError) as exc:
        return _fail(str(exc))
    except gateway.GatewayError as exc:
        return _fail(str(exc))
