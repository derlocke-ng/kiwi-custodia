# Development

This page is for people who work on kiwi-custodia itself: how to run it from a
checkout, which tests exist and where they run, and how a release is made.

## Run it from a checkout

kiwi-custodia imports kiwi-proxy for everything on the network side, so it
needs a kiwi-proxy checkout next to it:

```bash
git clone https://github.com/derlocke-ng/kiwi-proxy
git clone https://github.com/derlocke-ng/kiwi-custodia
cd kiwi-custodia
make setup              # a .venv with pydantic, pytest and ruff
make run ARGS=list      # the command line, the same as `kiwi-custodia list`
make gui                # the app
make image              # the tunnel image, kiwi-custodia/tunnel:latest
```

`make image` builds the tunnel image without the label that records which
files it was built from, so `kiwi-custodia doctor` calls it `stale` and
`kiwi-custodia setup` builds it again with the label.

`make setup` creates the virtual environment with the system's site packages,
because PyGObject for the app comes from the distribution. The Makefile puts
`src`, the checkout itself and `../kiwi-proxy/src` on the Python path.

## Tests

| Command | What it runs |
|---|---|
| `make test` | The unit tests in `tests/unit`. They need kiwi-proxy (see above) but no Podman and no network. |
| `make lint` | `ruff check` and `ruff format --check` over the sources, the tests and the container files. |
| `make fmt` | Formats the same files and applies ruff's fixes. |

The unit tests replace Podman with a stand-in (`tests/unit/conftest.py`). The
commands kiwi-custodia would run, such as a box's `podman run` and the tunnel
container's specification, are built apart from running them so that the
tests can check them. What happens in a real network namespace needs a
machine with Podman. The test of the window's size is skipped when PyGObject
is not installed.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request.

| Job | Where | What |
|---|---|---|
| `test` | GitHub Actions, Ubuntu 24.04 | The linter, `bash -n` on the tunnel's entrypoint, `kc-init.sh` and `install.sh`, and the unit tests, against kiwi-proxy's `main` branch |
| `tunnel-image` | GitHub Actions, `ubuntu-latest` with Podman | The tunnel image, built without a cache, which checks the pinned tun2socks download and its checksum; then `tun2socks --version` from inside it |

No job starts a box.

## Releases

A release is a signed tag. `kiwi` installs an app's newest version tag, so the
tag is the release. A maintainer makes and signs it; CI holds no key:

```bash
git tag -s v1.2.0 -m v1.2.0
git push origin v1.2.0
```

For a pushed `v*` tag, `.github/workflows/release.yml` checks that the tag is
annotated, signed by a key in `.github/allowed_signers`, equal to `VERSION` in
`kiwi.manifest` and newer than every other release. It also checks that
`pyproject.toml` and `src/kiwi_custodia/__init__.py` carry the same version.
It then publishes the GitHub release with the matching section of
`CHANGELOG.md` as its notes.

The docs in this folder reach
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-custodia/) with
the next release tag, so run the docs checker before you tag:

```bash
python3 .claude/skills/kiwi-docs/scripts/check-docs.py .
```
