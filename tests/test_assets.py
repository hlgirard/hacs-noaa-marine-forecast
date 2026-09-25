"""Tests for the flag image asset loader."""

from __future__ import annotations

import unittest
from pathlib import Path
from xml.etree import ElementTree

from custom_components.noaa_marine_forecast.assets import (
    ASSET_DIR,
    CONTENT_TYPES,
    FLAG_ASSETS,
    asset_path,
    load_flag_image,
)

ALL_FLAGS = (
    "small_craft_advisory",
    "gale_warning",
    "storm_warning",
    "hurricane_warning",
)


class TestAssetMapping(unittest.TestCase):
    """Only the four warning flags have images."""

    def test_exactly_four_flag_assets(self) -> None:
        self.assertEqual(set(FLAG_ASSETS), set(ALL_FLAGS))

    def test_no_all_clear_asset(self) -> None:
        self.assertNotIn("none", FLAG_ASSETS)
        self.assertFalse((ASSET_DIR / "no_warning.svg").exists())
        self.assertFalse((ASSET_DIR / "no_warning.png").exists())

    def test_no_other_marine_alert_asset(self) -> None:
        self.assertNotIn("other_marine_alert", FLAG_ASSETS)
        self.assertFalse((ASSET_DIR / "other_marine_alert.svg").exists())

    def test_every_flag_has_a_shipped_asset(self) -> None:
        for flag in ALL_FLAGS:
            path = asset_path(flag)
            self.assertIsNotNone(path, f"missing asset for {flag}")
            assert path is not None
            self.assertTrue(path.is_file())
            self.assertEqual(path.stem, FLAG_ASSETS[flag])

    def test_unknown_flag_has_no_path(self) -> None:
        self.assertIsNone(asset_path("none"))
        self.assertIsNone(asset_path("other_marine_alert"))
        self.assertIsNone(asset_path("bogus_flag"))


class TestLoadFlagImage(unittest.TestCase):
    """Loading flag artwork."""

    def test_loads_each_flag(self) -> None:
        for flag in ALL_FLAGS:
            image = load_flag_image(flag)
            self.assertTrue(image.content, f"empty asset for {flag}")
            self.assertIn(image.content_type, CONTENT_TYPES.values())

    def test_svg_content_type(self) -> None:
        path = asset_path("storm_warning")
        assert path is not None
        if path.suffix == ".svg":
            self.assertEqual(
                load_flag_image("storm_warning").content_type, "image/svg+xml"
            )

    def test_shipped_assets_parse_as_images(self) -> None:
        # Guards against an asset that exists but is not renderable.
        for flag in ALL_FLAGS:
            image = load_flag_image(flag)
            self.assertTrue(image.content.strip(), f"empty asset for {flag}")

    def test_missing_asset_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_flag_image("none")

    def test_undefined_flag_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_flag_image("other_marine_alert")

    def test_error_for_undefined_flag_names_the_key(self) -> None:
        with self.assertRaises(FileNotFoundError) as ctx:
            load_flag_image("none")
        self.assertIn("none", str(ctx.exception))

    def test_results_are_cached(self) -> None:
        self.assertIs(
            load_flag_image("hurricane_warning"),
            load_flag_image("hurricane_warning"),
        )


class TestAssetDirectory(unittest.TestCase):
    """The asset directory ships with the integration."""

    def test_directory_exists(self) -> None:
        self.assertTrue(ASSET_DIR.is_dir())

    def test_no_stray_assets(self) -> None:
        stems = {path.stem for path in ASSET_DIR.iterdir() if path.is_file()}
        self.assertEqual(stems, set(FLAG_ASSETS.values()))

    def test_assets_are_images(self) -> None:
        for path in ASSET_DIR.iterdir():
            if not path.is_file():
                continue
            self.assertIn(path.suffix.lower(), CONTENT_TYPES, path.name)

    def test_svg_assets_are_well_formed(self) -> None:
        for path in ASSET_DIR.iterdir():
            if path.is_file() and path.suffix.lower() == ".svg":
                root = ElementTree.fromstring(path.read_bytes())
                self.assertTrue(
                    root.tag.endswith("svg"), f"{path.name} is not an SVG root"
                )


if __name__ == "__main__":
    unittest.main()
