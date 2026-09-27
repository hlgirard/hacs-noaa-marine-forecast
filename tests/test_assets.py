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


class TestBrandIcon(unittest.TestCase):
    """The integration's brand icon is the storm warning flag.

    Home Assistant serves ``brand/icon.png`` for the integration (with
    ``logo.png`` and ``@2x`` variants falling back to it), so a single
    file covers every surface.

    Pixel comparison is stdlib-only (``struct``/``zlib``) so this test
    also runs in the dependency-free fast tier.
    """

    def test_brand_icon_is_storm_warning_flag(self) -> None:
        brand_icon = ASSET_DIR.parent.parent / "brand" / "icon.png"
        self.assertTrue(brand_icon.is_file(), "missing brand/icon.png")
        flag_pixels, flag_size = _read_png_rgba(
            asset_path("storm_warning")
        )
        icon_pixels, icon_size = _read_png_rgba(brand_icon)
        self.assertEqual(icon_size, (256, 256))
        scale_x = icon_size[0] // flag_size[0]
        scale_y = icon_size[1] // flag_size[1]
        self.assertEqual(
            (icon_size[0] % flag_size[0], icon_size[1] % flag_size[1]), (0, 0)
        )
        for y in range(flag_size[1]):
            for x in range(flag_size[0]):
                expected = bytes(flag_pixels[(y * flag_size[0] + x) * 4 :][:4])
                # Nearest-neighbour upscale: every pixel in the block is
                # identical, so sampling the block origin suffices.
                ix, iy = x * scale_x, y * scale_y
                actual = bytes(icon_pixels[(iy * icon_size[0] + ix) * 4 :][:4])
                self.assertEqual(
                    actual,
                    expected,
                    "brand/icon.png diverged from the storm "
                    f"warning flag at {ix},{iy}",
                )


def _read_png_rgba(path) -> tuple[bytearray, tuple[int, int]]:
    """Decode an 8-bit non-interlaced RGBA PNG with the standard library."""
    import struct
    import zlib

    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    pos = 8
    width = height = 0
    header = (0, 0, 0)
    raw_bands = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = (
                struct.unpack(">IIBBBBB", chunk)
            )
            header = (bit_depth, color_type, interlace)
        elif kind == b"IDAT":
            raw_bands += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    assert header == (8, 6, 0), f"{path} must be 8-bit non-interlaced RGBA"
    raw = zlib.decompress(bytes(raw_bands))
    channels = 4
    stride = width * channels
    pixels = bytearray(width * height * channels)
    prev = bytearray(stride)
    offset = 0
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif filter_type != 0:
            raise AssertionError(f"unknown PNG filter {filter_type}")
        pixels[y * stride : (y + 1) * stride] = line
        prev = line
    return pixels, (width, height)


if __name__ == "__main__":
    unittest.main()
