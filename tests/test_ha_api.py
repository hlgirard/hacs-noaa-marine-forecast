"""Static checks on the Home Assistant facing modules.

The config flow, coordinator, sensor and image platforms all import
Home Assistant, so they cannot be executed by the test suite. That makes it
easy to reference an attribute that no longer exists and only find out at
runtime (as happened with ``FlowHandler._context``, which is the public
``context``). These tests parse the source instead of importing it.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "noaa_marine_forecast"

#: Modules that import Home Assistant and therefore are never executed here.
HA_MODULES = (
    "__init__.py",
    "api.py",
    "config_flow.py",
    "coordinator.py",
    "image.py",
    "sensor.py",
)

#: Attribute names that were private, removed or phased out. Reaching for
#: these raises AttributeError at runtime.
FORBIDDEN_ATTRIBUTES = {
    "_context": "FlowHandler exposes this as the public `context` attribute",
    "handler": "set by the flow manager; do not read directly",
}


def _attribute_names(path: Path) -> set[str]:
    """Return every attribute name referenced anywhere in a module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class TestNoRemovedInternals(unittest.TestCase):
    """No references to private or phased out Home Assistant internals."""

    def test_modules_exist(self) -> None:
        for name in HA_MODULES:
            self.assertTrue((COMPONENT / name).is_file(), name)

    def test_no_forbidden_attributes(self) -> None:
        for name in HA_MODULES:
            used = _attribute_names(COMPONENT / name)
            for attribute, reason in FORBIDDEN_ATTRIBUTES.items():
                self.assertNotIn(
                    attribute,
                    used,
                    f"{name} references {attribute!r}: {reason}",
                )

    def test_config_flow_uses_public_context(self) -> None:
        used = _attribute_names(COMPONENT / "config_flow.py")
        self.assertIn("context", used)

    def test_options_flow_is_not_phased_out_base(self) -> None:
        source = (COMPONENT / "config_flow.py").read_text()
        self.assertNotIn("OptionsFlowWithConfigEntry", source)
        self.assertIn("class MarineForecastOptionsFlow(OptionsFlow)", source)


class TestConfigFlowTitlePlaceholders(unittest.TestCase):
    """The title placeholders assignment must be inside the create path."""

    def test_title_placeholders_assigned_to_public_context(self) -> None:
        tree = ast.parse(
            (COMPONENT / "config_flow.py").read_text(), filename="config_flow.py"
        )
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "context"
                ):
                    continue
                key = target.slice
                if isinstance(key, ast.Constant) and key.value == "title_placeholders":
                    found = True
        self.assertTrue(
            found,
            "config_flow must set self.context['title_placeholders'] "
            "(not a private attribute)",
        )


class TestNoHomeAssistantImportInPureModules(unittest.TestCase):
    """Pure modules must stay importable without Home Assistant."""

    PURE_MODULES = ("parser.py", "flags.py", "alerts.py", "assets.py", "const.py")

    def test_no_homeassistant_imports(self) -> None:
        for name in self.PURE_MODULES:
            source = (COMPONENT / name).read_text()
            self.assertNotIn(
                "homeassistant", source, f"{name} must not import Home Assistant"
            )
            self.assertNotIn("aiohttp", source, f"{name} must not import aiohttp")


if __name__ == "__main__":
    unittest.main()
