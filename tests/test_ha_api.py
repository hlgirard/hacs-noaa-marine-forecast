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


class TestCoordinatorImplementsUpdateMethod(unittest.TestCase):
    """The coordinator must actually implement ``_async_update_data``.

    A bare ``DataUpdateCoordinator`` whose update method is never bound raises
    ``NotImplementedError`` on the first refresh, which only surfaces when the
    entry is set up. These assertions check the wiring statically.
    """

    @staticmethod
    def _coordinator_class() -> ast.ClassDef:
        tree = ast.parse(
            (COMPONENT / "coordinator.py").read_text(), filename="coordinator.py"
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and base.value.id == "DataUpdateCoordinator"
                for base in node.bases
            ):
                return node
        raise AssertionError(
            "coordinator.py must define a DataUpdateCoordinator subclass"
        )

    def test_subclasses_data_update_coordinator(self) -> None:
        self._coordinator_class()

    def test_overrides_async_update_data(self) -> None:
        methods = {
            node.name: node
            for node in self._coordinator_class().body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn(
            "_async_update_data",
            methods,
            "the coordinator subclass must define _async_update_data",
        )
        self.assertIsInstance(
            methods["_async_update_data"],
            ast.AsyncFunctionDef,
            "_async_update_data must be async",
        )

    def test_factory_does_not_build_the_base_class(self) -> None:
        """The factory must instantiate the subclass, not the base class."""
        tree = ast.parse(
            (COMPONENT / "coordinator.py").read_text(), filename="coordinator.py"
        )
        factory = None
        for node in tree.body:
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "async_setup_coordinator"
            ):
                factory = node
        self.assertIsNotNone(factory, "async_setup_coordinator is missing")
        assert factory is not None
        called = {
            node.func.id
            for node in ast.walk(factory)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn(
            "DataUpdateCoordinator",
            called,
            "async_setup_coordinator must instantiate the coordinator "
            "subclass so its _async_update_data is used",
        )
        self.assertIn("MarineForecastCoordinator", called)


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
