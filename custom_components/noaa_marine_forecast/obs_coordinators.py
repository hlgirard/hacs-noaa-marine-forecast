"""Coordinators for tide stations (CO-OPS) and buoys (NDBC)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    NOAAError,
    async_fetch_buoy,
    async_fetch_coops_json,
    coops_latest_url,
    coops_predictions_url,
)
from .buoy import BuoyData, build_buoy_data
from .const import (
    CONF_DATUM,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_DATUM,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .tides import (
    OBSERVATION_PRODUCTS,
    TideData,
    parse_latest_reading,
    parse_predictions,
)

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


def _interval(entry: ConfigEntry) -> timedelta:
    raw = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
    )
    return timedelta(minutes=max(int(raw), MIN_SCAN_INTERVAL_MINUTES))


class TideCoordinator(DataUpdateCoordinator[TideData]):
    """Coordinator for one CO-OPS tide station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.station_name: str = entry.data.get(CONF_NAME) or self.station_id
        self.datum: str = entry.data.get(CONF_DATUM, DEFAULT_DATUM)
        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA tide station {self.station_id}",
            update_interval=_interval(entry),
            config_entry=entry,
        )

    async def _async_update_data(self) -> TideData:
        now = datetime.now(UTC)
        urls = {
            product: coops_latest_url(self.station_id, product, self.datum)
            for product in OBSERVATION_PRODUCTS
        }
        pred_url = coops_predictions_url(
            self.station_id, self.datum, now - timedelta(hours=12)
        )
        results = await asyncio.gather(
            *(async_fetch_coops_json(self.hass, url) for url in urls.values()),
            async_fetch_coops_json(self.hass, pred_url),
            return_exceptions=True,
        )
        *obs_results, pred_result = results

        failures = [r for r in results if isinstance(r, Exception)]
        if len(failures) == len(results):
            raise UpdateFailed(
                f"Error fetching tide data for {self.station_id}: {failures[0]}"
            ) from failures[0]

        readings = {}
        for product, result in zip(urls, obs_results):
            if isinstance(result, Exception):
                _LOGGER.debug("CO-OPS %s failed: %s", product, result)
                continue
            reading = parse_latest_reading(result, product)
            if reading is not None:
                readings[product] = reading

        predictions = () if isinstance(pred_result, Exception) else parse_predictions(
            pred_result
        )
        if not readings and not predictions:
            raise UpdateFailed(
                f"CO-OPS station {self.station_id} returned no data"
            )
        return TideData(
            station_id=self.station_id,
            name=self.station_name,
            fetched_at=now,
            readings=readings,
            predictions=predictions,
            datum=self.datum,
        )


class BuoyCoordinator(DataUpdateCoordinator[BuoyData]):
    """Coordinator for one NDBC station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.station_name: str = entry.data.get(CONF_NAME) or self.station_id
        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA buoy {self.station_id}",
            update_interval=_interval(entry),
            config_entry=entry,
        )

    async def _async_update_data(self) -> BuoyData:
        try:
            text = await async_fetch_buoy(self.hass, self.station_id)
            return build_buoy_data(
                self.station_id, self.station_name, text, datetime.now(UTC)
            )
        except NOAAError as err:
            raise UpdateFailed(
                f"Error fetching buoy {self.station_id}: {err}"
            ) from err
        except ValueError as err:
            raise UpdateFailed(
                f"Unreadable data for buoy {self.station_id}: {err}"
            ) from err


async def async_setup_tide_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> TideCoordinator:
    """Create and first-refresh the tide coordinator."""
    coordinator = TideCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    return coordinator


async def async_setup_buoy_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> BuoyCoordinator:
    """Create and first-refresh the buoy coordinator."""
    coordinator = BuoyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    return coordinator
