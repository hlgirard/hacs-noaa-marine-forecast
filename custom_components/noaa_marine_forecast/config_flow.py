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

from .api import NOAAForecastError, async_fetch_forecast, forecast_url
from .const import (
    CONF_NAME,
    CONF_PRODUCT_TYPE,
    CONF_SCAN_INTERVAL,
    CONF_ZONE_ID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
    PRODUCT_MARINE_ZONE,
)
from .parser import parse_forecast
from .products import COORDINATOR_FACTORIES

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ZONE_ID): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
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
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current): cv.string,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=interval
                ): vol.All(cv.positive_int, vol.Coerce(int)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "minimum": str(MIN_SCAN_INTERVAL_MINUTES),
            },
        )
