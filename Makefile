.PHONY: run gui image test lint fmt setup
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
# A sibling kiwi-proxy checkout supplies the kiwi_proxy package in development.
export PYTHONPATH := src:.:../kiwi-proxy/src

setup:
	python3 -m venv --system-site-packages .venv
	.venv/bin/python -m pip install -q --upgrade pip
	.venv/bin/python -m pip install -q pydantic pytest ruff

run:
	$(PY) -m kiwi_custodia $(ARGS)

gui:
	$(PY) -m kiwi_custodia.ui

image:
	podman build -t kiwi-custodia/tunnel:latest -f containers/tunnel/Containerfile containers/tunnel

test:
	$(PY) -m pytest tests/unit -q

lint:
	.venv/bin/ruff check src tests containers
	.venv/bin/ruff format --check src tests containers

fmt:
	.venv/bin/ruff format src tests containers
	.venv/bin/ruff check --fix src tests containers
