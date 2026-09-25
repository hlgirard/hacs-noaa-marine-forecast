"""Real-Home-Assistant tests for the config and options flow.

The flow runs against Home Assistant's real ``ConfigFlow`` machinery: the form
schema is validated by voluptuous, ``async_set_unique_id`` and
``_abort_if_unique_id_configured`` use the real entry registry, and
``async_create_entry`` drives the real config entry state machine.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import NOW, ZONE, ZONE_NAME, cap_alert

from custom_components.noaa_marine_forecast.api import forecast_url
from custom_components.noaa_marine_forecast.const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_ZONE_ID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)
from custom_components.noaa_marine_forecast.coordinator import (
    MarineForecastCoordinator,
)

OTHER_ZONE = "ANZ231"


async def start_user_flow(hass):
    """Begin the user step and return the form result."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )


class TestUserStep:
    """The initial form."""

    async def test_shows_form(self, hass) -> None:
        result = await start_user_flow(hass)
        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert not result["errors"]
        keys = {str(k) for k in result["data_schema"].schema}
        assert keys == {CONF_ZONE_ID, CONF_NAME}

    async def test_creates_entry(self, hass, mock_noaa) -> None:
        mock_noaa()
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        await hass.async_block_till_done()

        assert result["type"] == "create_entry"
        assert result["title"] == f"{ZONE_NAME} {ZONE}"
        assert result["data"] == {CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}

    async def test_normalizes_zone_id_case(self, hass, mock_noaa) -> None:
        """A lower case zone is upper cased before it is stored."""
        mock_noaa()
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: "  anz230  ", CONF_NAME: ZONE_NAME}
        )
        await hass.async_block_till_done()
        assert result["data"][CONF_ZONE_ID] == ZONE

    async def test_name_defaults(self, hass, mock_noaa) -> None:
        mock_noaa()
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: ZONE}
        )
        await hass.async_block_till_done()
        assert result["data"][CONF_NAME] == DEFAULT_NAME

    async def test_sets_unique_id(self, hass, mock_noaa) -> None:
        mock_noaa()
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        await hass.async_block_till_done()
        assert result["result"].unique_id == ZONE.lower()


class TestUserStepValidation:
    """Rejecting zones that cannot produce a forecast."""

    async def test_rejects_unreachable_zone(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(forecast_url("ANZ999"), status=404)
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: "ANZ999", CONF_NAME: "Nowhere"}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_zone"}
        assert not hass.config_entries.async_entries(DOMAIN)

    async def test_rejects_zone_absent_from_product(self, hass, aioclient_mock) -> None:
        """A product for a different zone does not validate this zone."""
        from conftest import _PRODUCTS

        aioclient_mock.get(forecast_url(OTHER_ZONE), text=_PRODUCTS.ANZ230_PRODUCT)
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: OTHER_ZONE, CONF_NAME: "Elsewhere"}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_zone"}
        assert not hass.config_entries.async_entries(DOMAIN)

    async def test_blank_zone_is_rejected_by_schema(self, hass) -> None:
        result = await start_user_flow(hass)
        with pytest.raises(Exception):
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_NAME: ZONE_NAME}
            )


class TestDuplicate:
    """One config entry per marine zone."""

    async def test_aborts_when_already_configured(self, hass, aioclient_mock) -> None:
        from conftest import _PRODUCTS

        aioclient_mock.get(forecast_url(ZONE), text=_PRODUCTS.ANZ230_PRODUCT)
        MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME},
            unique_id=ZONE.lower(),
        ).add_to_hass(hass)

        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: ZONE, CONF_NAME: "Second"}
        )
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"


class TestOptionsFlow:
    """The options flow, reachable from the entry."""

    @pytest.fixture
    def entry(self, hass, mock_noaa):
        mock_noaa()
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME},
            unique_id=ZONE.lower(),
        )
        entry.add_to_hass(hass)
        assert entry.unique_id == ZONE.lower()
        return entry

    def test_get_options_flow_is_a_staticmethod(self, hass) -> None:
        """Home Assistant calls this on the class, with no instance."""
        from custom_components.noaa_marine_forecast.config_flow import (
            MarineForecastConfigFlow,
        )

        assert isinstance(
            MarineForecastConfigFlow.__dict__["async_get_options_flow"],
            staticmethod,
        ), (
            "async_get_options_flow must be a staticmethod; Home Assistant "
            "calls it on the class"
        )

    def test_options_flow_keeps_config_entry(self, hass, entry) -> None:
        from homeassistant.config_entries import OptionsFlow

        from custom_components.noaa_marine_forecast.config_flow import (
            MarineForecastConfigFlow,
        )

        flow = MarineForecastConfigFlow.async_get_options_flow(entry)
        assert isinstance(flow, OptionsFlow)
        assert flow._entry is entry

    async def test_shows_current_values(self, hass, entry) -> None:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"
        assert result["step_id"] == "init"
        defaults = {
            str(k): k.default() for k in result["data_schema"].schema if k.default
        }
        assert defaults[CONF_NAME] == ZONE_NAME
        assert defaults[CONF_SCAN_INTERVAL] == DEFAULT_SCAN_INTERVAL_MINUTES

    async def test_saves_options(self, hass, entry) -> None:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_NAME: "Renamed", CONF_SCAN_INTERVAL: 25}
        )
        await hass.async_block_till_done()

        assert result["type"] == "create_entry"
        assert entry.options[CONF_SCAN_INTERVAL] == 25
        assert entry.options[CONF_NAME] == "Renamed"

    async def test_changed_interval_applies_without_restart(
        self, hass, entry
    ) -> None:
        """Saving a new interval must reach the running coordinator.

        The interval is read from the entry options when the coordinator is
        built, so the entry has to reload when options change. Without an
        update listener the new value is stored but ignored until the next
        Home Assistant restart.
        """
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.data[DOMAIN][entry.entry_id].update_interval == timedelta(
            minutes=DEFAULT_SCAN_INTERVAL_MINUTES
        )

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_NAME: ZONE_NAME, CONF_SCAN_INTERVAL: 45}
        )
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.update_interval == timedelta(minutes=45), (
            "the new interval was stored but the coordinator still polls on "
            f"{coordinator.update_interval}"
        )


class TestScanInterval:
    """How the options value reaches the coordinator."""

    @pytest.mark.parametrize(
        ("configured", "expected_minutes"),
        [
            (25, 25),
            (1, 1),
            # Below the documented minimum the coordinator clamps rather than
            # rejecting, so the form and the runtime agree on the floor.
            (0, MIN_SCAN_INTERVAL_MINUTES),
        ],
    )
    def test_coordinator_interval(
        self, hass, configured, expected_minutes
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME},
            options={CONF_SCAN_INTERVAL: configured},
        )
        entry.add_to_hass(hass)
        coordinator = MarineForecastCoordinator(hass, entry)
        assert coordinator.update_interval == timedelta(minutes=expected_minutes)

    async def test_options_flow_accepts_zero(self, hass, mock_noaa) -> None:
        """Pins the current behaviour: the form does not enforce the minimum.

        ``cv.positive_int`` allows 0, so the options flow stores it and the
        coordinator clamps it to ``MIN_SCAN_INTERVAL_MINUTES`` afterwards. The
        UI label says "minimum 1" but the form does not enforce it.
        """
        mock_noaa()
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME},
            unique_id=ZONE.lower(),
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_NAME: ZONE_NAME, CONF_SCAN_INTERVAL: 0}
        )
        await hass.async_block_till_done()

        assert result["type"] == "create_entry"
        assert entry.options[CONF_SCAN_INTERVAL] == 0
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.update_interval == timedelta(
            minutes=MIN_SCAN_INTERVAL_MINUTES
        )


class TestEndToEnd:
    """Flow, then real setup, then the alert-driven image."""

    async def test_flow_to_working_entities(self, hass, mock_noaa) -> None:
        mock_noaa(
            active=[
                cap_alert(
                    "Storm Warning",
                    "e2e",
                    onset=NOW - timedelta(hours=1),
                    ends=NOW + timedelta(hours=6),
                )
            ]
        )
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        await hass.async_block_till_done()

        assert result["type"] == "create_entry"
        entry = result["result"]
        assert entry.state is ConfigEntryState.LOADED

        flag_sensor = hass.states.get(
            "sensor.boston_harbor_anz230_alert_flags"
        )
        assert flag_sensor is not None
        assert flag_sensor.state == "storm_warning:active"
        assert (
            hass.states.get("image.boston_harbor_anz230_alert_flag").state
            != "unavailable"
        )

    async def test_unload_removes_entities(self, hass, mock_noaa) -> None:
        mock_noaa()
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.boston_harbor_anz230_alert_flags")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # The entity registry entry survives an unload, so Home Assistant
        # leaves a restored placeholder rather than deleting the state.
        assert entry.entry_id not in hass.data.get(DOMAIN, {})
        assert entry.state is ConfigEntryState.NOT_LOADED
        leftover = hass.states.get("sensor.boston_harbor_anz230_alert_flags")
        assert leftover is None or leftover.state == "unavailable"
