"""Sensors for tide stations (CO-OPS) and buoys (NDBC)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    EntityCategory,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .buoy import BuoyData
from .device import build_device_info, entity_prefix
from .tides import TIDE_HIGH, TIDE_LOW, TideData


@dataclass(frozen=True, kw_only=True)
class ObsSensorDescription(SensorEntityDescription):
    """Describe a tide or buoy sensor."""

    value_fn: Callable[[Any], Any]
    #: Sensors are created only when this is true for the first data fetch.
    present_fn: Callable[[Any], bool]
    attributes_fn: Callable[[Any], dict[str, Any] | None] | None = None


# --- diagnostics shared by tide stations and buoys ------------------------

DIAGNOSTIC_SENSORS: tuple[ObsSensorDescription, ...] = (
    ObsSensorDescription(
        key="station_id",
        translation_key="station_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.station_id,
        present_fn=lambda data: True,
        attributes_fn=lambda data: {"station_name": data.name},
    ),
    ObsSensorDescription(
        key="checked_at",
        translation_key="checked_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.fetched_at,
        present_fn=lambda data: True,
    ),
)

# --- tide station ---------------------------------------------------------


def _reading_value(product: str, extra: str | None = None) -> Callable[[TideData], Any]:
    def _value(data: TideData) -> Any:
        reading = data.readings.get(product)
        if reading is None:
            return None
        return reading.extra.get(extra) if extra else reading.value

    return _value


def _has_reading(product: str, extra: str | None = None) -> Callable[[TideData], bool]:
    return lambda data: _reading_value(product, extra)(data) is not None


def _next_tide(kind: str, attr: str) -> Callable[[TideData], Any]:
    def _value(data: TideData) -> Any:
        prediction = data.next_tide(kind, dt_util.utcnow())
        return getattr(prediction, attr) if prediction else None

    return _value


def _next_tide_kind(data: TideData) -> str | None:
    prediction = data.upcoming_tide(dt_util.utcnow())
    if prediction is None:
        return None
    return "high" if prediction.kind == TIDE_HIGH else "low"


def _next_tide_attributes(data: TideData) -> dict[str, Any] | None:
    """Time and level of the next tide (level in metres, relative to datum)."""
    prediction = data.upcoming_tide(dt_util.utcnow())
    if prediction is None:
        return None
    return {
        "time": prediction.time,
        "level": prediction.value,
        "level_unit": "m",
        "datum": data.datum,
    }


def _has_predictions(data: TideData) -> bool:
    return bool(data.predictions)


def _reading_time(product: str) -> Callable[[TideData], datetime | None]:
    def _value(data: TideData) -> datetime | None:
        reading = data.readings.get(product)
        return reading.time if reading else None

    return _value


TIDE_SENSORS: tuple[ObsSensorDescription, ...] = (
    ObsSensorDescription(
        key="water_level",
        translation_key="water_level",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_reading_value("water_level"),
        present_fn=_has_reading("water_level"),
        attributes_fn=lambda data: {
            "datum": data.datum,
            "observed_at": _reading_time("water_level")(data),
        },
    ),
    ObsSensorDescription(
        key="tide_state",
        translation_key="tide_state",
        device_class=SensorDeviceClass.ENUM,
        options=["rising", "falling"],
        value_fn=lambda data: data.tide_state(dt_util.utcnow()),
        present_fn=_has_predictions,
    ),
    ObsSensorDescription(
        key="next_tide",
        translation_key="next_tide",
        device_class=SensorDeviceClass.ENUM,
        options=["high", "low"],
        value_fn=_next_tide_kind,
        present_fn=_has_predictions,
        attributes_fn=_next_tide_attributes,
    ),
    ObsSensorDescription(
        key="next_high_tide",
        translation_key="next_high_tide",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_tide(TIDE_HIGH, "time"),
        present_fn=_has_predictions,
    ),
    ObsSensorDescription(
        key="next_high_tide_level",
        translation_key="next_high_tide_level",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=2,
        value_fn=_next_tide(TIDE_HIGH, "value"),
        present_fn=_has_predictions,
    ),
    ObsSensorDescription(
        key="next_low_tide",
        translation_key="next_low_tide",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_tide(TIDE_LOW, "time"),
        present_fn=_has_predictions,
    ),
    ObsSensorDescription(
        key="next_low_tide_level",
        translation_key="next_low_tide_level",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=2,
        value_fn=_next_tide(TIDE_LOW, "value"),
        present_fn=_has_predictions,
    ),
    ObsSensorDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("air_temperature"),
        present_fn=_has_reading("air_temperature"),
    ),
    ObsSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("water_temperature"),
        present_fn=_has_reading("water_temperature"),
    ),
    ObsSensorDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("air_pressure"),
        present_fn=_has_reading("air_pressure"),
    ),
    ObsSensorDescription(
        key="wind_speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("wind"),
        present_fn=_has_reading("wind"),
    ),
    ObsSensorDescription(
        key="wind_gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("wind", "gust"),
        present_fn=_has_reading("wind", "gust"),
    ),
    ObsSensorDescription(
        key="wind_direction",
        translation_key="wind_direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading_value("wind", "direction"),
        present_fn=_has_reading("wind", "direction"),
    ),
    *DIAGNOSTIC_SENSORS,
)

# --- buoy -----------------------------------------------------------------


def _buoy_value(column: str) -> Callable[[BuoyData], float | None]:
    return lambda data: data.value(column)


def _buoy_present(column: str) -> Callable[[BuoyData], bool]:
    return lambda data: data.value(column) is not None


def _buoy_attrs(column: str) -> Callable[[BuoyData], dict[str, Any] | None]:
    def _attrs(data: BuoyData) -> dict[str, Any] | None:
        reading = data.readings.get(column)
        return {"observed_at": reading.time} if reading else None

    return _attrs


def _buoy(
    key: str, column: str, **kwargs: Any
) -> ObsSensorDescription:
    return ObsSensorDescription(
        key=key,
        translation_key=key,
        value_fn=_buoy_value(column),
        present_fn=_buoy_present(column),
        attributes_fn=_buoy_attrs(column),
        state_class=SensorStateClass.MEASUREMENT,
        **kwargs,
    )


BUOY_SENSORS: tuple[ObsSensorDescription, ...] = (
    _buoy(
        "wind_speed", "WSPD",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
    ),
    _buoy(
        "wind_gust", "GST",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
    ),
    _buoy("wind_direction", "WDIR", native_unit_of_measurement=DEGREE),
    _buoy(
        "wave_height", "WVHT",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=1,
    ),
    _buoy(
        "dominant_wave_period", "DPD",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    _buoy(
        "average_wave_period", "APD",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    _buoy("wave_direction", "MWD", native_unit_of_measurement=DEGREE),
    _buoy(
        "pressure", "PRES",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
    ),
    _buoy(
        "air_temperature", "ATMP",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    _buoy(
        "water_temperature", "WTMP",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    _buoy(
        "dew_point", "DEWP",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ObsSensorDescription(
        key="observed_at",
        translation_key="observed_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.observed_at,
        present_fn=lambda data: data.observed_at is not None,
    ),
    *DIAGNOSTIC_SENSORS,
)



class ObsSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """A tide station or buoy sensor."""

    _attr_has_entity_name = True
    entity_description: ObsSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: ObsSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entity_prefix(entry)}_{description.key}"
        self._attr_device_info = build_device_info(entry)

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        fn = self.entity_description.attributes_fn
        if data is None or fn is None:
            return None
        return fn(data)


def build_obs_sensors(
    coordinator: DataUpdateCoordinator,
    descriptions: tuple[ObsSensorDescription, ...],
    entry: ConfigEntry,
) -> list[ObsSensor]:
    """Create sensors whose data is present in the first fetch."""
    data = coordinator.data
    return [
        ObsSensor(coordinator, description, entry)
        for description in descriptions
        if data is not None and description.present_fn(data)
    ]
