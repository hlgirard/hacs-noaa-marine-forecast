"""NOAA Marine Forecast integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_PRODUCT_TYPE,
    CONF_ZONE_ID,
    DEFAULT_PRODUCT_TYPE,
    DOMAIN,
    PLATFORMS,
    PRODUCT_PLATFORMS,
)
from .products import COORDINATOR_FACTORIES


def _platforms(entry: ConfigEntry) -> list[str]:
    """Return the platforms for the entry's product type."""
    return PRODUCT_PLATFORMS[entry.data.get(CONF_PRODUCT_TYPE, DEFAULT_PRODUCT_TYPE)]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries (v1 had no product type)."""
    if entry.version == 1:
        zone_id = entry.data[CONF_ZONE_ID]
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_PRODUCT_TYPE: DEFAULT_PRODUCT_TYPE},
            unique_id=f"{DEFAULT_PRODUCT_TYPE}:{zone_id.lower()}",
            version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NOAA Marine Forecast from a config entry."""
    product_type = entry.data.get(CONF_PRODUCT_TYPE, DEFAULT_PRODUCT_TYPE)
    entry.runtime_data = await COORDINATOR_FACTORIES[product_type](hass, entry)
    # Listen for config updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms(entry)
    )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


__all__ = ["DOMAIN", "PLATFORMS", "Platform", "async_setup_entry"]
