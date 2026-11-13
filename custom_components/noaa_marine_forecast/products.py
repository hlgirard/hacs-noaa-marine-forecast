"""Registry of supported product types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import PRODUCT_MARINE_ZONE
from .coordinator import async_setup_coordinator

CoordinatorFactory = Callable[
    [HomeAssistant, ConfigEntry], Awaitable[DataUpdateCoordinator]
]

COORDINATOR_FACTORIES: dict[str, CoordinatorFactory] = {
    PRODUCT_MARINE_ZONE: async_setup_coordinator,
}
