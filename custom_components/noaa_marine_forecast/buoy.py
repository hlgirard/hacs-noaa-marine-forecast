"""Parser for NDBC realtime2 standard meteorological files.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

#: Columns exposed as readings, keyed by NDBC header name.
FIELDS: tuple[str, ...] = (
    "WDIR",
    "WSPD",
    "GST",
    "WVHT",
    "DPD",
    "APD",
    "MWD",
    "PRES",
    "ATMP",
    "WTMP",
    "DEWP",
)

#: How many of the most recent rows to scan for each field. Waves and a few
#: other fields are only reported on some rows, so the newest row alone has gaps.
MAX_ROWS = 8


@dataclass(frozen=True)
class BuoyReading:
    """One measured value and the time of the row it came from."""

    value: float
    time: datetime


@dataclass(frozen=True)
class BuoyData:
    """Everything the entities need for one NDBC station."""

    station_id: str
    name: str
    fetched_at: datetime
    observed_at: datetime | None
    readings: dict[str, BuoyReading]

    def value(self, key: str) -> float | None:
        """Return the latest value for an NDBC column, if any."""
        reading = self.readings.get(key)
        return reading.value if reading else None


def parse_realtime(text: str) -> tuple[datetime | None, dict[str, BuoyReading]]:
    """Parse a realtime2 file.

    Returns the newest observation time and, per column, the newest non-missing
    value among the first ``MAX_ROWS`` rows. Raises ValueError when the header
    is missing or no rows can be parsed.
    """
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            if header is None:
                header = line.lstrip("#").split()
            continue
        fields = line.split()
        # A truncated or malformed row must never yield a wrong number.
        if header is None or len(fields) != len(header):
            continue
        rows.append(fields)
        if len(rows) >= MAX_ROWS:
            break
    if header is None or not rows:
        raise ValueError("not an NDBC realtime2 file")

    readings: dict[str, BuoyReading] = {}
    newest: datetime | None = None
    for row in rows:
        try:
            when = datetime(
                int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]),
                tzinfo=UTC,
            )
        except (ValueError, IndexError):
            continue
        if newest is None:
            newest = when
        for name in FIELDS:
            if name in readings or name not in header:
                continue
            index = header.index(name)
            if index >= len(row) or row[index] == "MM":
                continue
            try:
                readings[name] = BuoyReading(float(row[index]), when)
            except ValueError:
                continue
    if newest is None:
        raise ValueError("no parsable observation rows")
    return newest, readings


def build_buoy_data(
    station_id: str, name: str, text: str, fetched_at: datetime
) -> BuoyData:
    """Build :class:`BuoyData` from a realtime2 file body."""
    observed_at, readings = parse_realtime(text)
    return BuoyData(station_id, name, fetched_at, observed_at, readings)


__all__: list[Any] = [
    "FIELDS",
    "BuoyData",
    "BuoyReading",
    "build_buoy_data",
    "parse_realtime",
]
