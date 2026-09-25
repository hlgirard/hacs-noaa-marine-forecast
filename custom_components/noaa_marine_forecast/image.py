"""Image platform: shows the highest severity marine flag."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .alerts import format_alert_text
from .assets import load_flag_image
from .const import CONF_NAME, CONF_ZONE_ID, DEFAULT_NAME, DOMAIN
from .coordinator import MarineZoneData
from .flags import FLAG_NONE, FLAG_TITLES

_LOGGER = logging.getLogger(__name__)

UTC = timezone.utc


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the image entity for a config entry."""
    coordinator: DataUpdateCoordinator[MarineZoneData] = (
        hass.data[DOMAIN][entry.entry_id]
    )
    zone_id = entry.data[CONF_ZONE_ID]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    async_add_entities(
        [MarineFlagImage(coordinator, hass, entry, zone_id, name)]
    )


class MarineFlagImage(ImageEntity):
    """An image showing the highest severity marine flag for a zone."""

    _attr_has_entity_name = True
    _attr_translation_key = "alert_flag_image"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[MarineZoneData],
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone_id: str,
        name: str,
    ) -> None:
        """Initialize the image entity."""
        super().__init__(hass)
        self.coordinator = coordinator
        self._zone_id = zone_id
        self._attr_unique_id = f"{zone_id.lower()}_alert_flag_image"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, zone_id.lower())},
            "name": f"{name} {zone_id}",
            "manufacturer": "NOAA / NWS",
            "model": "Coastal Waters Forecast",
        }
        self._flag = FLAG_NONE
        self._lifecycle: str | None = None
        self._asset_missing = False
        self._last_reported: tuple[str, str | None] = (FLAG_NONE, None)
        self._attr_image_last_updated = None

    @property
    def flag(self) -> str:
        """Return the flag key currently displayed."""
        return self._flag

    @property
    def lifecycle(self) -> str | None:
        """Return the lifecycle of the displayed flag."""
        return self._lifecycle

    @property
    def available(self) -> bool:
        """Return True only while a recognized flag image is in force.

        There is no "all clear" image, so the entity reports unavailable when
        no alert matching one of the four flags is active or pending, and when
        the asset for the current flag is missing.

        A stale-but-retained flag still reports available: if the alert API is
        briefly unreachable, blanking the dashboard would hide a warning that
        may well still be in force. The ``alerts_available`` attribute shows
        when the underlying data is stale.
        """
        if self._asset_missing or self._flag == FLAG_NONE:
            return False
        return self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the flag state as attributes.

        ``alert_text`` is a ready made one line summary for dashboard cards.
        The native tile card's ``state_content`` selects an attribute by name
        rather than evaluating a template, so this is what lets a stock tile
        card show the alert without any custom card or Jinja.
        """
        bundle: MarineZoneData | None = self.coordinator.data
        if bundle is None:
            return {}
        return {
            "highest_flag": self._flag,
            "highest_flag_title": FLAG_TITLES.get(self._flag, self._flag),
            "lifecycle": self._lifecycle,
            "active_flags": list(bundle.alerts.active_flags),
            "pending_flags": list(bundle.alerts.pending_flags),
            "flag_combination": bundle.alerts.combination,
            "alerts_available": bundle.alerts_available,
            "alert_text": format_alert_text(bundle.alerts, dt_util.DEFAULT_TIME_ZONE),
        }

    def _apply(self) -> bool:
        """Update the displayed image. Returns True when it changed."""
        data: MarineZoneData | None = self.coordinator.data
        if data is None:
            return False
        bundle = data.alerts
        flag = bundle.highest_flag or FLAG_NONE
        lifecycle = bundle.highest_lifecycle

        if flag == FLAG_NONE:
            # Nothing to show. Keep the last image loaded so the entity can
            # return to it if the same flag comes back, but report unavailable.
            self._flag = FLAG_NONE
            self._lifecycle = None
            return self._flag_changed()

        try:
            image = load_flag_image(flag)
        except FileNotFoundError as err:
            if not self._asset_missing:
                _LOGGER.error(
                    "Marine flag image unavailable for %s: %s", flag, err
                )
            self._asset_missing = True
            self._flag = flag
            self._lifecycle = lifecycle
            return self._flag_changed()

        self._asset_missing = False
        self._flag = flag
        self._lifecycle = lifecycle
        self._attr_content_type = image.content_type
        self._attr_image_last_updated = datetime.now(UTC)
        return self._flag_changed()

    def _flag_changed(self) -> bool:
        """Return True when the displayed flag differs from the last state."""
        changed = (self._flag, self._lifecycle) != self._last_reported
        if changed:
            self._last_reported = (self._flag, self._lifecycle)
        return changed

    async def async_added_to_hass(self) -> None:
        """Register the coordinator listener."""
        await super().async_added_to_hass()
        self._apply()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._apply():
            self.async_write_ha_state()

    def image(self) -> bytes:
        """Return the image bytes for the current flag."""
        return load_flag_image(self._flag).content
