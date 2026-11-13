"""Real-Home-Assistant tests for the tide station and buoy products."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.noaa_marine_forecast.api import (
    coops_station_url,
    ndbc_url,
)
from custom_components.noaa_marine_forecast.const import (
    CONF_DATUM,
    CONF_NAME,
    CONF_PRODUCT_TYPE,
    CONF_STATION_ID,
    DOMAIN,
)

DATA = Path(__file__).resolve().parent.parent / "data"
TIDE_ID = "8443970"
BUOY_ID = "44013"


def _text(name: str) -> str:
    return (DATA / name).read_text()


@pytest.fixture
def mock_coops(aioclient_mock):
    """Mock the CO-OPS metadata and data endpoints with real captures."""

    def _mock(*, water_level: str = "coops_water_level.json") -> None:
        aioclient_mock.get(coops_station_url(TIDE_ID), text=_text("coops_station.json"))
        for product, fixture in {
            "water_level": water_level,
            "air_temperature": "coops_air_temperature.json",
            "water_temperature": "coops_no_data.json",
            "air_pressure": "coops_no_data.json",
            "wind": "coops_no_data.json",
            "predictions": "coops_hilo.json",
        }.items():
            aioclient_mock.get(
                re.compile(rf".*datagetter\?.*product={product}(&|$).*"),
                text=_text(fixture),
            )

    return _mock


@pytest.fixture
def mock_ndbc(aioclient_mock):
    def _mock() -> None:
        aioclient_mock.get(ndbc_url(BUOY_ID), text=_text("ndbc_44013.txt"))

    return _mock


def _entity_id(hass, domain_prefix: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{domain_prefix}_{key}"
    )


async def _configure(hass, step: str, user_input: dict):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


class TestTideStation:
    async def test_flow_creates_entry_with_station_name(self, hass, mock_coops) -> None:
        mock_coops()
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        assert result["type"] == "create_entry"
        assert result["title"] == "Boston tides"
        assert result["data"] == {
            CONF_PRODUCT_TYPE: "tide_station",
            CONF_STATION_ID: TIDE_ID,
            CONF_NAME: "Boston",
            CONF_DATUM: "MLLW",
        }
        assert result["result"].unique_id == f"tide_station:{TIDE_ID}"
        assert result["result"].state is ConfigEntryState.LOADED

    @pytest.mark.parametrize("bad", ["abc", "123", "84439700"])
    async def test_flow_rejects_malformed_id(self, hass, bad) -> None:
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: bad})
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_station"}

    async def test_flow_rejects_unknown_station(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(
            coops_station_url("9999999"),
            json={"errorMsg": "No station was found for id 9999999", "errorCode": 404},
        )
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: "9999999"})
        assert result["errors"] == {"base": "invalid_station"}

    async def test_flow_reports_unreachable(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(coops_station_url(TIDE_ID), status=500)
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_duplicate_aborts(self, hass, mock_coops) -> None:
        mock_coops()
        await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"

    async def test_entities_and_states(self, hass, mock_coops, freezer) -> None:
        freezer.move_to("2026-11-13 05:00:00+00:00")
        mock_coops()
        await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        prefix = f"tide_{TIDE_ID}"

        level = hass.states.get(_entity_id(hass, prefix, "water_level"))
        assert float(level.state) == pytest.approx(3.251)
        assert level.attributes["datum"] == "MLLW"
        assert hass.states.get(_entity_id(hass, prefix, "tide_state")).state == "rising"
        assert (
            hass.states.get(_entity_id(hass, prefix, "next_high_tide")).state
            == "2026-11-13T06:30:00+00:00"
        )
        assert (
            hass.states.get(_entity_id(hass, prefix, "next_low_tide")).state
            == "2026-11-13T12:20:00+00:00"
        )
        assert float(
            hass.states.get(_entity_id(hass, prefix, "air_temperature")).state
        ) == pytest.approx(5.4)
        station = hass.states.get(_entity_id(hass, prefix, "station_id"))
        assert station.state == TIDE_ID
        assert station.attributes["station_name"] == "Boston"
        assert (
            hass.states.get(_entity_id(hass, prefix, "checked_at")).state
            == "2026-11-13T05:00:00+00:00"
        )
        # Products the station did not return data for create no entities.
        assert _entity_id(hass, prefix, "wind_speed") is None
        assert _entity_id(hass, prefix, "water_temperature") is None

    async def test_station_without_water_level(self, hass, mock_coops) -> None:
        mock_coops(water_level="coops_no_data.json")
        await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        prefix = f"tide_{TIDE_ID}"
        assert _entity_id(hass, prefix, "water_level") is None
        assert _entity_id(hass, prefix, "next_high_tide") is not None

    async def test_setup_retries_when_no_data(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(re.compile(r".*datagetter.*"), text=_text("coops_no_data.json"))
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={
                CONF_PRODUCT_TYPE: "tide_station",
                CONF_STATION_ID: TIDE_ID,
                CONF_NAME: "Boston",
                CONF_DATUM: "MLLW",
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_RETRY

    async def test_unload(self, hass, mock_coops) -> None:
        mock_coops()
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        entry = result["result"]
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ConfigEntryState.NOT_LOADED


class TestBuoy:
    async def test_flow_creates_entry(self, hass, mock_ndbc) -> None:
        mock_ndbc()
        result = await _configure(hass, "buoy", {CONF_STATION_ID: "44013"})
        assert result["type"] == "create_entry"
        assert result["title"] == "NDBC 44013"
        assert result["result"].unique_id == f"buoy:{BUOY_ID}"
        assert result["result"].state is ConfigEntryState.LOADED

    async def test_flow_normalizes_case(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(ndbc_url("BUZM3"), text=_text("ndbc_44013.txt"))
        result = await _configure(hass, "buoy", {CONF_STATION_ID: "buzm3"})
        assert result["data"][CONF_STATION_ID] == "BUZM3"

    async def test_flow_rejects_missing_station(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(ndbc_url("00000"), status=404)
        result = await _configure(hass, "buoy", {CONF_STATION_ID: "00000"})
        assert result["errors"] == {"base": "invalid_station"}

    async def test_flow_rejects_non_ndbc_body(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(ndbc_url("12345"), text="<html>oops</html>")
        result = await _configure(hass, "buoy", {CONF_STATION_ID: "12345"})
        assert result["errors"] == {"base": "invalid_station"}

    async def test_flow_rejects_malformed_id(self, hass) -> None:
        result = await _configure(hass, "buoy", {CONF_STATION_ID: "no way!"})
        assert result["errors"] == {"base": "invalid_station"}

    async def test_entities_and_states(self, hass, mock_ndbc) -> None:
        mock_ndbc()
        await _configure(hass, "buoy", {CONF_STATION_ID: BUOY_ID})
        prefix = f"buoy_{BUOY_ID}"

        wind = hass.states.get(_entity_id(hass, prefix, "wind_speed"))
        # The test hass uses metric: 9.0 m/s is converted to km/h.
        assert wind.attributes["unit_of_measurement"] == "km/h"
        assert float(wind.state) == pytest.approx(32.4)
        wave = hass.states.get(_entity_id(hass, prefix, "wave_height"))
        assert float(wave.state) == pytest.approx(2.4)
        assert wave.attributes["observed_at"].isoformat() == "2026-11-13T16:50:00+00:00"
        assert hass.states.get(_entity_id(hass, prefix, "observed_at")).state == (
            "2026-11-13T17:10:00+00:00"
        )
        assert float(
            hass.states.get(_entity_id(hass, prefix, "pressure")).state
        ) == pytest.approx(1000.9)
        assert hass.states.get(_entity_id(hass, prefix, "station_id")).state == BUOY_ID
        assert _entity_id(hass, prefix, "checked_at") is not None

    async def test_setup_retries_on_failure(self, hass, aioclient_mock) -> None:
        aioclient_mock.get(ndbc_url(BUOY_ID), status=503)
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={
                CONF_PRODUCT_TYPE: "buoy",
                CONF_STATION_ID: BUOY_ID,
                CONF_NAME: "NDBC 44013",
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_RETRY
