"""Device info helpers shared by all platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .api import forecast_url
from .const import (
    CONF_NAME,
    CONF_PRODUCT_TYPE,
    CONF_STATION_ID,
    CONF_ZONE_ID,
    DEFAULT_NAME,
    DEFAULT_PRODUCT_TYPE,
    DOMAIN,
    COOPS_STATION_PAGE,
    NDBC_STATION_PAGE,
    PRODUCT_BUOY,
    PRODUCT_MARINE_ZONE,
    PRODUCT_TIDE_STATION,
)


def entry_name(entry: ConfigEntry) -> str:
    """Return the display name: the options value wins over the setup value."""
    return (
        entry.options.get(CONF_NAME) or entry.data.get(CONF_NAME) or DEFAULT_NAME
    )


def entity_prefix(entry: ConfigEntry) -> str:
    """Return the lowercase id prefix used in entity unique ids.

    Kept identical to the pre-product-type scheme so existing entities survive.
    """
    product_type = entry.data.get(CONF_PRODUCT_TYPE, DEFAULT_PRODUCT_TYPE)
    if product_type == PRODUCT_TIDE_STATION:
        return f"tide_{entry.data[CONF_STATION_ID]}"
    if product_type == PRODUCT_BUOY:
        return f"buoy_{entry.data[CONF_STATION_ID].lower()}"
    return entry.data[CONF_ZONE_ID].lower()


def build_device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Return the device info for a config entry, by product type."""
    product_type = entry.data.get(CONF_PRODUCT_TYPE, DEFAULT_PRODUCT_TYPE)
    name = entry_name(entry)
    if product_type == PRODUCT_MARINE_ZONE:
        zone_id = entry.data[CONF_ZONE_ID]
        return {
            "identifiers": {(DOMAIN, zone_id.lower())},
            "name": f"{name} {zone_id}",
            "manufacturer": "NOAA / NWS",
            "model": "Coastal Waters Forecast",
            "configuration_url": forecast_url(zone_id),
        }
    if product_type == PRODUCT_TIDE_STATION:
        station = entry.data[CONF_STATION_ID]
        return {
            "identifiers": {(DOMAIN, f"tide_{station}")},
            "name": f"{name} ({station})",
            "manufacturer": "NOAA / CO-OPS",
            "model": "Tide Station",
            "configuration_url": COOPS_STATION_PAGE.format(station=station),
        }
    if product_type == PRODUCT_BUOY:
        station = entry.data[CONF_STATION_ID]
        return {
            "identifiers": {(DOMAIN, f"buoy_{station.lower()}")},
            "name": f"{name} ({station})",
            "manufacturer": "NOAA / NDBC",
            "model": "Buoy / Weather Station",
            "configuration_url": NDBC_STATION_PAGE.format(station=station),
        }
    raise ValueError(f"Unsupported product type: {product_type}")
