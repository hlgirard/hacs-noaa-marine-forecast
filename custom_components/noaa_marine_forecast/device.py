"""Device info helpers shared by all platforms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .api import forecast_url
from .const import (
    CONF_NAME,
    CONF_PRODUCT_TYPE,
    CONF_ZONE_ID,
    DEFAULT_NAME,
    DEFAULT_PRODUCT_TYPE,
    DOMAIN,
    PRODUCT_MARINE_ZONE,
)


def entity_prefix(entry: ConfigEntry) -> str:
    """Return the lowercase id prefix used in entity unique ids.

    Kept identical to the pre-product-type scheme so existing entities survive.
    """
    return entry.data[CONF_ZONE_ID].lower()


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info for a config entry, by product type."""
    product_type = entry.data.get(CONF_PRODUCT_TYPE, DEFAULT_PRODUCT_TYPE)
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    if product_type == PRODUCT_MARINE_ZONE:
        zone_id = entry.data[CONF_ZONE_ID]
        return DeviceInfo(
            identifiers={(DOMAIN, zone_id.lower())},
            name=f"{name} {zone_id}",
            manufacturer="NOAA / NWS",
            model="Coastal Waters Forecast",
            configuration_url=forecast_url(zone_id),
        )
    raise ValueError(f"Unsupported product type: {product_type}")
