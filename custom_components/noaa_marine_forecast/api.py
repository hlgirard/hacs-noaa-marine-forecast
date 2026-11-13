"""HTTP client for NOAA/NWS data sources."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlencode

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    COOPS_DATA_URL,
    COOPS_STATION_URL,
    NDBC_REALTIME_URL,
    ALERTS_ACTIVE_URL_TEMPLATE,
    ALERTS_ZONE_URL_TEMPLATE,
    FORECAST_URL_TEMPLATE,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

VALID_ZONE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class NOAAError(Exception):
    """Raised when a NOAA request fails."""


# Backward-compatible alias.
NOAAForecastError = NOAAError


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


# --- CO-OPS tide stations -------------------------------------------------

_TIDE_STATION_RE = re.compile(r"^\d{7}$")
_BUOY_STATION_RE = re.compile(r"^[A-Z0-9]{4,6}$")


def normalize_tide_station_id(station_id: str) -> str:
    """Return a CO-OPS station id (7 digits), raising on invalid input."""
    candidate = (station_id or "").strip()
    if not _TIDE_STATION_RE.match(candidate):
        raise NOAAError(
            f"Invalid tide station id {station_id!r}; expected 7 digits such as 8443970"
        )
    return candidate


def normalize_buoy_station_id(station_id: str) -> str:
    """Return an upper case NDBC station id, raising on invalid input."""
    candidate = (station_id or "").strip().upper()
    if not _BUOY_STATION_RE.match(candidate):
        raise NOAAError(
            f"Invalid buoy station id {station_id!r}; expected 4-6 letters or "
            "digits such as 44013"
        )
    return candidate


def coops_station_url(station_id: str) -> str:
    """Return the CO-OPS metadata URL for a station."""
    return COOPS_STATION_URL.format(station=normalize_tide_station_id(station_id))


def coops_data_url(station_id: str, product: str, datum: str, **extra: str) -> str:
    """Return a CO-OPS data API URL (metric units, GMT, JSON)."""
    params = {
        "product": product,
        "station": normalize_tide_station_id(station_id),
        "time_zone": "gmt",
        "units": "metric",
        "format": "json",
        "application": "hacs-noaa-marine-forecast",
    }
    if product in ("water_level", "predictions"):
        params["datum"] = datum
    params.update(extra)
    return f"{COOPS_DATA_URL}?{urlencode(params)}"


def coops_latest_url(station_id: str, product: str, datum: str) -> str:
    """URL for the latest observation of a product."""
    return coops_data_url(station_id, product, datum, date="latest")


def coops_predictions_url(station_id: str, datum: str, begin: datetime) -> str:
    """URL for high/low predictions covering 72 hours from ``begin`` (UTC)."""
    return coops_data_url(
        station_id,
        "predictions",
        datum,
        interval="hilo",
        begin_date=begin.strftime("%Y%m%d"),
        range="72",
    )


async def async_fetch_station_metadata(hass: HomeAssistant, station_id: str) -> dict:
    """Fetch CO-OPS station metadata (404 payloads come back as dicts)."""
    session = async_get_clientsession(hass)
    url = coops_station_url(station_id)
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            # An unknown station answers 200 with an ``errorCode`` payload,
            # but tolerate a real 404 too.
            if response.status == 404:
                return {}
            response.raise_for_status()
            return await response.json(content_type=None)
    except ClientError as err:
        raise NOAAError(f"Error requesting {url}: {err}") from err
    except TimeoutError as err:
        raise NOAAError(f"Timeout requesting {url}") from err


async def async_fetch_coops_json(hass: HomeAssistant, url: str) -> dict:
    """Fetch a CO-OPS data API URL as JSON."""
    payload = await _async_get_json(async_get_clientsession(hass), url)
    return payload if isinstance(payload, dict) else {}


# --- NDBC buoys ------------------------------------------------------------

#: The realtime2 file holds ~45 days of rows; only the head is needed.
NDBC_READ_BYTES = 4096


def ndbc_url(station_id: str) -> str:
    """Return the NDBC realtime2 URL for a station."""
    return NDBC_REALTIME_URL.format(station=normalize_buoy_station_id(station_id))


async def async_fetch_buoy(hass: HomeAssistant, station_id: str) -> str:
    """Fetch the newest rows of an NDBC realtime2 file as text."""
    session = async_get_clientsession(hass)
    url = ndbc_url(station_id)
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            buffer = bytearray()
            eof = True
            # ``read(n)`` returns whatever has arrived, so accumulate chunks.
            async for chunk in response.content.iter_chunked(1024):
                buffer.extend(chunk)
                if len(buffer) >= NDBC_READ_BYTES:
                    eof = False
                    break
    except ClientError as err:
        raise NOAAError(f"Error requesting {url}: {err}") from err
    except TimeoutError as err:
        raise NOAAError(f"Timeout requesting {url}") from err
    if not eof:
        # Stopped mid-file: drop the trailing partial line.
        buffer = buffer[: buffer.rfind(b"\n") + 1]
    text = bytes(buffer).decode("utf-8", errors="replace")
    if not text.strip():
        raise NOAAError(f"NOAA returned an empty file for {station_id.upper()}")
    return text
