"""No test reads or writes the real stores, and none needs podman: a fake keeps
a table of containers so tests can say who runs, who joined whom, and what was
started with which arguments."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The sibling kiwi-proxy checkout supplies kiwi_proxy (install.sh puts the
# installed copy on the path the same way).
for candidate in (ROOT / "src", ROOT.parent / "kiwi-proxy" / "src", ROOT / "kiwi-proxy" / "src"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from kiwi_proxy import dns, exits, gateway, podman  # noqa: E402
from kiwi_proxy import paths as proxy_paths  # noqa: E402
from kiwi_proxy.models import Endpoint, Exit  # noqa: E402

from kiwi_custodia import paths, session, store, tunnel  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    monkeypatch.setenv("KIWI_PROXY_SECRETS", "file")
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    proxy_paths.ensure_tree()
    paths.ensure_tree()


def make_exit(name="work", dns_mode="resolver", module=None) -> Exit:
    from kiwi_proxy.models import DnsConfig

    ex = Exit(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" if name == "work" else f"{name}-" + "0" * 30,
        name=name,
        created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        endpoint=Endpoint(host="10.64.0.1", port=1080, module=module),
        dns=DnsConfig(mode=dns_mode),
    )
    exits.save(ex)
    return ex


@pytest.fixture
def an_exit():
    return make_exit()


@pytest.fixture
def a_box(an_exit):
    return store.create("work", distro="fedora", exit_id=an_exit.id)


class FakePodman:
    """Enough of podman for the lifecycle: containers with state, labels, env
    and the network they joined; images; the run/exec/logs calls."""

    def __init__(self, monkeypatch):
        self.containers: dict[str, dict] = {}
        self.images: set[str] = {paths.TUNNEL_IMAGE, proxy_paths.GATEWAY_IMAGE}
        self.pulled: list[str] = []
        self.runs: list[list[str]] = []  # every `podman run` argv
        self.execs: list[list[str]] = []
        self.commits: list[list[str]] = []
        self.exec_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        m = monkeypatch
        m.setattr(podman, "available", lambda: True)
        m.setattr(podman, "version", lambda: "podman 5.0 (fake)")
        m.setattr(podman, "is_running", lambda n: self.containers.get(n, {}).get("running", False))
        m.setattr(podman, "exists", lambda n: n in self.containers)
        m.setattr(podman, "labels", lambda n: dict(self.containers.get(n, {}).get("labels", {})))
        m.setattr(podman, "dependents", self.dependents)
        m.setattr(podman, "rm", self.rm)
        m.setattr(podman, "start", self.start)
        m.setattr(podman, "logs", self.logs)
        m.setattr(podman, "secret_set", lambda n, v: None)
        m.setattr(podman, "secret_rm", lambda n: None)
        m.setattr(podman, "ps", self.ps)
        m.setattr(podman, "image_exists", lambda i: i in self.images)
        m.setattr(podman, "pull", lambda i: (self.pulled.append(i), self.images.add(i)))
        m.setattr(
            podman, "container_env", lambda n, k: self.containers.get(n, {}).get("env", {}).get(k)
        )
        m.setattr(podman, "container_ip", lambda n, net: None)
        m.setattr(podman, "exec_", self.exec_)
        m.setattr(podman, "_run", self._run)
        # The gateway's plan would resolve and probe the upstream.
        m.setattr(
            gateway,
            "plan",
            lambda ex, password=None, measure=True: gateway.EndpointPlan(
                "10.64.0.1", 1080, "pasta", None, []
            ),
        )
        m.setattr(dns, "load_stamps", lambda: {"google": "sdns://x"})
        m.setattr(dns, "merged_blocklist", lambda names: Path("/tmp/blocked"))
        m.setattr(
            tunnel,
            "wait_ready",
            lambda name, timeout=20.0: self.containers.get(name, {}).get("running", False),
        )

    # -- containers
    def start(self, spec, **k):
        self.containers[spec.name] = {
            "running": True,
            "labels": dict(spec.labels),
            "env": dict(spec.env),
            "network": spec.network,
            "image": spec.image,
            "log": "",
        }
        return spec.name

    def rm(self, name, **k):
        self.containers.pop(name, None)

    def logs(self, name, tail=50):
        c = self.containers.get(name)
        if not c:
            return ""
        if c["labels"].get(proxy_paths.ROLE_LABEL) == "gateway":
            return gateway.READY_MARK
        if c["labels"].get(paths.ROLE_LABEL) == "tunnel":
            return tunnel.READY_MARK + " kc0"
        return c.get("log", "")

    def dependents(self, name):
        return [n for n, c in self.containers.items() if c.get("network") == f"container:{name}"]

    def ps(self, all_=True, *, labels=None):
        rows = []
        for n, c in self.containers.items():
            if not all_ and not c["running"]:
                continue
            lab = c["labels"]
            if labels and any(lab.get(k) != v for k, v in labels.items()):
                continue
            if proxy_paths.ROLE_LABEL not in lab:
                continue
            rows.append(
                {"Names": [n], "Labels": lab, "State": "running" if c["running"] else "exited"}
            )
        return rows

    def exec_(self, name, args, timeout=60):
        self.execs.append([name, *args])
        return self.exec_result

    def _run(self, args, *, check=True, timeout=120):
        """`podman run …` for a box, `podman ps --format json` for ours(), and
        `podman cp` / `exec` as no-ops."""
        if args[0] == "run":
            self.runs.append(args)
            name = args[args.index("--name") + 1]
            labels = {}
            env = {}
            for i, a in enumerate(args):
                if a == "--label":
                    k, _, v = args[i + 1].partition("=")
                    labels[k] = v
                if a == "--env":
                    k, _, v = args[i + 1].partition("=")
                    env[k] = v
            net = args[args.index("--network") + 1]
            self.containers[name] = {
                "running": True,
                "labels": labels,
                "env": env,
                "network": net,
                "image": args[-2],
                "log": "kc-init: first start: installing\nkc-init: ready — tester",
            }
            return subprocess.CompletedProcess(args, 0, stdout=name, stderr="")
        if args[0] == "ps":
            import json

            rows = [
                {
                    "Names": [n],
                    "Labels": c["labels"],
                    "State": "running" if c["running"] else "exited",
                }
                for n, c in self.containers.items()
                if paths.ROLE_LABEL in c["labels"]
            ]
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rows), stderr="")
        if args[0] == "exec":
            self.execs.append(args)
            return self.exec_result
        if args[0] == "cp":
            Path(args[2]).write_bytes(b"icon")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "commit":  # the box's snapshot
            self.commits.append(args)
            self.images.add(args[-1])
            return subprocess.CompletedProcess(args, 0, stdout="sha256:fake", stderr="")
        if args[0] == "rmi":
            self.images.discard(args[-1])
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


@pytest.fixture
def fake_podman(monkeypatch):
    return FakePodman(monkeypatch)


@pytest.fixture
def a_session(monkeypatch, tmp_path):
    """A desktop session with a Wayland socket, a bus and PipeWire."""
    rt = tmp_path / "xdg_runtime_dir"
    rt.mkdir(exist_ok=True)
    for name in ("wayland-0", "bus", "pipewire-0"):
        (rt / name).touch()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    return session.current(gpu=False)
