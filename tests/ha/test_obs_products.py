"""Real-Home-Assistant tests for the tide station and buoy products."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

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


@pytest.fixture(autouse=True)
def _clock(freezer):
    """Pin the clock just after the fixture observations were taken.

    Readings older than three hours make sensors unavailable, so the real
    clock would eventually break these tests.
    """
    freezer.move_to("2026-11-13 17:40:00+00:00")


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
            "level_unit": "auto",
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
        await hass.config.async_set_time_zone("America/New_York")
        mock_coops()
        await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        prefix = f"tide_{TIDE_ID}"

        level = hass.states.get(_entity_id(hass, prefix, "water_level"))
        assert float(level.state) == pytest.approx(3.251)
        assert level.attributes["datum"] == "MLLW"
        assert hass.states.get(_entity_id(hass, prefix, "tide_state")).state == "rising"
        nxt = hass.states.get(_entity_id(hass, prefix, "next_tide"))
        assert nxt.state == "high"
        assert nxt.attributes["time"].isoformat() == "2026-11-13T06:30:00+00:00"
        assert nxt.attributes["level"] == 2.6
        assert nxt.attributes["level_unit"] == "m"
        assert nxt.attributes["datum"] == "MLLW"
        # 06:30 UTC is 01:30 in New York (EST); the display text is local time.
        assert nxt.attributes["display"] == "01:30 \u00b7 2.6 m"
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

    async def test_level_unit_feet(self, hass, mock_coops, freezer) -> None:
        freezer.move_to("2026-11-13 05:00:00+00:00")
        await hass.config.async_set_time_zone("UTC")
        mock_coops()
        await _configure(
            hass, "tide_station", {CONF_STATION_ID: TIDE_ID, "level_unit": "ft"}
        )
        nxt = hass.states.get(_entity_id(hass, f"tide_{TIDE_ID}", "next_tide"))
        assert nxt.attributes["display"] == "06:30 \u00b7 8.6 ft"
        assert nxt.attributes["level_unit"] == "ft"
        assert nxt.attributes["level"] == 8.6

    async def test_auto_follows_home_assistant_units(
        self, hass, mock_coops, freezer
    ) -> None:
        from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

        hass.config.units = US_CUSTOMARY_SYSTEM
        freezer.move_to("2026-11-13 05:00:00+00:00")
        mock_coops()
        await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        nxt = hass.states.get(_entity_id(hass, f"tide_{TIDE_ID}", "next_tide"))
        assert nxt.attributes["level_unit"] == "ft"

    async def test_options_flow_changes_unit(self, hass, mock_coops, freezer) -> None:
        freezer.move_to("2026-11-13 05:00:00+00:00")
        mock_coops()
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        entry = result["result"]
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        assert "level_unit" in flow["data_schema"].schema
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {"level_unit": "ft", "scan_interval": 10}
        )
        await hass.async_block_till_done()
        nxt = hass.states.get(_entity_id(hass, f"tide_{TIDE_ID}", "next_tide"))
        assert nxt.attributes["level_unit"] == "ft"

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


def test_tide_numeric_sensors_default_to_one_decimal() -> None:
    from custom_components.noaa_marine_forecast.obs_sensor import TIDE_SENSORS

    numeric = [d for d in TIDE_SENSORS if d.native_unit_of_measurement]
    assert len(numeric) == 9  # levels, temperatures, pressure, wind
    for description in numeric:
        assert description.suggested_display_precision == 1, description.key


def test_buoy_numeric_sensors_default_to_one_decimal() -> None:
    from custom_components.noaa_marine_forecast.obs_sensor import BUOY_SENSORS

    numeric = [d for d in BUOY_SENSORS if d.native_unit_of_measurement]
    assert len(numeric) == 11  # wind, waves, pressure, temperatures
    for description in numeric:
        assert description.suggested_display_precision == 1, description.key


def _tide_entry(hass, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_PRODUCT_TYPE: "tide_station",
            CONF_STATION_ID: TIDE_ID,
            CONF_NAME: "Boston",
            CONF_DATUM: "MLLW",
        },
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


class TestTideRollover:
    async def test_states_update_when_a_tide_passes(
        self, hass, mock_coops, freezer
    ) -> None:
        freezer.move_to("2026-11-13 05:00:00+00:00")
        mock_coops()
        # A day-long interval proves the update comes from the timer, not a poll.
        entry = _tide_entry(hass, scan_interval=1440)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        prefix = f"tide_{TIDE_ID}"
        assert hass.states.get(_entity_id(hass, prefix, "tide_state")).state == "rising"
        assert hass.states.get(_entity_id(hass, prefix, "next_tide")).state == "high"

        freezer.move_to("2026-11-13 06:31:00+00:00")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(_entity_id(hass, prefix, "tide_state")).state == "falling"
        nxt = hass.states.get(_entity_id(hass, prefix, "next_tide"))
        assert nxt.state == "low"
        assert nxt.attributes["time"].isoformat() == "2026-11-13T12:20:00+00:00"


class TestTideResilience:
    async def _setup(self, hass, mock_coops):
        mock_coops()
        entry = _tide_entry(hass, scan_interval=1440)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    async def test_failed_requests_keep_previous_data(
        self, hass, mock_coops, aioclient_mock, freezer
    ) -> None:
        freezer.move_to("2026-11-13 05:00:00+00:00")
        entry = await self._setup(hass, mock_coops)
        prefix = f"tide_{TIDE_ID}"
        aioclient_mock.clear_requests()
        # Every request except water level now fails.
        aioclient_mock.get(
            re.compile(r".*product=water_level.*"),
            text=_text("coops_water_level.json"),
        )
        aioclient_mock.get(re.compile(r".*datagetter.*"), status=500)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert entry.runtime_data.last_update_success
        assert hass.states.get(_entity_id(hass, prefix, "next_tide")).state == "high"
        assert float(
            hass.states.get(_entity_id(hass, prefix, "air_temperature")).state
        ) == pytest.approx(5.4)

    async def test_old_readings_become_unavailable(
        self, hass, mock_coops, freezer
    ) -> None:
        entry = await self._setup(hass, mock_coops)
        prefix = f"tide_{TIDE_ID}"
        level = _entity_id(hass, prefix, "water_level")
        assert hass.states.get(level).state != "unavailable"

        # The observation is from 17:36; four hours later it is too old.
        freezer.move_to("2026-11-13 21:40:00+00:00")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(level).state == "unavailable"
        assert hass.states.get(_entity_id(hass, prefix, "station_id")).state == TIDE_ID

    async def test_malformed_station_id_retries_setup(self, hass) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={
                CONF_PRODUCT_TYPE: "tide_station",
                CONF_STATION_ID: "abc",
                CONF_NAME: "Bad",
                CONF_DATUM: "MLLW",
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_RETRY


class TestBuoyStaleness:
    async def test_old_buoy_readings_unavailable(self, hass, mock_ndbc, freezer) -> None:
        mock_ndbc()
        result = await _configure(hass, "buoy", {CONF_STATION_ID: BUOY_ID})
        entry = result["result"]
        prefix = f"buoy_{BUOY_ID}"
        wind = _entity_id(hass, prefix, "wind_speed")
        assert hass.states.get(wind).state != "unavailable"
        freezer.move_to("2026-11-13 21:30:00+00:00")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(wind).state == "unavailable"


class TestBuoyFetch:
    async def test_large_file_cut_to_complete_rows(self, hass, aioclient_mock) -> None:
        from custom_components.noaa_marine_forecast.api import async_fetch_buoy

        lines = _text("ndbc_44013.txt").splitlines()
        body = "\n".join(lines + lines[2:] * 4) + "\n2026 11 13 10 00  10  9"
        assert len(body) > 4096
        aioclient_mock.get(ndbc_url(BUOY_ID), text=body)
        text = await async_fetch_buoy(hass, BUOY_ID)
        assert text.endswith("\n")
        assert text.startswith("#YY")

    async def test_truncated_final_row_is_ignored(self, hass, aioclient_mock) -> None:
        from custom_components.noaa_marine_forecast.api import async_fetch_buoy
        from custom_components.noaa_marine_forecast.buoy import parse_realtime

        header = _text("ndbc_44013.txt").splitlines()[:2]
        body = "\n".join(header + ["2026 11 13 17 10  10  9.0 11.0"]) + "\n"
        aioclient_mock.get(ndbc_url(BUOY_ID), text=body)
        with pytest.raises(ValueError):
            parse_realtime(await async_fetch_buoy(hass, BUOY_ID))


class TestOptionsName:
    async def test_tide_name_from_options(self, hass, mock_coops) -> None:
        mock_coops()
        result = await _configure(hass, "tide_station", {CONF_STATION_ID: TIDE_ID})
        entry = result["result"]
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {"name": "Harbor", "scan_interval": 10}
        )
        await hass.async_block_till_done()
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, f"tide_{TIDE_ID}"), entry.entry_id
        )
        assert device.name == f"Harbor ({TIDE_ID})"
        station = hass.states.get(_entity_id(hass, f"tide_{TIDE_ID}", "station_id"))
        assert station.attributes["station_name"] == "Harbor"

    async def test_buoy_name_from_options(self, hass, mock_ndbc) -> None:
        mock_ndbc()
        result = await _configure(hass, "buoy", {CONF_STATION_ID: BUOY_ID})
        entry = result["result"]
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {"name": "Offshore", "scan_interval": 10}
        )
        await hass.async_block_till_done()
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, f"buoy_{BUOY_ID}"), entry.entry_id
        )
        assert device.name == f"Offshore ({BUOY_ID})"
