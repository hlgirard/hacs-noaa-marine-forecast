"""Registry of supported product types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import PRODUCT_BUOY, PRODUCT_MARINE_ZONE, PRODUCT_TIDE_STATION
from .coordinator import async_setup_coordinator
from .obs_coordinators import async_setup_buoy_coordinator, async_setup_tide_coordinator

CoordinatorFactory = Callable[
    [HomeAssistant, ConfigEntry], Awaitable[DataUpdateCoordinator]
]

COORDINATOR_FACTORIES: dict[str, CoordinatorFactory] = {
    PRODUCT_MARINE_ZONE: async_setup_coordinator,
    PRODUCT_TIDE_STATION: async_setup_tide_coordinator,
    PRODUCT_BUOY: async_setup_buoy_coordinator,
}
