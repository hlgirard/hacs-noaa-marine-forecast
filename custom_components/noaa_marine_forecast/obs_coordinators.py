"""Coordinators for tide stations (CO-OPS) and buoys (NDBC)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    NOAAError,
    async_fetch_buoy,
    async_fetch_coops_json,
    coops_latest_url,
    coops_predictions_url,
)
from .buoy import BuoyData, build_buoy_data
from .device import entry_name
from .const import (
    CONF_DATUM,
    CONF_LEVEL_UNIT,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_DATUM,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    LEVEL_UNIT_AUTO,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .tides import (
    OBSERVATION_PRODUCTS,
    Reading,
    TideData,
    TidePrediction,
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
        self.station_name: str = entry_name(entry)
        self.datum: str = entry.data.get(CONF_DATUM, DEFAULT_DATUM)
        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA tide station {self.station_id}",
            update_interval=_interval(entry),
            config_entry=entry,
        )
        self._last_readings: dict[str, Reading] = {}
        self._last_predictions: tuple[TidePrediction, ...] = ()
        self._rollover_cancel: CALLBACK_TYPE | None = None

    def _level_unit(self) -> str:
        """Resolve the level unit: entry option, else Home Assistant's units."""
        entry = self.config_entry
        choice = entry.options.get(
            CONF_LEVEL_UNIT, entry.data.get(CONF_LEVEL_UNIT, LEVEL_UNIT_AUTO)
        )
        if choice in ("m", "ft"):
            return choice
        imperial = self.hass.config.units.length_unit == UnitOfLength.MILES
        return "ft" if imperial else "m"

    async def _async_update_data(self) -> TideData:
        now = datetime.now(UTC)
        try:
            urls = {
                product: coops_latest_url(self.station_id, product, self.datum)
                for product in OBSERVATION_PRODUCTS
            }
            pred_url = coops_predictions_url(
                self.station_id, self.datum, now - timedelta(hours=12)
            )
        except NOAAError as err:
            raise UpdateFailed(f"Invalid tide station configuration: {err}") from err
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

        readings: dict[str, Reading] = {}
        for product, result in zip(urls, obs_results):
            reading = None
            if isinstance(result, Exception):
                _LOGGER.debug("CO-OPS %s failed: %s", product, result)
            else:
                reading = parse_latest_reading(result, product)
            # Keep the previous value across a gap; sensors expire it by age.
            reading = reading or self._last_readings.get(product)
            if reading is not None:
                readings[product] = reading

        predictions: tuple[TidePrediction, ...] = ()
        if not isinstance(pred_result, Exception):
            predictions = parse_predictions(pred_result)
        if not any(p.time > now for p in predictions) and any(
            p.time > now for p in self._last_predictions
        ):
            predictions = self._last_predictions

        if not readings and not predictions:
            raise UpdateFailed(
                f"CO-OPS station {self.station_id} returned no data"
            )
        self._last_readings = readings
        self._last_predictions = predictions
        data = TideData(
            station_id=self.station_id,
            name=self.station_name,
            fetched_at=now,
            readings=readings,
            predictions=predictions,
            datum=self.datum,
            level_unit=self._level_unit(),
        )
        self._schedule_rollover(data, now)
        return data

    @callback
    def _schedule_rollover(self, data: TideData, now: datetime) -> None:
        """Re-render entities when the next predicted tide passes."""
        self._cancel_rollover()
        upcoming = data.upcoming_tide(now)
        if upcoming is None:
            return
        self._rollover_cancel = async_track_point_in_utc_time(
            self.hass, self._handle_rollover, upcoming.time + timedelta(seconds=1)
        )

    @callback
    def _handle_rollover(self, _now: datetime) -> None:
        """A tide time passed: recompute states from the same data."""
        self._rollover_cancel = None
        if self.data is not None:
            self._schedule_rollover(self.data, datetime.now(UTC))
            self.async_update_listeners()

    def _cancel_rollover(self) -> None:
        if self._rollover_cancel is not None:
            self._rollover_cancel()
            self._rollover_cancel = None

    async def async_shutdown(self) -> None:
        """Cancel the rollover timer before shutting down."""
        self._cancel_rollover()
        await super().async_shutdown()


class BuoyCoordinator(DataUpdateCoordinator[BuoyData]):
    """Coordinator for one NDBC station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.station_name: str = entry_name(entry)
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
