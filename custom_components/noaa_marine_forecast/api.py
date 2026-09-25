"""HTTP client for NOAA/NWS data sources."""

from __future__ import annotations

import logging

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ALERTS_ACTIVE_URL_TEMPLATE,
    ALERTS_ZONE_URL_TEMPLATE,
    FORECAST_URL_TEMPLATE,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

VALID_ZONE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class NOAAForecastError(Exception):
    """Raised when a NOAA request fails."""


def normalize_zone_id(zone_id: str) -> str:
    """Return an upper case zone id, raising on invalid input."""
    candidate = (zone_id or "").strip().upper()
    if len(candidate) != 6 or not set(candidate) <= VALID_ZONE_CHARS:
        raise NOAAForecastError(
            f"Invalid marine zone id {zone_id!r}; expected 6 alphanumeric "
            "characters such as ANZ230"
        )
    return candidate


def forecast_url(zone_id: str) -> str:
    """Return the tgftp.nws.noaa.gov forecast URL for a zone."""
    zone = normalize_zone_id(zone_id)
    return FORECAST_URL_TEMPLATE.format(
        prefix=zone[:2].lower(), zone_lower=zone.lower()
    )


def alerts_active_url(zone_id: str) -> str:
    """Return the active alerts URL for a zone."""
    return ALERTS_ACTIVE_URL_TEMPLATE.format(zone=normalize_zone_id(zone_id))


def alerts_zone_url(zone_id: str) -> str:
    """Return the zone filtered alerts URL used to find pending alerts."""
    return ALERTS_ZONE_URL_TEMPLATE.format(zone=normalize_zone_id(zone_id))


async def _async_get_text(session, url: str) -> str:
    """GET a URL and return the body as text."""
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            return await response.text()
    except ClientError as err:
        raise NOAAForecastError(f"Error requesting {url}: {err}") from err
    except TimeoutError as err:
        raise NOAAForecastError(f"Timeout requesting {url}") from err


async def _async_get_json(session, url: str) -> dict:
    """GET a URL and return the body as JSON."""
    try:
        async with session.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/geo+json, application/json",
            },
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)
    except ClientError as err:
        raise NOAAForecastError(f"Error requesting {url}: {err}") from err
    except TimeoutError as err:
        raise NOAAForecastError(f"Timeout requesting {url}") from err


async def async_fetch_forecast(hass: HomeAssistant, zone_id: str) -> str:
    """Fetch the raw coastal waters forecast text for a zone."""
    session = async_get_clientsession(hass)
    text = await _async_get_text(session, forecast_url(zone_id))
    if not text.strip():
        raise NOAAForecastError(
            f"NOAA returned an empty forecast for {zone_id.upper()}"
        )
    return text


async def async_fetch_alerts(hass: HomeAssistant, zone_id: str) -> list[dict]:
    """Fetch active alert properties for a zone."""
    session = async_get_clientsession(hass)
    payload = await _async_get_json(session, alerts_active_url(zone_id))
    return _features(payload)


async def async_fetch_zone_alerts(hass: HomeAssistant, zone_id: str) -> list[dict]:
    """Fetch recent/pending alert properties for a zone."""
    session = async_get_clientsession(hass)
    payload = await _async_get_json(session, alerts_zone_url(zone_id))
    return _features(payload)


def _features(payload: object) -> list[dict]:
    """Return the ``properties`` of each feature in a GeoJSON collection."""
    from .alerts import parse_alert_payload

    return parse_alert_payload(payload if isinstance(payload, dict) else None)
