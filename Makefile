UV ?= uv
export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
PY = .venv/bin/python

.PHONY: setup demo seed reset test check format evaluate smoke fixtures verify build distribution-check
setup:
	$(UV) sync --frozen

demo: setup
	$(PY) -m noticeforge.cli demo

seed:
	$(PY) -m noticeforge.cli seed

reset:
	$(PY) -m noticeforge.cli reset

test:
	$(PY) -m pytest

check:
	.venv/bin/ruff check noticeforge tests scripts
	.venv/bin/ruff format --check --quiet noticeforge tests scripts
	.venv/bin/mypy noticeforge
	node --check noticeforge/static/app.js

format:
	.venv/bin/ruff format noticeforge tests scripts
	npm run format

evaluate:
	$(PY) -m noticeforge.cli evaluate

smoke:
	$(PY) -m noticeforge.cli smoke

fixtures:
	$(PY) scripts/build_fixtures.py

verify: setup test check evaluate smoke

build: setup
	$(UV) build

distribution-check: build
	$(UV) run --isolated --no-project --with ./dist/noticeforge-0.1.1-py3-none-any.whl python scripts/verify_distribution.py
