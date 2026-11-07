"""The lifecycle against the fake podman: what a box is started with, what shares
what, and what goes when."""

from __future__ import annotations

import pytest
from conftest import make_exit
from kiwi_proxy import gateway

from kiwi_custodia import boxes, paths, store, tunnel


def _flag(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


# ------------------------------------------------------------------ run args
def test_run_args_join_the_gateway_as_the_user(a_box, an_exit, a_session):
    args = boxes.run_args(a_box, an_exit, "kf-gw-x", "/rt/resolv.conf", a_session)
    assert args[:2] == ["run", "--replace"]
    assert _flag(args, "--network") == ["container:kf-gw-x"]
    assert _flag(args, "--userns") == ["keep-id"]
    assert _flag(args, "--user") == ["root:root"]  # the init; exec goes in as the user
    assert "--init" in args
    assert _flag(args, "--hostname") == ["work"]
    assert _flag(args, "--security-opt") == ["label=disable"]
    assert set(_flag(args, "--cap-drop")) == {"NET_RAW", "NET_ADMIN"}
    assert "--privileged" not in args
    assert args[-2:] == [a_box.image, boxes.INIT_SCRIPT]


def test_run_args_mount_home_resolver_init_and_the_session(a_box, an_exit, a_session):
    args = boxes.run_args(a_box, an_exit, "kf-gw-x", "/rt/resolv.conf", a_session)
    vols = _flag(args, "--volume")
    assert f"{paths.box_home(a_box.id)}:/home/tester:rw" in vols
    assert "/rt/resolv.conf:/etc/resolv.conf:ro" in vols
    assert any(v.endswith(f":{boxes.INIT_SCRIPT}:ro") and "kc-init.sh" in v for v in vols)
    assert any(v.endswith("/wayland-0:rw") for v in vols)
    assert any("/bus:" in v for v in vols)
    env = dict(e.split("=", 1) for e in _flag(args, "--env"))
    assert env["KC_USER"] == "tester"
    assert env["KC_FAMILY"] == "dnf"
    assert env["KC_SOCKS"] == gateway.FORWARDER
    assert env["KC_EXIT_NAME"] == "work"
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["DBUS_SESSION_BUS_ADDRESS"].startswith("unix:path=/run/user/")
    assert "HOME" not in env  # the init runs as root; exec sets it for the user
    labels = dict(lab.split("=", 1) for lab in _flag(args, "--label"))
    assert labels["app"] == "kiwi-custodia"
    assert labels[paths.ROLE_LABEL] == "box"
    assert labels[paths.EXIT_LABEL] == an_exit.id
    # kiwi-proxy commits the box to this image before it removes it with the gateway
    assert labels[paths.SNAPSHOT_LABEL] == paths.box_image(a_box.id)
    assert "--device" not in args  # gpu=False session


def test_run_args_gpu(a_box, an_exit, monkeypatch, tmp_path):
    from kiwi_custodia import session

    monkeypatch.setattr(session.Path, "is_dir", lambda self: str(self) == "/dev/dri")
    s = session.current(gpu=True)
    args = boxes.run_args(a_box, an_exit, "gw", "/r", s)
    assert _flag(args, "--device") == ["/dev/dri"]


def test_exec_args(a_box, a_session):
    args = boxes.exec_args(a_box, None, sess=a_session)
    assert args[:3] == ["exec", "--interactive", "--tty"]
    assert _flag(args, "--user") == [f"{a_session.uid}:{a_session.gid}"]
    assert _flag(args, "--workdir") == ["/home/tester"]
    assert args[-2:] == [paths.box_name(a_box.id), boxes.SHELL]
    args = boxes.exec_args(a_box, ["echo", "hello world"], tty=False, sess=a_session)
    assert "--tty" not in args
    assert args[-3:] == [boxes.SHELL, "-c", "echo 'hello world'"]
    args = boxes.exec_args(a_box, ["id"], user="root", sess=a_session)
    assert _flag(args, "--env")[0] == "HOME=/root" and _flag(args, "--workdir") == ["/root"]


# ----------------------------------------------------------------- lifecycle
def test_up_brings_gateway_tunnel_and_box(a_box, an_exit, fake_podman):
    up = boxes.up(a_box)
    gw, tun, box = (
        paths.gateway_name(an_exit.id),
        paths.tunnel_name(an_exit.id),
        paths.box_name(a_box.id),
    )
    assert (up.gateway, up.tunnel, up.container) == (gw, tun, box)
    assert up.first_start
    assert fake_podman.containers[tun]["network"] == f"container:{gw}"
    assert fake_podman.containers[box]["network"] == f"container:{gw}"
    assert fake_podman.containers[tun]["env"]["KC_DNS_MODE"] == "resolver"
    assert fake_podman.containers[tun]["env"]["KC_ENDPOINT_IP"] == "10.64.0.1"
    assert fake_podman.pulled == [a_box.image]
    assert boxes.state(a_box) == "running"


def test_up_is_idempotent(a_box, fake_podman):
    boxes.up(a_box)
    again = boxes.up(a_box)
    assert again.reused
    assert len(fake_podman.runs) == 1


def test_tunnel_spec(an_exit):
    s = tunnel.spec(an_exit, "kf-gw-x", "10.64.0.1")
    assert s.network == "container:kf-gw-x"
    assert s.userns is None
    assert s.devices == ["/dev/net/tun"]
    assert set(s.cap_add) == {"NET_ADMIN", "NET_BIND_SERVICE"}
    assert "NET_RAW" not in s.cap_add
    assert s.labels[paths.ROLE_LABEL] == "tunnel"
    assert tunnel.resolver_for(an_exit) == gateway.RESOLVER


def test_remote_dns_exit_uses_the_stub(fake_podman):
    ex = make_exit("tor", dns_mode="remote")
    box = store.create("anon", distro="debian", exit_id=ex.id)
    boxes.up(box)
    tun = fake_podman.containers[paths.tunnel_name(ex.id)]
    assert tun["env"]["KC_DNS_MODE"] == "remote"
    assert tunnel.resolver_for(ex) == tunnel.DNS_STUB
    resolv = paths.tunnel_runtime_dir(ex.id) / "resolv.conf"
    assert f"nameserver {tunnel.DNS_STUB}" in resolv.read_text()


def test_stop_takes_tunnel_and_gateway_when_last(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    boxes.stop(a_box)
    assert paths.box_name(a_box.id) not in fake_podman.containers
    assert paths.tunnel_name(an_exit.id) not in fake_podman.containers
    assert paths.gateway_name(an_exit.id) not in fake_podman.containers
    assert boxes.state(a_box) == "stopped"


def test_two_boxes_share_exit_tunnel_and_gateway(a_box, an_exit, fake_podman):
    other = store.create("other", distro="ubuntu", exit_id=an_exit.id)
    boxes.up(a_box)
    boxes.up(other)
    tun, gw = paths.tunnel_name(an_exit.id), paths.gateway_name(an_exit.id)
    assert len([n for n in fake_podman.containers if n.startswith("kc-tun-")]) == 1
    boxes.stop(a_box)
    assert tun in fake_podman.containers and gw in fake_podman.containers
    assert boxes.running(other)
    boxes.stop(other)
    assert tun not in fake_podman.containers and gw not in fake_podman.containers


def test_stop_leaves_a_gateway_someone_else_uses(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    gw = paths.gateway_name(an_exit.id)
    # kiwi-fox's browser joined the same exit's gateway.
    fake_podman.containers["kf-br-browser"] = {
        "running": True,
        "labels": {},
        "env": {},
        "network": f"container:{gw}",
        "image": "x",
    }
    boxes.stop(a_box)
    assert paths.tunnel_name(an_exit.id) not in fake_podman.containers
    assert gw in fake_podman.containers


def test_held_gateway_stays(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    gateway.hold(an_exit.id)
    boxes.stop(a_box)
    assert paths.gateway_name(an_exit.id) in fake_podman.containers


def test_missing_tunnel_image_is_said(a_box, an_exit, fake_podman):
    fake_podman.images.discard(paths.TUNNEL_IMAGE)
    with pytest.raises(boxes.BoxError, match="kiwi-custodia setup"):
        boxes.up(a_box)
    assert paths.gateway_name(an_exit.id) not in fake_podman.containers


def test_state_gateway_down(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    fake_podman.rm(paths.tunnel_name(an_exit.id))
    assert boxes.state(a_box) == "gateway-down"


def test_check_reads_the_exit_from_inside(a_box, fake_podman):
    import subprocess

    boxes.up(a_box)
    fake_podman.exec_result = subprocess.CompletedProcess(
        [], 0, stdout='{"ip": "198.51.100.7", "country_iso": "SE", "city": "Malmo"}', stderr=""
    )
    info = boxes.check(a_box)
    assert (info.ip, info.country) == ("198.51.100.7", "SE")
    assert fake_podman.execs[-1][0] == "exec"
    assert "curl" in fake_podman.execs[-1][-1]


def test_reap(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    # A box whose record is gone, and a tunnel with no box running on its exit.
    fake_podman.containers["kc-box-ghost"] = {
        "running": True,
        "labels": {paths.ROLE_LABEL: "box", paths.BOX_LABEL: "ghost"},
        "env": {},
        "network": "x",
        "image": "x",
    }
    fake_podman.rm(paths.box_name(a_box.id))
    cleaned = boxes.reap()
    assert "kc-box-ghost" in cleaned
    assert paths.tunnel_name(an_exit.id) in cleaned
    assert paths.gateway_name(an_exit.id) not in fake_podman.containers


def test_delete_stops_and_removes(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    boxes.delete(a_box)
    assert store.list_boxes() == []
    assert paths.box_name(a_box.id) not in fake_podman.containers
    assert paths.gateway_name(an_exit.id) not in fake_podman.containers


# ------------------------------------------------------------- snapshots
def test_stop_keeps_the_box_as_a_snapshot_and_up_starts_from_it(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    name = paths.box_name(a_box.id)
    assert fake_podman.runs[-1][-2] == a_box.image  # the base image, first time
    boxes.stop(a_box)
    assert fake_podman.commits and fake_podman.commits[-1][-1] == paths.box_image(a_box.id)
    assert fake_podman.commits[-1][-2] == name
    assert boxes.has_snapshot(a_box)
    up = boxes.up(a_box)
    assert fake_podman.runs[-1][-2] == paths.box_image(a_box.id)  # the snapshot, from then on
    assert any("snapshot" in n for n in up.notes)


def test_delete_and_reset_forget_the_snapshot(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    boxes.stop(a_box)
    assert boxes.has_snapshot(a_box)
    boxes.reset(a_box)
    assert not boxes.has_snapshot(a_box)
    assert paths.box_home(a_box.id).exists()  # the home stays
    boxes.up(a_box)
    boxes.delete(a_box)
    assert not boxes.has_snapshot(a_box)
    assert (
        not fake_podman.commits[-1:] or fake_podman.commits[-1][-2] != "deleted"
    )  # no commit on delete


def test_run_args_carry_the_shell_and_an_auto_family_for_a_custom_image(an_exit, a_session):
    box = store.create(
        "lab", distro="custom", exit_id=an_exit.id, image="quay.io/x/y:1", shell="/usr/bin/zsh"
    )
    args = boxes.run_args(box, an_exit, "kf-gw-x", "/rt/resolv.conf", a_session)
    env = dict(e.split("=", 1) for e in _flag(args, "--env"))
    assert env["KC_FAMILY"] == "auto" and env["KC_SHELL"] == "/usr/bin/zsh"
    assert args[-2] == "quay.io/x/y:1"
    assert (
        boxes.run_args(box, an_exit, "kf-gw-x", "/rt/r", a_session, image="snap:1")[-2] == "snap:1"
    )


def test_a_custom_distro_needs_an_image(an_exit):
    with pytest.raises(store.StoreError, match="needs an image"):
        store.create("lab", distro="custom", exit_id=an_exit.id)


def test_proxy_env_only_on_a_remote_dns_exit(a_box, an_exit, a_session):
    args = boxes.run_args(a_box, an_exit, "kf-gw-x", "/rt/resolv.conf", a_session)
    env = dict(e.split("=", 1) for e in _flag(args, "--env"))
    assert env["KC_PROXY_ENV"] == "0"  # a resolver exit: the route is the exit, no ALL_PROXY
    tor = make_exit("tor", dns_mode="remote")
    args = boxes.run_args(a_box, tor, "kf-gw-x", "/rt/resolv.conf", a_session)
    env = dict(e.split("=", 1) for e in _flag(args, "--env"))
    assert env["KC_PROXY_ENV"] == "1"  # Tor: a .onion needs socks5h by name


def test_a_commit_that_leaves_no_image_keeps_the_container(
    a_box, an_exit, fake_podman, monkeypatch
):
    boxes.up(a_box)
    name = paths.box_name(a_box.id)
    real_run = fake_podman._run

    def run(args, **k):  # podman says fine but writes nothing
        if args[0] == "commit":
            import subprocess

            return subprocess.CompletedProcess(args, 0, stdout="sha256:x", stderr="")
        return real_run(args, **k)

    monkeypatch.setattr(boxes.podman, "_run", run)
    with pytest.raises(boxes.BoxError, match="is not there"):
        boxes.stop(a_box)
    assert name in fake_podman.containers  # nothing was lost


def test_up_keeps_a_box_a_reboot_left_behind(a_box, an_exit, fake_podman):
    boxes.up(a_box)
    name = paths.box_name(a_box.id)
    fake_podman.containers[name]["running"] = False  # the host rebooted
    boxes.up(a_box)
    assert fake_podman.commits, "the exited container was committed before --replace"
    assert fake_podman.containers[name]["image"] == paths.box_image(a_box.id)
