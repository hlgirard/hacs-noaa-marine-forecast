"""Loading of flag image assets.

Kept free of Home Assistant imports so it can be unit tested standalone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).parent / "assets" / "flags"

#: Flag key -> asset file stem, for the four warning flags only. There is no
#: image for clear conditions: the entity is unavailable when no flag is in
#: force. To change the artwork, replace the files in ``assets/flags`` keeping
#: the same file names.
FLAG_ASSETS: dict[str, str] = {
    "small_craft_advisory": "small_craft_advisory",
    "gale_warning": "gale_warning",
    "storm_warning": "storm_warning",
    "hurricane_warning": "hurricane_warning",
}

CONTENT_TYPES: dict[str, str] = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

#: Every supported suffix, longest first so ".jpeg" is preferred over ".jpg".
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".svg",
    ".png",
    ".webp",
    ".jpeg",
    ".jpg",
)


@dataclass(frozen=True)
class FlagImage:
    """A loaded flag image."""

    content: bytes
    content_type: str


def asset_path(flag: str) -> Path | None:
    """Return the path of the asset for a flag, or None when it is missing."""
    stem = FLAG_ASSETS.get(flag)
    if stem is None:
        return None
    for suffix in SUPPORTED_SUFFIXES:
        path = ASSET_DIR / f"{stem}{suffix}"
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=None)
def load_flag_image(flag: str) -> FlagImage:
    """Load the image bytes for a flag key.

    Raises :class:`FileNotFoundError` when the asset is missing. There is no
    fallback image: showing a different flag would misrepresent conditions, so
    the caller makes the entity unavailable instead.
    """
    if flag not in FLAG_ASSETS:
        raise FileNotFoundError(f"No flag image defined for {flag!r}")
    path = asset_path(flag)
    if path is None:
        stem = FLAG_ASSETS[flag]
        raise FileNotFoundError(
            f"No flag image asset for {flag!r} in {ASSET_DIR} "
            f"(expected {stem}.svg/.png/.jpg/.webp)"
        )
    try:
        content = path.read_bytes()
    except OSError as err:  # pragma: no cover - defensive
        _LOGGER.error("Unable to read flag image %s: %s", path, err)
        raise FileNotFoundError(f"Unable to read flag image {path}: {err}") from err
    return FlagImage(content, CONTENT_TYPES[path.suffix.lower()])
