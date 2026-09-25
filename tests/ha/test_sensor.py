"""Real-Home-Assistant tests for the alert sensor and hazard attributes.

The ``alert`` sensor is the dashboard's compact text source, so its state and
attributes are a contract: the Home markdown card renders the state verbatim
and the Weather card reads ``hazard_title`` off the period sensors.
"""

from __future__ import annotations

from unittest.mock import patch
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from conftest import ZONE, ZONE_NAME

from custom_components.noaa_marine_forecast.const import DOMAIN
from custom_components.noaa_marine_forecast.sensor import SENSORS, MarineSensor

EASTERN = ZoneInfo("America/New_York")


def _description(key: str):
    """Return the sensor description for a key."""
    return next(item for item in SENSORS if item.key == key)


def _sensor(hass, coordinator, make_zone_data, key: str, **kwargs) -> MarineSensor:
    """Build a sensor bound to canned zone data."""
    coordinator.async_set_updated_data(make_zone_data(**kwargs))
    entity = MarineSensor(coordinator, _description(key), ZONE, ZONE_NAME)
    entity.hass = hass
    return entity


def _alert_text(entity: MarineSensor) -> str:
    """Return the alert state with the timezone pinned to Eastern."""
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", EASTERN):
        return entity.native_value


class TestAlertState:
    """The state is the one line the Home card renders."""

    def test_storm_warning_with_window(self, hass, coordinator, make_zone_data):
        entity = _sensor(
            hass, coordinator, make_zone_data, "alert", active=("storm_warning",)
        )
        # NOW is Friday 2026-09-25 18:00 UTC; ends is +6h = 8pm Eastern.
        assert _alert_text(entity) == "Storm Warning until Friday 8pm"

    def test_all_clear(self, hass, coordinator, make_zone_data):
        entity = _sensor(hass, coordinator, make_zone_data, "alert")
        assert _alert_text(entity) == "No marine alerts"


class TestAlertAttributes:
    """Attributes carry the detail the Weather card and automations need."""

    def test_top_alert_fields(self, hass, coordinator, make_zone_data):
        entity = _sensor(
            hass, coordinator, make_zone_data, "alert", active=("storm_warning",)
        )
        attrs = entity.extra_state_attributes
        assert attrs["flag"] == "storm_warning"
        assert attrs["flag_title"] == "Storm Warning"
        assert attrs["lifecycle"] == "active"
        assert attrs["severity"] == "Moderate"
        assert attrs["area"] == "Boston Harbor"
        assert attrs["ends"] == "2026-09-26T00:00:00+00:00"
        assert attrs["zone"] == ZONE
        assert attrs["zone_name"] == "Boston Harbor"
        assert attrs["alerts_available"] is True

    def test_clear_has_no_alert_fields(self, hass, coordinator, make_zone_data):
        entity = _sensor(hass, coordinator, make_zone_data, "alert")
        attrs = entity.extra_state_attributes
        assert attrs["flag"] == "none"
        assert attrs["lifecycle"] is None
        assert "headline" not in attrs
        assert "ends" not in attrs


class TestAlertPicture:
    """The sensor mirrors the flag image URL when the image entity exists."""

    def test_no_image_entity_means_no_picture(
        self, hass, coordinator, make_zone_data
    ):
        entity = _sensor(
            hass, coordinator, make_zone_data, "alert", active=("storm_warning",)
        )
        assert entity.extra_state_attributes["entity_picture"] is None

    def test_picture_mirrored_from_image_entity(
        self, hass, coordinator, make_zone_data
    ):
        registry = er.async_get(hass)
        entity_id = registry.async_get_or_create(
            "image", DOMAIN, f"{ZONE.lower()}_alert_flag_image"
        ).entity_id
        url = "/api/image_proxy/image.test?token=abc"
        hass.states.async_set(entity_id, "2026-09-25T18:00:00+00:00", {"entity_picture": url})
        entity = _sensor(
            hass, coordinator, make_zone_data, "alert", active=("storm_warning",)
        )
        assert entity.extra_state_attributes["entity_picture"] == url


class TestHazardAttributes:
    """Every period sensor carries the product hazard text."""

    def test_now_has_title_and_summary(
        self, hass, coordinator, make_zone_data
    ):
        entity = _sensor(hass, coordinator, make_zone_data, "conditions_now")
        attrs = entity.extra_state_attributes
        assert attrs["hazard_title"] == (
            "Storm Warning in Effect from 2 PM EDT This Afternoon "
            "through Saturday Evening"
        )
        assert attrs["hazard_summary"].startswith("STORM WARNING IN EFFECT")
        # Pre-existing attributes survive the hazard wiring.
        assert attrs["period_label"] == "THIS AFTERNOON"
        assert attrs["selection_method"]

class TestPeriodsSensor:
    """The periods sensor exposes the full parsed horizon for the card."""

    def test_state_is_period_count(self, hass, coordinator, make_zone_data):
        entity = _sensor(hass, coordinator, make_zone_data, "periods")
        assert entity.native_value == 7

    def test_periods_in_order_with_detail(
        self, hass, coordinator, make_zone_data
    ):
        entity = _sensor(hass, coordinator, make_zone_data, "periods")
        periods = entity.extra_state_attributes["periods"]
        assert [p["label"] for p in periods] == [
            "THIS AFTERNOON",
            "TONIGHT",
            "SAT",
            "SAT NIGHT",
            "SUN",
            "SUN NIGHT",
            "MON",
        ]
        first = periods[0]
        assert first["part"] == "day"
        assert first["date"] == "2026-09-25"
        assert first["order"] == 0
        assert first["text"].startswith("NE winds")
        # Window instants are exact regardless of the ambient timezone.
        assert datetime.fromisoformat(first["start"]) == datetime(
            2026, 9, 25, 19, 0, tzinfo=timezone.utc
        )
        assert datetime.fromisoformat(first["end"]) == datetime(
            2026, 9, 26, 1, 0, tzinfo=timezone.utc
        )

    def test_deprecated_period_sensors_removed(self):
        from custom_components.noaa_marine_forecast.sensor import SENSORS

        keys = {item.key for item in SENSORS}
        for key in (
            "conditions_today",
            "conditions_tonight",
            "conditions_next",
            "conditions_tomorrow",
            "conditions_tomorrow_night",
        ):
            assert key not in keys, key
        # conditions_now and the new periods sensor stay.
        assert "conditions_now" in keys
        assert "periods" in keys
