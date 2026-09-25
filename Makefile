VENV := .venv
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest

.PHONY: help test test-ha test-all venv clean

help:
	@echo "test      Run the fast suite (stdlib unittest, no dependencies)"
	@echo "test-ha   Run the real-Home-Assistant suite (needs the venv)"
	@echo "test-all  Run both tiers"
	@echo "venv      Create .venv and install the development dependencies"

## Fast tier: no Home Assistant required. Stubs out homeassistant, aiohttp and
## voluptuous.
test:
	python3 -m unittest discover -s tests -t . $(TESTFLAGS)

## Real Home Assistant tier. Exercises the entity, config flow and coordinator
## code paths the fast tier can only inspect statically. HTTP Requests remain mocked.
test-ha: $(VENV)
	$(PYTEST)

test-all: test test-ha

$(VENV):
	uv python install 3.14
	uv venv --python 3.14 $(VENV)
	uv pip install --python $(PY) -r requirements-dev.txt

clean:
	rm -rf .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
