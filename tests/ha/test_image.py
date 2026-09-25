"""Real-Home-Assistant tests for the flag image entity.

The image platform is the one module the fast tier cannot execute at all: it
subclasses a Home Assistant entity, and every interesting behaviour -- the
``available`` contract, the state write on a coordinator update, the image
bytes -- only exists once Home Assistant's real base classes are involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import NOW, OTHER_EVENT, ZONE, ZONE_NAME, cap_alert

from custom_components.noaa_marine_forecast.assets import FLAG_ASSETS
from custom_components.noaa_marine_forecast.const import (
    CONF_NAME,
    CONF_ZONE_ID,
    DOMAIN,
)
from custom_components.noaa_marine_forecast.flags import FLAG_NONE
from custom_components.noaa_marine_forecast.image import MarineFlagImage

ALL_FLAGS = tuple(FLAG_ASSETS)


@pytest.fixture
def make_image(hass, coordinator):
    """Build a real image entity bound to a real coordinator."""

    def _make(name: str = ZONE_NAME) -> MarineFlagImage:
        return MarineFlagImage(
            coordinator, hass, coordinator.config_entry, ZONE, name
        )

    return _make


def image_entity_id(hass) -> str | None:
    """Return the entity id of the flag image, if it was registered."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "image", DOMAIN, f"{ZONE.lower()}_alert_flag_image"
    )


class TestConstruction:
    """The entity must build against the installed Home Assistant."""

    def test_entity_constructs(self, make_image) -> None:
        """Smoke test for the ``ImageEntity`` base class contract."""
        entity = make_image()
        assert entity.unique_id == f"{ZONE.lower()}_alert_flag_image"
        assert entity.entity_id is None, "not added to hass yet"

    def test_translation_key_and_device_info(self, make_image) -> None:
        entity = make_image()
        assert entity.has_entity_name is True
        assert entity.translation_key == "alert_flag_image"
        assert entity.should_poll is False
        info = entity.device_info
        assert info["identifiers"] == {(DOMAIN, ZONE.lower())}
        assert info["name"] == f"{ZONE_NAME} {ZONE}"
        assert info["manufacturer"] == "NOAA / NWS"

    def test_device_name_uses_entry_name(self, hass, coordinator) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: "Custom Name"}
        )
        entity = MarineFlagImage(coordinator, hass, entry, ZONE, "Custom Name")
        assert entity.device_info["name"] == f"Custom Name {ZONE}"


class TestAvailability:
    """``available`` is the contract the dashboard depends on."""

    def test_unavailable_before_data(self, coordinator, make_image) -> None:
        entity = make_image()
        assert coordinator.data is None
        assert entity.available is False

    @pytest.mark.parametrize("flag", ALL_FLAGS)
    def test_available_for_each_flag(
        self, coordinator, make_image, make_zone_data, flag
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=(flag,))
        entity._apply()
        assert entity.flag == flag
        assert entity.available is True

    def test_unavailable_when_nothing_in_force(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data()
        entity._apply()
        assert entity.flag == FLAG_NONE
        assert entity.available is False

    def test_unavailable_for_unflagged_marine_alert(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        """Hazardous Seas is a real alert but drives no flag image."""
        entity = make_image()
        coordinator.data = make_zone_data(other_events=(OTHER_EVENT,))
        entity._apply()
        assert coordinator.data.alerts.active, "the alert should still be surfaced"
        assert entity.flag == FLAG_NONE
        assert entity.available is False

    def test_stays_available_when_alerts_are_stale(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        """A transient API failure must not blank a possibly in-force warning."""
        entity = make_image()
        coordinator.data = make_zone_data(
            active=("storm_warning",), alerts_available=False
        )
        entity._apply()
        assert entity.available is True
        assert entity.extra_state_attributes["alerts_available"] is False

    def test_missing_asset_makes_unavailable(
        self, coordinator, make_image, make_zone_data, monkeypatch
    ) -> None:
        from custom_components.noaa_marine_forecast import image as image_module

        def _missing(flag: str):
            raise FileNotFoundError(f"No flag image asset for {flag!r}")

        monkeypatch.setattr(image_module, "load_flag_image", _missing)
        # The cache would otherwise mask repeated failures.
        monkeypatch.setattr(
            image_module, "_LOGGER", image_module._LOGGER, raising=False
        )
        entity = make_image()
        coordinator.data = make_zone_data(active=("gale_warning",))
        entity._apply()
        assert entity.flag == "gale_warning"
        assert entity.available is False


class TestImageBytes:
    """What the image entity actually serves."""

    @pytest.mark.parametrize("flag", ALL_FLAGS)
    def test_image_matches_flag(
        self, coordinator, make_image, make_zone_data, flag
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=(flag,))
        entity._apply()
        payload = entity.image()
        assert isinstance(payload, bytes)
        assert payload, "flag image must not be empty"
        # SVGs may lead with an XML declaration before the <svg> element.
        assert payload[:200].lstrip().startswith((b"<?xml", b"<svg", b"\x89PNG", b"\xff\xd8\xff"))
        assert entity.content_type in {
            "image/svg+xml",
            "image/png",
            "image/jpeg",
            "image/webp",
        }

    @pytest.mark.parametrize("flag", ALL_FLAGS)
    def test_content_type_set_on_apply(
        self, coordinator, make_image, make_zone_data, flag
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=(flag,))
        entity._apply()
        assert entity.content_type == "image/png"

    def test_image_raises_for_no_flag(self, coordinator, make_image, make_zone_data):
        """Pins the defensive behaviour: no bytes for a flag that has no asset."""
        entity = make_image()
        coordinator.data = make_zone_data()
        entity._apply()
        assert entity.available is False
        with pytest.raises(FileNotFoundError):
            entity.image()


class TestStateWrites:
    """A poll that changes nothing must not write state.

    ``_apply`` reports whether the displayed flag changed, and
    ``_handle_coordinator_update`` only writes state when it did. If the success
    path reports "changed" unconditionally, every poll writes state and the
    recorder grows a row per zone per interval forever.
    """

    def test_no_write_when_flag_unchanged(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=("storm_warning",))
        entity._apply()

        with patch.object(entity, "async_write_ha_state") as write:
            coordinator.data = make_zone_data(active=("storm_warning",))
            entity._handle_coordinator_update()
            coordinator.data = make_zone_data(active=("storm_warning",))
            entity._handle_coordinator_update()

        assert write.call_count == 0, (
            "state was written on polls that did not change the flag: "
            f"{write.call_count} writes for 2 unchanged updates"
        )

    def test_writes_when_flag_changes(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=("gale_warning",))
        entity._apply()

        with patch.object(entity, "async_write_ha_state") as write:
            coordinator.data = make_zone_data(active=("storm_warning",))
            entity._handle_coordinator_update()

        assert write.call_count == 1
        assert entity.flag == "storm_warning"

    def test_writes_when_flag_clears(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(active=("gale_warning",))
        entity._apply()

        with patch.object(entity, "async_write_ha_state") as write:
            coordinator.data = make_zone_data()
            entity._handle_coordinator_update()

        assert write.call_count == 1
        assert entity.flag == FLAG_NONE
        assert entity.available is False


class TestSeveritySelection:
    """The image shows the single highest severity flag in force."""

    def test_pending_outranks_active(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        """A pending storm warning beats an active gale warning."""
        entity = make_image()
        coordinator.data = make_zone_data(
            active=("gale_warning",), pending=("storm_warning",)
        )
        entity._apply()
        assert entity.flag == "storm_warning"
        assert entity.lifecycle == "pending"

    def test_highest_of_several_active(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(
            active=("small_craft_advisory", "gale_warning", "storm_warning")
        )
        entity._apply()
        assert entity.flag == "storm_warning"
        assert entity.lifecycle == "active"

    def test_attributes_expose_alert_detail(
        self, coordinator, make_image, make_zone_data
    ) -> None:
        entity = make_image()
        coordinator.data = make_zone_data(
            active=("gale_warning",), pending=("storm_warning",)
        )
        entity._apply()
        attrs = entity.extra_state_attributes
        assert attrs["highest_flag"] == "storm_warning"
        assert attrs["highest_flag_title"] == "Storm Warning"
        assert attrs["lifecycle"] == "pending"
        assert attrs["active_flags"] == ["gale_warning"]
        assert attrs["pending_flags"] == ["storm_warning"]
        assert attrs["flag_combination"] == "gale_warning:active | storm_warning:pending"
        assert attrs["alerts_available"] is True


class TestFullSetup:
    """End to end through the real config entry, coordinator and platforms."""

    async def test_entity_is_registered_and_serves_image(
        self, hass, mock_noaa
    ) -> None:
        mock_noaa(
            active=[
                cap_alert(
                    "Storm Warning",
                    "live",
                    onset=NOW - timedelta(hours=1),
                    ends=NOW + timedelta(hours=6),
                )
            ]
        )
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_id = image_entity_id(hass)
        assert entity_id is not None, "the flag image entity was never registered"

        state = hass.states.get(entity_id)
        assert state is not None
        # An available image entity reports its last-updated timestamp as state.
        assert state.state != "unavailable", state.attributes
        datetime.fromisoformat(state.state)
        assert state.attributes["highest_flag"] == "storm_warning"
        assert state.attributes["lifecycle"] == "active"
        # The frontend image is served through Home Assistant's image proxy.
        assert entity_id in state.attributes["entity_picture"]

    async def test_unavailable_when_no_alerts(self, hass, mock_noaa) -> None:
        mock_noaa()
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_id = image_entity_id(hass)
        assert entity_id is not None
        assert hass.states.get(entity_id).state == "unavailable"

    async def test_sensors_created_alongside(self, hass, mock_noaa) -> None:
        """The image platform must not break the sensor platform."""
        mock_noaa()
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: ZONE_NAME}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        sensors = [
            e
            for e in registry.entities.values()
            if e.platform == DOMAIN and e.domain == "sensor"
        ]
        assert len(sensors) == 19, f"expected 19 sensors, found {len(sensors)}"
