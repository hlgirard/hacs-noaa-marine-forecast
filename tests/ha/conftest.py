"""Shared fixtures for the real-Home-Assistant test tier.

The fast tier (``tests/*.py``, stdlib ``unittest``) stubs out Home Assistant
entirely. That catches import and name errors but cannot reach the code paths
that only exist once the real entity base classes, config entry state machine
and coordinator lifecycle are in play -- which is where every bug so far has
landed.

This tier runs against a real Home Assistant install via
``pytest-homeassistant-custom-component``. NOAA HTTP is mocked with Home
Assistant's own ``aioclient_mock`` fixture, so nothing here touches the network.

Note: ``tests/__init__.py`` deliberately replaces the component package with a
stub so the fast tier can run without Home Assistant. Importing anything
through the ``tests`` package here would poison the real modules, so the
repository root is placed on ``sys.path`` and the shared product fixtures are
loaded by file path instead.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.noaa_marine_forecast.alerts import build_alert_bundle  # noqa: E402
from custom_components.noaa_marine_forecast.api import (  # noqa: E402
    alerts_active_url,
    alerts_zone_url,
    forecast_url,
)
from custom_components.noaa_marine_forecast.const import (  # noqa: E402
    CONF_NAME,
    CONF_ZONE_ID,
    DOMAIN,
)
from custom_components.noaa_marine_forecast.coordinator import (  # noqa: E402
    MarineForecastCoordinator,
    MarineZoneData,
)
from custom_components.noaa_marine_forecast.parser import (  # noqa: E402
    parse_forecast,
    select_now_next,
)

ZONE = "ANZ230"
ZONE_NAME = "Boston Harbor"
OFFICE_TZ = ZoneInfo("America/New_York")

#: Fixed clock for every test. Real time would make the flag lifecycle and the
#: issued/expiry parsing non-deterministic.
NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)

#: NWS event names for each flag the integration recognizes.
FLAG_EVENTS = {
    "small_craft_advisory": "Small Craft Advisory",
    "gale_warning": "Gale Warning",
    "storm_warning": "Storm Warning",
    "hurricane_warning": "Hurricane Force Wind Warning",
}

#: A marine alert that is surfaced but drives no flag image.
OTHER_EVENT = "Hazardous Seas Warning"


def _load_product_fixtures() -> ModuleType:
    """Load ``tests/fixtures.py`` by path, bypassing the ``tests`` package."""
    spec = importlib.util.spec_from_file_location(
        "_nmf_product_fixtures", REPO_ROOT / "tests" / "fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PRODUCTS = _load_product_fixtures()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from ``custom_components``."""
    yield


@pytest.fixture
def product():
    """A parsed coastal waters forecast for ANZ230."""
    return parse_forecast(_PRODUCTS.ANZ230_PRODUCT, ZONE)


def cap_alert(
    event: str,
    alert_id: str,
    *,
    onset: datetime,
    ends: datetime,
) -> dict:
    """Build a minimal NWS CAP ``properties`` object."""
    return {
        "id": f"urn:oid:2.49.OMAPS.{alert_id}",
        "event": event,
        "category": "Marine",
        "severity": "Moderate",
        "certainty": "Likely",
        "urgency": "Expected",
        "status": "Actual",
        "messageType": "Alert",
        "areaDesc": "Boston Harbor",
        "senderName": "NWS Boston/Norton MA",
        "sent": onset.isoformat(),
        "onset": onset.isoformat(),
        "effective": onset.isoformat(),
        "ends": ends.isoformat(),
        "expires": ends.isoformat(),
    }


@pytest.fixture
def make_zone_data(product):
    """Build :class:`MarineZoneData` with chosen active and pending flags."""

    def _make(
        *,
        active: tuple[str, ...] = (),
        pending: tuple[str, ...] = (),
        other_events: tuple[str, ...] = (),
        alerts_available: bool = True,
        zone: str = ZONE,
    ) -> MarineZoneData:
        active_props = [
            cap_alert(
                FLAG_EVENTS[flag],
                f"a{index}",
                onset=NOW - timedelta(hours=1),
                ends=NOW + timedelta(hours=6),
            )
            for index, flag in enumerate(active)
        ]
        pending_props = [
            cap_alert(
                FLAG_EVENTS[flag],
                f"p{index}",
                onset=NOW + timedelta(hours=6),
                ends=NOW + timedelta(hours=30),
            )
            for index, flag in enumerate(pending)
        ]
        other_props = [
            cap_alert(
                event,
                f"o{index}",
                onset=NOW - timedelta(hours=1),
                ends=NOW + timedelta(hours=6),
            )
            for index, event in enumerate(other_events)
        ]
        # Unflagged marine events are reported through the active query. They
        # are surfaced as alerts but must not produce a flag.
        bundle = build_alert_bundle(
            active_props + other_props, pending_props, NOW
        )
        now_period, next_period, method = select_now_next(
            product, NOW, OFFICE_TZ
        )
        return MarineZoneData(
            zone_id=zone,
            forecast=product,
            alerts=bundle,
            now_period=now_period,
            next_period=next_period,
            selection_method=method,
            fetched_at=NOW,
            alerts_available=alerts_available,
            alerts_updated_at=NOW,
        )

    return _make


@pytest.fixture
def coordinator(hass):
    """A real coordinator with no data yet, for driving the entity directly."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_ZONE_ID: ZONE, CONF_NAME: "Boston Harbor"}
    )
    entry.add_to_hass(hass)
    return MarineForecastCoordinator(hass, entry)


@pytest.fixture
def mock_noaa(aioclient_mock):
    """Serve canned NOAA responses for a zone's forecast and alert queries."""

    def _mock(
        zone: str = ZONE,
        *,
        forecast_text: str | None = None,
        active: list[dict] | None = None,
        zone_alerts: list[dict] | None = None,
    ) -> None:
        text = forecast_text if forecast_text is not None else _PRODUCTS.ANZ230_PRODUCT
        aioclient_mock.get(forecast_url(zone), text=text)
        # api._features() reads the GeoJSON envelope, so each alert's CAP
        # properties must sit under a feature's "properties" key.
        aioclient_mock.get(
            alerts_active_url(zone),
            json={"features": [{"properties": p} for p in (active or [])]},
        )
        aioclient_mock.get(
            alerts_zone_url(zone),
            json={"features": [{"properties": p} for p in (zone_alerts or [])]},
        )

    return _mock
