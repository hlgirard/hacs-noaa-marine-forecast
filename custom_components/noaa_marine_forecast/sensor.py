"""Sensor platform for NOAA Marine Forecast."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import CONF_NAME, CONF_ZONE_ID, DEFAULT_NAME, DOMAIN
from .coordinator import MarineZoneData
from .flags import FLAG_TITLES
from .alerts import format_alert_text, top_alert_detail
from .parser import PART_DAY, PART_NIGHT, ForecastPeriod, format_hazard_title

UTC = timezone.utc


def _iso(value: datetime | None) -> str | None:
    """Return an ISO 8601 string for a datetime."""
    return value.isoformat() if value else None


def _period_text(period: ForecastPeriod | None) -> str | None:
    """Return the forecast text for a period."""
    return period.text if period else None


def _period_attributes(
    data: MarineZoneData, period: ForecastPeriod | None
) -> dict[str, Any] | None:
    """Return descriptive attributes for a period.

    The hazard summary is product-level rather than per period, but every
    period sensor carries it so cards never have to know which sensor is
    "current".
    """
    if period is None:
        return None
    return {
        "period_label": period.source_label,
        "period_date": period.period_date.isoformat()
        if period.period_date
        else None,
        "period_part": period.part,
        "hazard_summary": data.forecast.hazard_summary,
        "hazard_title": format_hazard_title(data.forecast.hazard_summary),
    }


def _now_attributes(data: MarineZoneData) -> dict[str, Any]:
    """Return period attributes plus the raw product text."""
    attributes: dict[str, Any] = _period_attributes(data, data.now_period) or {}
    attributes["full_text"] = data.forecast.raw_text
    attributes["selection_method"] = data.selection_method
    attributes.setdefault("hazard_summary", data.forecast.hazard_summary)
    attributes.setdefault(
        "hazard_title", format_hazard_title(data.forecast.hazard_summary)
    )
    return attributes


@dataclass(frozen=True, kw_only=True)
class MarineSensorDescription(SensorEntityDescription):
    """Describe a NOAA marine forecast sensor."""

    value_fn: Callable[[MarineZoneData], Any]
    attributes_fn: Callable[[MarineZoneData], dict[str, Any] | None] | None = None


SENSORS: tuple[MarineSensorDescription, ...] = (
    MarineSensorDescription(
        key="conditions_now",
        translation_key="conditions_now",
        value_fn=lambda data: _period_text(data.now_period),
        attributes_fn=lambda data: _now_attributes(data),
    ),
    MarineSensorDescription(
        key="conditions_next",
        translation_key="conditions_next",
        value_fn=lambda data: _period_text(data.next_period),
        attributes_fn=lambda data: _period_attributes(data, data.next_period),
    ),
    MarineSensorDescription(
        key="conditions_today",
        translation_key="conditions_today",
        value_fn=lambda data: _period_text(data.period_for(0, PART_DAY)),
        attributes_fn=lambda data: _period_attributes(
            data, data.period_for(0, PART_DAY)
        ),
    ),
    MarineSensorDescription(
        key="conditions_tonight",
        translation_key="conditions_tonight",
        value_fn=lambda data: _period_text(data.period_for(0, PART_NIGHT)),
        attributes_fn=lambda data: _period_attributes(
            data, data.period_for(0, PART_NIGHT)
        ),
    ),
    MarineSensorDescription(
        key="conditions_tomorrow",
        translation_key="conditions_tomorrow",
        value_fn=lambda data: _period_text(data.period_for(1, PART_DAY)),
        attributes_fn=lambda data: _period_attributes(
            data, data.period_for(1, PART_DAY)
        ),
    ),
    MarineSensorDescription(
        key="conditions_tomorrow_night",
        translation_key="conditions_tomorrow_night",
        value_fn=lambda data: _period_text(data.period_for(1, PART_NIGHT)),
        attributes_fn=lambda data: _period_attributes(
            data, data.period_for(1, PART_NIGHT)
        ),
    ),
    MarineSensorDescription(
        key="alert_flags",
        translation_key="alert_flags",
        value_fn=lambda data: data.alerts.combination,
        attributes_fn=lambda data: _alert_attributes(data),
    ),
    MarineSensorDescription(
        key="active_alerts",
        translation_key="active_alerts",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.alerts.active),
    ),
    MarineSensorDescription(
        key="pending_alerts",
        translation_key="pending_alerts",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.alerts.pending),
    ),
    MarineSensorDescription(
        key="alert_summary",
        translation_key="alert_summary",
        value_fn=lambda data: _alert_summary(data),
        attributes_fn=lambda data: {
            "active_alerts": [alert.as_attributes() for alert in data.alerts.active],
            "pending_alerts": [
                alert.as_attributes() for alert in data.alerts.pending
            ],
        },
    ),
    MarineSensorDescription(
        key="alert",
        translation_key="alert",
        value_fn=lambda data: _alert_text(data),
        attributes_fn=lambda data: _alert_detail(data),
    ),
    MarineSensorDescription(
        key="zone_name",
        translation_key="zone_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.forecast.zone_name(),
    ),
    MarineSensorDescription(
        key="forecast_office",
        translation_key="forecast_office",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.forecast.office,
        attributes_fn=lambda data: {
            "office_name": data.forecast.office_name,
            "raw_header": data.forecast.raw_header,
        },
    ),
    MarineSensorDescription(
        key="product_title",
        translation_key="product_title",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.forecast.product_title,
        attributes_fn=lambda data: {
            "area_description": data.forecast.area_description,
            "zones": list(data.forecast.zones),
        },
    ),
    MarineSensorDescription(
        key="wmo_identifier",
        translation_key="wmo_identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.forecast.wmo_id,
    ),
    MarineSensorDescription(
        key="awips_identifier",
        translation_key="awips_identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.forecast.awips_id,
    ),
    MarineSensorDescription(
        key="issued_at",
        translation_key="issued_at",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.forecast.issued,
    ),
    MarineSensorDescription(
        key="expires_at",
        translation_key="expires_at",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.forecast.expires,
    ),
    MarineSensorDescription(
        key="checked_at",
        translation_key="checked_at",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.fetched_at,
    ),
)


def _alert_attributes(data: MarineZoneData) -> dict[str, Any]:
    """Return flag attributes for the flag sensor."""
    bundle = data.alerts
    return {
        "active_flags": list(bundle.active_flags),
        "pending_flags": list(bundle.pending_flags),
        "flag_combination": bundle.combination,
        "highest_flag": bundle.highest_flag,
        "highest_flag_title": FLAG_TITLES.get(bundle.highest_flag),
        "highest_flag_lifecycle": bundle.highest_lifecycle,
        "active_count": len(bundle.active),
        "pending_count": len(bundle.pending),
        "other_marine_alerts": [
            alert.as_attributes() for alert in bundle.other
        ],
        "alerts_available": data.alerts_available,
        "alerts_updated_at": _iso(data.alerts_updated_at),
    }


def _alert_detail(data: MarineZoneData) -> dict[str, Any]:
    """Return flag, zone and top-alert attributes for the alert sensor."""
    bundle = data.alerts
    attributes: dict[str, Any] = {
        "flag": bundle.highest_flag,
        "flag_title": FLAG_TITLES.get(bundle.highest_flag),
        "lifecycle": bundle.highest_lifecycle,
        "zone": data.zone_id,
        "zone_name": data.forecast.zone_name(),
        "alerts_available": data.alerts_available,
        "alerts_updated_at": _iso(data.alerts_updated_at),
    }
    detail = top_alert_detail(bundle)
    if detail is not None:
        attributes.update(detail)
    return attributes


def _alert_text(data: MarineZoneData) -> str:
    """Return the one line alert summary, or the all-clear text."""
    return (
        format_alert_text(data.alerts, dt_util.DEFAULT_TIME_ZONE)
        or "No marine alerts"
    )


def _alert_summary(data: MarineZoneData) -> str:
    """Return a one line summary of the marine alerts."""
    parts: list[str] = []
    if data.alerts.active:
        parts.append(
            "Active: "
            + ", ".join(alert.event for alert in data.alerts.active)
        )
    if data.alerts.pending:
        parts.append(
            "Pending: "
            + ", ".join(alert.event for alert in data.alerts.pending)
        )
    return " | ".join(parts) if parts else "none"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors for a config entry."""
    coordinator: DataUpdateCoordinator[MarineZoneData] = (
        hass.data[DOMAIN][entry.entry_id]
    )
    zone_id = entry.data[CONF_ZONE_ID]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME

    entities = [
        MarineSensor(coordinator, description, zone_id, name)
        for description in SENSORS
    ]
    async_add_entities(entities)


class MarineSensor(CoordinatorEntity[MarineZoneData], SensorEntity):
    """A NOAA marine forecast sensor."""

    _attr_has_entity_name = True
    entity_description: MarineSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[MarineZoneData],
        description: MarineSensorDescription,
        zone_id: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._zone_id = zone_id
        self._attr_unique_id = f"{zone_id.lower()}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, zone_id.lower())},
            "name": f"{name} {zone_id}",
            "manufacturer": "NOAA / NWS",
            "model": "Coastal Waters Forecast",
            "configuration_url": f"https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/{zone_id[:2].lower()}/{zone_id.lower()}.txt",
        }

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sensor attributes.

        The ``alert`` sensor additionally mirrors the flag image entity's
        ``entity_picture`` URL so it can drive a picture-showing card on its
        own. The frontend reads ``attributes.entity_picture`` for any domain,
        and the URL is a stable signed proxy URL, so copying it verbatim is
        safe. A missing image entity only costs the picture, never the text.
        """
        data = self.coordinator.data
        if data is None or self.entity_description.attributes_fn is None:
            attributes = None
        else:
            attributes = self.entity_description.attributes_fn(data)
        if self.entity_description.key != "alert":
            return attributes
        merged = dict(attributes or {})
        merged["entity_picture"] = self._alert_flag_picture()
        return merged

    def _alert_flag_picture(self) -> str | None:
        """Return the flag image entity's picture URL, if registered."""
        hass = self.hass
        if hass is None:
            return None
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(hass)
            entity_id = registry.async_get_entity_id(
                "image", DOMAIN, f"{self._zone_id.lower()}_alert_flag_image"
            )
            if entity_id is None:
                return None
            state = hass.states.get(entity_id)
            if state is None:
                return None
            picture = state.attributes.get("entity_picture")
            return picture if isinstance(picture, str) else None
        except Exception:  # pragma: no cover - defensive
            return None

    @property
    def available(self) -> bool:
        """Return whether the sensor has data.

        A period that is not present in the product yields an ``unknown``
        state rather than making the entity unavailable.
        """
        return super().available and self.coordinator.data is not None
