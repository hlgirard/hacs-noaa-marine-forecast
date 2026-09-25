"""Parity checks between the code, ``strings.json`` and ``translations/en.json``.

A missing translation key does not fail loudly. Home Assistant logs a warning
and renders the raw key, so the symptom is an entity or an error message that
reads ``conditions_tomorow`` or ``invalid_zone`` in the UI. Nothing else in the
test suite would notice, because the pure modules never load the JSON and the
Home Assistant modules cannot be imported without a full install.

These checks are pure ``ast`` and ``json`` so they run in the fast tier with no
dependencies installed.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "noaa_marine_forecast"
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"

#: Platform for each source file, derived from the module name. Home Assistant
#: looks up ``entity.<platform>.<translation_key>.<attribute>``.
PLATFORMS = {"sensor.py": "sensor", "image.py": "image"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _constant_str(node: ast.AST) -> str | None:
    """Return the value of a constant string node, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_values() -> dict[str, str]:
    """Map ``const.py`` module level names to their string values.

    Schema keys are written as ``vol.Required(CONF_ZONE_ID)``, so the literal
    only appears in ``const.py``. Resolving the name is what lets these checks
    see the real key the user is shown.
    """
    path = COMPONENT / "const.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename="const.py")
    values: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _constant_str(node.value)
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    values[target.id] = value
    return values


class TestTranslationKeyParity(unittest.TestCase):
    """Every translation key used in code must exist in both JSON files."""

    @staticmethod
    def _translation_keys() -> dict[str, set[str]]:
        """Map platform -> translation keys referenced by the code."""
        found: dict[str, set[str]] = {p: set() for p in PLATFORMS.values()}
        for filename, platform in PLATFORMS.items():
            path = COMPONENT / filename
            if not path.is_file():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
            for node in ast.walk(tree):
                # MarineSensorDescription(..., translation_key="x")
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg == "translation_key":
                            value = _constant_str(kw.value)
                            if value:
                                found[platform].add(value)
                # _attr_translation_key = "x"
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        name = getattr(target, "attr", None) or getattr(
                            target, "id", None
                        )
                        if name in {
                            "_attr_translation_key",
                            "_translation_key",
                            "translation_key",
                        }:
                            value = _constant_str(node.value)
                            if value:
                                found[platform].add(value)
        return found

    def test_code_references_translation_keys(self) -> None:
        """Guard the extraction itself: a silent empty result proves nothing."""
        found = self._translation_keys()
        self.assertTrue(
            found.get("sensor"),
            "no sensor translation keys found; the AST walk is broken",
        )
        self.assertTrue(
            found.get("image"),
            "no image translation keys found; the AST walk is broken",
        )

    def test_every_translation_key_is_defined(self) -> None:
        for document, label in ((_load(STRINGS), "strings.json"), (_load(EN), "en.json")):
            entities = document.get("entity", {})
            for platform, keys in self._translation_keys().items():
                platform_keys = set(entities.get(platform, {}))
                for key in sorted(keys):
                    with self.subTest(file=label, platform=platform, key=key):
                        self.assertIn(
                            key,
                            platform_keys,
                            f"{label} is missing entity.{platform}.{key}",
                        )
                        self.assertIn(
                            "name",
                            entities.get(platform, {}).get(key, {}),
                            f"{label} entity.{platform}.{key} has no 'name'",
                        )

    def test_no_orphan_entity_translations(self) -> None:
        """Every entity translation must be used, or a rename left it behind."""
        used = self._translation_keys()
        for document, label in ((_load(STRINGS), "strings.json"), (_load(EN), "en.json")):
            for platform, entries in document.get("entity", {}).items():
                for key in sorted(entries):
                    with self.subTest(file=label, platform=platform, key=key):
                        self.assertIn(
                            key,
                            used.get(platform, set()),
                            f"{label} defines entity.{platform}.{key}, "
                            "which no entity uses",
                        )


class TestConfigFlowStrings(unittest.TestCase):
    """Errors and abort reasons must have user-facing text."""

    @staticmethod
    def _error_keys() -> set[str]:
        """Error keys assigned by the config flow, e.g. ``errors["base"] = ...``."""
        path = COMPONENT / "config_flow.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename="config_flow.py")
        keys: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            value = _constant_str(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _attr_name(target.value) == (
                    "errors"
                ):
                    keys.add(value)
        return keys

    def test_error_extraction_finds_known_key(self) -> None:
        """Guards the AST walk; ``invalid_zone`` is set in the user step."""
        self.assertIn(
            "invalid_zone",
            self._error_keys(),
            "expected to find errors['base'] = 'invalid_zone' in config_flow.py",
        )

    def test_error_keys_are_translated(self) -> None:
        for document, label in ((_load(STRINGS), "strings.json"), (_load(EN), "en.json")):
            for key in sorted(self._error_keys()):
                with self.subTest(file=label, key=key):
                    self.assertIn(
                        key,
                        document.get("config", {}).get("error", {}),
                        f"{label} is missing config.error.{key}",
                    )

    def test_abort_reason_is_translated(self) -> None:
        """``_abort_if_unique_id_configured`` aborts as ``already_configured``."""
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        if "_abort_if_unique_id_configured" not in source:
            self.skipTest("config flow no longer aborts on duplicate unique id")
        for document, label in ((_load(STRINGS), "strings.json"), (_load(EN), "en.json")):
            with self.subTest(file=label):
                self.assertIn(
                    "already_configured",
                    document.get("config", {}).get("abort", {}),
                    f"{label} is missing config.abort.already_configured",
                )

    def test_form_fields_are_translated(self) -> None:
        """Every schema key shown to the user needs a label."""
        consts = _const_values()
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        keys = set()
        for node in ast.walk(ast.parse(source, filename="config_flow.py")):
            if not isinstance(node, ast.Call) or _attr_name(node.func) not in {
                "Required",
                "Optional",
            }:
                continue
            if not node.args:
                continue
            arg = _constant_str(node.args[0])
            if arg is None and isinstance(node.args[0], ast.Name):
                arg = consts.get(node.args[0].id)
            if arg:
                keys.add(arg)
        self.assertIn(
            "zone_id", keys, "expected vol.Required(CONF_ZONE_ID) in the user step"
        )
        for document, label in ((_load(STRINGS), "strings.json"), (_load(EN), "en.json")):
            # A label may live under either the config or the options step.
            labelled = set()
            for section in ("config", "options"):
                for entries in document.get(section, {}).get("step", {}).values():
                    labelled.update(entries.get("data", {}))
            for key in sorted(keys):
                with self.subTest(file=label, key=key):
                    self.assertIn(
                        key,
                        labelled,
                        f"{label} has no label for form field {key!r}",
                    )


class TestTranslationFilesAgree(unittest.TestCase):
    """``strings.json`` and ``translations/en.json`` must stay in sync."""

    def test_en_matches_strings(self) -> None:
        self.assertEqual(
            _load(STRINGS),
            _load(EN),
            "strings.json and translations/en.json have diverged",
        )

    def test_files_are_valid_json(self) -> None:
        for path in (STRINGS, EN):
            with self.subTest(path=path.name):
                self.assertIsInstance(_load(path), dict)

    def test_scan_interval_key_matches_constant(self) -> None:
        """The options field label must use the shared key name."""
        document = _load(EN)
        self.assertIn(
            "scan_interval",
            document.get("options", {}).get("step", {}).get("init", {}).get("data", {}),
            "translations/en.json is missing options.step.init.data.scan_interval",
        )


def _attr_name(node: ast.AST) -> str | None:
    """Return the trailing name of an attribute or name node."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


if __name__ == "__main__":
    unittest.main()
