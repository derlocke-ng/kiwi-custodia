"""The command line, end to end against the fake podman."""

from __future__ import annotations

import json

import pytest

from kiwi_custodia import cli, paths, store


def run(capsys, *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_new_list_show(an_exit, fake_podman, capsys):
    code, out = run(capsys, "new", "work", "--exit", "work", "--distro", "debian", "--no-start")
    assert code == 0 and "created work" in out
    code, out = run(capsys, "list")
    assert code == 0 and "work" in out and "Debian" in out
    code, out = run(capsys, "show", "work", "--json")
    d = json.loads(out)
    assert d["distro"] == "debian" and d["exit_name"] == "work" and d["state"] == "stopped"
    assert d["container"].startswith("kc-box-")


def test_new_unknown_exit(capsys):
    code, out = run(capsys, "new", "work", "--exit", "nope", "--no-start")
    assert code == 1 and "no exit matches" in out


def test_new_starts_by_default(an_exit, fake_podman, capsys):
    code, out = run(capsys, "new", "work", "--exit", "work")
    assert code == 0 and "is up" in out
    assert len(fake_podman.runs) == 1


def test_up_stop(a_box, an_exit, fake_podman, capsys):
    code, out = run(capsys, "up", "work")
    assert code == 0 and "default route through" in out
    code, out = run(capsys, "list")
    assert "running" in out
    code, out = run(capsys, "stop", "work")
    assert code == 0 and "stopped work" in out
    assert paths.gateway_name(an_exit.id) not in fake_podman.containers


def test_up_without_setup(a_box, fake_podman, capsys):
    fake_podman.images.discard(paths.TUNNEL_IMAGE)
    code, out = run(capsys, "up", "work")
    assert code == 1 and "not set up yet" in out


def test_enter_execs_podman(a_box, fake_podman, capsys, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.os, "execvp", lambda file, args: called.update(file=file, args=args))
    code, out = run(capsys, "enter", "work")
    assert called["file"] == "podman"
    assert called["args"][:3] == ["podman", "exec", "--interactive"]
    assert called["args"][-1].endswith("kc-shell")


def test_run_passes_the_command(a_box, fake_podman, capsys, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.os, "execvp", lambda file, args: called.update(args=args))
    run(capsys, "run", "work", "--", "ls", "-la", "my dir")
    assert called["args"][-2:] == ["-c", "ls -la 'my dir'"]


def test_run_needs_a_command(a_box, capsys):
    code, out = run(capsys, "run", "work")
    assert code == 1 and "needs a command" in out


def test_set(a_box, an_exit, fake_podman, capsys):
    from conftest import make_exit

    other = make_exit("other")
    run(capsys, "up", "work")
    code, out = run(capsys, "set", "work", "--exit", "other", "--package", "vim", "--desktop-entry")
    assert code == 0
    assert "stopped" in out and "exit other" in out and "+vim" in out
    box = store.load(a_box.id)
    assert box.exit == other.id and box.packages == ["vim"] and box.desktop_entry
    assert (paths.applications_dir() / f"{cli.desktop.ENTRY_PREFIX}{a_box.id[:8]}.desktop").exists()
    code, out = run(capsys, "set", "work", "--name", "renamed")
    assert code == 0 and store.load(a_box.id).name == "renamed"


def test_rm_yes(a_box, fake_podman, capsys):
    code, out = run(capsys, "rm", "work", "--yes")
    assert code == 0 and "deleted work" in out
    assert store.list_boxes() == []


def test_distros(capsys):
    code, out = run(capsys, "distros")
    assert code == 0 and "fedora" in out and "(default)" in out
    code, out = run(capsys, "distros", "--json")
    assert any(d["key"] == "arch" for d in json.loads(out))


def test_ps_and_reap(a_box, fake_podman, capsys):
    run(capsys, "up", "work")
    code, out = run(capsys, "ps", "--json")
    rows = json.loads(out)
    assert {r["role"] for r in rows} == {"box", "tunnel", "gateway"}
    code, out = run(capsys, "reap")
    assert code == 0 and "nothing" in out


def test_doctor(fake_podman, capsys):
    code, out = run(capsys, "doctor")
    assert code == 0 and "tunnel image:" in out


@pytest.mark.parametrize("args", [["list"], ["distros"], ["desktop", "sync"]])
def test_commands_without_podman(args, capsys, monkeypatch):
    from kiwi_proxy import podman

    monkeypatch.setattr(podman, "available", lambda: False)
    code, _ = run(capsys, *args)
    assert code == 0
