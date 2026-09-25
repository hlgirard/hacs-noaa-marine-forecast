"""Data update coordinator for NOAA marine forecasts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .alerts import AlertBundle, build_alert_bundle
from .api import (
    NOAAForecastError,
    async_fetch_alerts,
    async_fetch_forecast,
    async_fetch_zone_alerts,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_ZONE_ID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .parser import ForecastPeriod, ForecastProduct, parse_forecast, select_now_next

_LOGGER = logging.getLogger(__name__)

UTC = timezone.utc


@dataclass(frozen=True)
class MarineZoneData:
    """Everything the entities need for one marine zone."""

    zone_id: str
    forecast: ForecastProduct
    alerts: AlertBundle
    now_period: ForecastPeriod | None
    next_period: ForecastPeriod | None
    selection_method: str
    fetched_at: datetime
    alerts_available: bool = True
    alerts_updated_at: datetime | None = None

    def period_for(self, offset_days: int, part: str) -> ForecastPeriod | None:
        """Return the period for a day offset (0 = today) and part."""
        base = self.forecast.issued.date() if self.forecast.issued else None
        if base is None:
            return None
        lookup = self.forecast.periods_by_part()
        return lookup.get((base + timedelta(days=offset_days), part))


class MarineForecastCoordinator(DataUpdateCoordinator[MarineZoneData]):
    """Coordinator for a single marine zone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator for a config entry."""
        self.zone_id: str = entry.data[CONF_ZONE_ID]
        # Retained across refreshes so a failed alert request never silently
        # clears an in-force marine warning.
        self._last_alerts: AlertBundle | None = None
        self._last_alerts_at: datetime | None = None

        raw_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DEFAULT_NAME} {self.zone_id}",
            update_interval=timedelta(
                minutes=max(int(raw_interval), MIN_SCAN_INTERVAL_MINUTES)
            ),
            config_entry=entry,
        )

    async def _async_update_data(self) -> MarineZoneData:
        """Fetch the forecast and alerts for the configured zone."""
        zone_id = self.zone_id
        try:
            forecast_text = await async_fetch_forecast(self.hass, zone_id)
        except NOAAForecastError as err:
            raise UpdateFailed(
                f"Error fetching forecast for {zone_id}: {err}"
            ) from err

        product = parse_forecast(forecast_text, zone_id)
        if not product.periods:
            _LOGGER.warning(
                "No forecast periods parsed for %s; raw header: %s",
                zone_id,
                product.raw_header,
            )

        active_props: list[dict] = []
        zone_props: list[dict] = []
        alerts_available = True
        try:
            active_props = await async_fetch_alerts(self.hass, zone_id)
            zone_props = await async_fetch_zone_alerts(self.hass, zone_id)
        except NOAAForecastError as err:
            # The forecast is still useful without alerts, so keep the last
            # known alert state rather than reporting a false "all clear".
            alerts_available = False
            _LOGGER.warning("Error fetching alerts for %s: %s", zone_id, err)

        fetched_at = datetime.now(UTC)
        if alerts_available:
            self._last_alerts = build_alert_bundle(
                active_props, zone_props, fetched_at
            )
            self._last_alerts_at = fetched_at
        bundle = self._last_alerts or build_alert_bundle([], [], fetched_at)

        now_period, next_period, method = select_now_next(
            product,
            fetched_at,
            dt_util.get_time_zone(self.hass.config.time_zone),
        )
        return MarineZoneData(
            zone_id=zone_id,
            forecast=product,
            alerts=bundle,
            now_period=now_period,
            next_period=next_period,
            selection_method=method,
            fetched_at=fetched_at,
            alerts_available=alerts_available,
            alerts_updated_at=self._last_alerts_at,
        )


async def async_setup_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> MarineForecastCoordinator:
    """Create and first-refresh the coordinator for a config entry."""
    coordinator = MarineForecastCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    return coordinator


__all__ = [
    "DOMAIN",
    "MarineForecastCoordinator",
    "MarineZoneData",
    "async_setup_coordinator",
]
