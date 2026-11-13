"""Parsers for NOAA CO-OPS (tides and currents) data API responses.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

# CO-OPS products requested for each station, besides tide predictions.
OBSERVATION_PRODUCTS: tuple[str, ...] = (
    "water_level",
    "air_temperature",
    "water_temperature",
    "air_pressure",
    "wind",
)

TIDE_HIGH = "H"
TIDE_LOW = "L"


@dataclass(frozen=True)
class Reading:
    """One observation: value plus extra fields for the product."""

    time: datetime
    value: float | None
    extra: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class TidePrediction:
    """One predicted high or low tide."""

    time: datetime
    value: float
    kind: str  # TIDE_HIGH or TIDE_LOW


@dataclass(frozen=True)
class StationInfo:
    """Station metadata from the CO-OPS metadata API."""

    station_id: str
    name: str
    latitude: float | None
    longitude: float | None
    state: str | None
    great_lakes: bool


@dataclass(frozen=True)
class TideData:
    """Everything the entities need for one tide station."""

    station_id: str
    name: str
    fetched_at: datetime
    readings: dict[str, Reading]
    predictions: tuple[TidePrediction, ...]
    datum: str
    #: Unit for level attributes (``m`` or ``ft``); sensor states stay metric
    #: and are converted by Home Assistant.
    level_unit: str = "m"

    @property
    def available_products(self) -> set[str]:
        """Names of observation products that returned data."""
        return set(self.readings)

    def next_tide(self, kind: str, now: datetime) -> TidePrediction | None:
        """Return the next predicted tide of ``kind`` after ``now``."""
        for prediction in self.predictions:
            if prediction.kind == kind and prediction.time > now:
                return prediction
        return None

    def upcoming_tide(self, now: datetime) -> TidePrediction | None:
        """Return the next predicted high or low tide after ``now``."""
        for prediction in self.predictions:
            if prediction.time > now:
                return prediction
        return None

    def tide_state(self, now: datetime) -> str | None:
        """Return ``rising`` or ``falling`` from the next predicted extreme."""
        upcoming = [p for p in self.predictions if p.time > now]
        if not upcoming:
            return None
        return "rising" if upcoming[0].kind == TIDE_HIGH else "falling"


METERS_TO_FEET = 3.280839895


def convert_level(meters: float, unit: str) -> float:
    """Convert a level in metres to ``unit`` (``m`` or ``ft``)."""
    if unit == "ft":
        return round(meters * METERS_TO_FEET, 3)
    return round(meters, 3)


def _to_float(value: Any) -> float | None:
    """Convert a CO-OPS string value to float; blank or invalid is None."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_time(value: str) -> datetime:
    """Parse a CO-OPS ``YYYY-MM-DD HH:MM`` timestamp requested as GMT."""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def response_error(payload: Any) -> str | None:
    """Return the error message of an error payload, or None."""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return str(payload["error"].get("message", "unknown error")).strip()
    return None


def parse_station_info(payload: Any, requested_id: str) -> StationInfo | None:
    """Parse the metadata API response; None if the station is unknown."""
    if not isinstance(payload, dict):
        return None
    stations = payload.get("stations")
    if not isinstance(stations, list) or not stations:
        return None
    station = stations[0]
    if not isinstance(station, dict):
        return None
    return StationInfo(
        station_id=str(station.get("id") or requested_id),
        name=str(station.get("name") or requested_id).strip(),
        latitude=_to_float(station.get("lat")),
        longitude=_to_float(station.get("lng")),
        state=station.get("state") or None,
        great_lakes=bool(station.get("greatlakes")),
    )


def parse_latest_reading(payload: Any, product: str) -> Reading | None:
    """Return the most recent usable reading of an observation product.

    Returns None for error payloads (for example a station that does not
    offer the product) and for payloads without a usable value.
    """
    if not isinstance(payload, dict) or response_error(payload):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    for row in reversed(data):
        if not isinstance(row, dict) or "t" not in row:
            continue
        try:
            when = parse_time(row["t"])
        except ValueError:
            continue
        if product == "wind":
            speed = _to_float(row.get("s"))
            if speed is None:
                continue
            return Reading(
                when,
                speed,
                {"gust": _to_float(row.get("g")), "direction": _to_float(row.get("d"))},
            )
        value = _to_float(row.get("v"))
        if value is None:
            continue
        return Reading(when, value)
    return None


def parse_predictions(payload: Any) -> tuple[TidePrediction, ...]:
    """Parse a ``predictions`` hi/lo response, ordered by time."""
    if not isinstance(payload, dict) or response_error(payload):
        return ()
    rows = payload.get("predictions")
    if not isinstance(rows, list):
        return ()
    result: list[TidePrediction] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = row.get("type")
        value = _to_float(row.get("v"))
        if kind not in (TIDE_HIGH, TIDE_LOW) or value is None:
            continue
        try:
            result.append(TidePrediction(parse_time(row["t"]), value, kind))
        except (KeyError, ValueError):
            continue
    return tuple(sorted(result, key=lambda p: p.time))
