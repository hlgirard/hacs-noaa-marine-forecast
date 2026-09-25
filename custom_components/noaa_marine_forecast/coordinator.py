"""Data update coordinator for NOAA marine forecasts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

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


async def async_setup_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> DataUpdateCoordinator[MarineZoneData]:
    """Create the coordinator for a config entry."""
    zone_id = entry.data[CONF_ZONE_ID]
    raw_interval = entry.options.get(
        "scan_interval",
        entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL_MINUTES),
    )
    interval = timedelta(minutes=max(int(raw_interval), MIN_SCAN_INTERVAL_MINUTES))
    coordinator: DataUpdateCoordinator[MarineZoneData] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DEFAULT_NAME} {zone_id}",
        update_interval=interval,
        config_entry=entry,
    )

    # Retained across refreshes so a failed alert request never silently
    # clears an in-force marine warning.
    last_alerts: AlertBundle | None = None
    last_alerts_at: datetime | None = None

    async def _async_update_data() -> MarineZoneData:
        nonlocal last_alerts, last_alerts_at
        try:
            forecast_text = await async_fetch_forecast(hass, zone_id)
        except NOAAForecastError as err:
            raise UpdateFailed(f"Error fetching forecast for {zone_id}: {err}") from err

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
            active_props = await async_fetch_alerts(hass, zone_id)
            zone_props = await async_fetch_zone_alerts(hass, zone_id)
        except NOAAForecastError as err:
            # The forecast is still useful without alerts, so keep the last
            # known alert state rather than reporting a false "all clear".
            alerts_available = False
            _LOGGER.warning("Error fetching alerts for %s: %s", zone_id, err)

        fetched_at = datetime.now(UTC)
        if alerts_available:
            last_alerts = build_alert_bundle(active_props, zone_props, fetched_at)
            last_alerts_at = fetched_at
        bundle = last_alerts or build_alert_bundle([], [], fetched_at)
        now_period, next_period, method = select_now_next(
            product,
            fetched_at,
            dt_util.get_time_zone(hass.config.time_zone),
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
            alerts_updated_at=last_alerts_at,
        )

    await coordinator.async_config_entry_first_refresh()
    return coordinator


__all__ = ["DOMAIN", "MarineZoneData", "async_setup_coordinator"]
