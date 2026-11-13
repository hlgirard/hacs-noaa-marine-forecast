"""Config flow for the NOAA Marine Forecast integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
import homeassistant.helpers.config_validation as cv

from .api import (
    NOAAError,
    NOAAForecastError,
    async_fetch_buoy,
    async_fetch_station_metadata,
    async_fetch_forecast,
    forecast_url,
    normalize_buoy_station_id,
    normalize_tide_station_id,
)
from .const import (
    CONF_NAME,
    CONF_PRODUCT_TYPE,
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_ZONE_ID,
    CONF_DATUM,
    CONF_LEVEL_UNIT,
    COOPS_DATUMS,
    LEVEL_UNIT_AUTO,
    LEVEL_UNITS,
    DEFAULT_DATUM,
    PRODUCT_BUOY,
    PRODUCT_TIDE_STATION,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
    PRODUCT_MARINE_ZONE,
)
from .buoy import parse_realtime
from .parser import parse_forecast
from .tides import parse_station_info
from .products import COORDINATOR_FACTORIES

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ZONE_ID): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


STEP_TIDE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATION_ID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_DATUM, default=DEFAULT_DATUM): vol.In(COOPS_DATUMS),
        vol.Optional(CONF_LEVEL_UNIT, default=LEVEL_UNIT_AUTO): vol.In(LEVEL_UNITS),
    }
)
STEP_BUOY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATION_ID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)


async def _async_validate_zone(hass, zone_id: str) -> str | None:
    """Return an error message when the zone cannot be used."""
    try:
        text = await async_fetch_forecast(hass, zone_id)
    except NOAAForecastError as err:
        return str(err)

    product = parse_forecast(text, zone_id)
    if not product.zones:
        return (
            f"No marine zone block found for {zone_id.upper()} in "
            f"{forecast_url(zone_id)}"
        )
    if product.zone_id and product.zone_id not in product.zones:
        return (
            f"{zone_id.upper()} is not part of this product "
            f"({', '.join(product.zones)})"
        )
    return None


class MarineForecastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NOAA Marine Forecast."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a product type (skipped when only one exists)."""
        product_types = list(COORDINATOR_FACTORIES)
        if len(product_types) == 1:
            return await getattr(self, f"async_step_{product_types[0]}")()
        return self.async_show_menu(step_id="user", menu_options=product_types)

    async def async_step_marine_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a NOAA coastal marine forecast zone."""
        errors: dict[str, str] = {}

        if user_input is not None:
            zone_id = user_input[CONF_ZONE_ID].strip().upper()
            name = user_input.get(CONF_NAME) or DEFAULT_NAME

            error = await _async_validate_zone(self.hass, zone_id)
            if error:
                _LOGGER.warning("Rejecting marine zone %s: %s", zone_id, error)
                errors["base"] = "invalid_zone"
            else:
                await self.async_set_unique_id(f"{PRODUCT_MARINE_ZONE}:{zone_id.lower()}")
                self._abort_if_unique_id_configured()
                title = f"{name} {zone_id}"
                self.context["title_placeholders"] = {"zone": zone_id}
                return self.async_create_entry(
                    title=title, data={
                        CONF_PRODUCT_TYPE: PRODUCT_MARINE_ZONE,
                        CONF_ZONE_ID: zone_id,
                        CONF_NAME: name,
                    },
                )

        return self.async_show_form(
            step_id=PRODUCT_MARINE_ZONE,
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"example": "ANZ230"},
        )

    async def async_step_tide_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a CO-OPS tide station."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info = None
            station_id = ""
            try:
                station_id = normalize_tide_station_id(user_input[CONF_STATION_ID])
            except NOAAError as err:
                _LOGGER.warning("Rejecting tide station: %s", err)
                errors["base"] = "invalid_station"
            else:
                try:
                    info = parse_station_info(
                        await async_fetch_station_metadata(self.hass, station_id),
                        station_id,
                    )
                except NOAAError as err:
                    _LOGGER.warning("Tide station lookup failed: %s", err)
                    errors["base"] = "cannot_connect"
            if not errors:
                if info is None:
                    errors["base"] = "invalid_station"
                else:
                    await self.async_set_unique_id(
                        f"{PRODUCT_TIDE_STATION}:{station_id}"
                    )
                    self._abort_if_unique_id_configured()
                    name = user_input.get(CONF_NAME) or info.name
                    self.context["title_placeholders"] = {"name": name}
                    return self.async_create_entry(
                        title=f"{name} tides",
                        data={
                            CONF_PRODUCT_TYPE: PRODUCT_TIDE_STATION,
                            CONF_STATION_ID: station_id,
                            CONF_NAME: name,
                            CONF_DATUM: user_input.get(CONF_DATUM, DEFAULT_DATUM),
                            CONF_LEVEL_UNIT: user_input.get(
                                CONF_LEVEL_UNIT, LEVEL_UNIT_AUTO
                            ),
                        },
                    )
        return self.async_show_form(
            step_id=PRODUCT_TIDE_STATION,
            data_schema=STEP_TIDE_SCHEMA,
            errors=errors,
            description_placeholders={"example": "8443970"},
        )

    async def async_step_buoy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an NDBC buoy or coastal weather station."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                station_id = normalize_buoy_station_id(user_input[CONF_STATION_ID])
                parse_realtime(await async_fetch_buoy(self.hass, station_id))
            except NOAAError as err:
                _LOGGER.warning("Rejecting buoy: %s", err)
                errors["base"] = "invalid_station"
            except ValueError as err:
                _LOGGER.warning("Rejecting buoy data: %s", err)
                errors["base"] = "invalid_station"
            else:
                await self.async_set_unique_id(f"{PRODUCT_BUOY}:{station_id.lower()}")
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME) or f"NDBC {station_id}"
                self.context["title_placeholders"] = {"name": name}
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_PRODUCT_TYPE: PRODUCT_BUOY,
                        CONF_STATION_ID: station_id,
                        CONF_NAME: name,
                    },
                )
        return self.async_show_form(
            step_id=PRODUCT_BUOY,
            data_schema=STEP_BUOY_SCHEMA,
            errors=errors,
            description_placeholders={"example": "44013"},
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MarineForecastOptionsFlow(entry)


class MarineForecastOptionsFlow(OptionsFlow):
    """Handle options for NOAA Marine Forecast."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.data.get(CONF_NAME, DEFAULT_NAME)
        interval = self._entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        fields: dict[Any, Any] = {
            vol.Optional(CONF_NAME, default=current): cv.string,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=interval
            ): vol.All(cv.positive_int, vol.Coerce(int)),
        }
        if self._entry.data.get(CONF_PRODUCT_TYPE) == PRODUCT_TIDE_STATION:
            unit = self._entry.options.get(
                CONF_LEVEL_UNIT,
                self._entry.data.get(CONF_LEVEL_UNIT, LEVEL_UNIT_AUTO),
            )
            fields[vol.Optional(CONF_LEVEL_UNIT, default=unit)] = vol.In(LEVEL_UNITS)
        schema = vol.Schema(fields)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "minimum": str(MIN_SCAN_INTERVAL_MINUTES),
            },
        )
