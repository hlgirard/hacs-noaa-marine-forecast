"""Tests for the NOAA marine forecast integration.

Run with::

    python -m unittest discover -s tests -t . -v

The parser, flag and alert modules are deliberately free of Home Assistant
imports, but importing them normally would execute the integration's
``__init__.py``. To keep the test suite runnable without Home Assistant
installed, the component package is pre-registered as a stub module pointing
at the real source directory.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "noaa_marine_forecast"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _stub_package(name: str, path: Path) -> None:
    """Register a namespace-style stub package so submodules import cleanly."""
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


_stub_package("custom_components", REPO_ROOT / "custom_components")
_stub_package("custom_components.noaa_marine_forecast", COMPONENT_DIR)
