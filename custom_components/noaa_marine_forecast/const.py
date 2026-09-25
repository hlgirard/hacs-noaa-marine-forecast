"""Constants for the NOAA Marine Forecast integration."""

from __future__ import annotations

from datetime import time
from typing import Final

DOMAIN: Final = "noaa_marine_forecast"
INTEGRATION_NAME: Final = "NOAA Marine Forecast"

PLATFORMS: Final[list[str]] = ["sensor", "image"]

CONF_ZONE_ID: Final = "zone_id"
CONF_NAME: Final = "name"

DEFAULT_NAME: Final = "NOAA Marine Forecast"
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 10
MIN_SCAN_INTERVAL_MINUTES: Final = 1

FORECAST_URL_TEMPLATE: Final = (
    "https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/"
    "{prefix}/{zone_lower}.txt"
)
ALERTS_ACTIVE_URL_TEMPLATE: Final = (
    "https://api.weather.gov/alerts/active/zone/{zone}"
)
ALERTS_ZONE_URL_TEMPLATE: Final = (
    "https://api.weather.gov/alerts?zone={zone}"
    "&status=actual&message_type=alert,update&limit=100"
)

USER_AGENT: Final = (
    "hacs-noaa-marine-forecast "
    "(Home Assistant custom integration; "
    "https://github.com/hlgirard/hacs-noaa-marine-forecast)"
)

REQUEST_TIMEOUT: Final = 30

# NOAA forecast text does not carry explicit period start/end times, so wall
# clock time is mapped onto periods using these conventional boundaries.
DAY_PERIOD_START: Final = time(6, 0)
AFTERNOON_PERIOD_START: Final = time(12, 0)
MORNING_PERIOD_END: Final = time(12, 0)
NIGHT_PERIOD_START: Final = time(18, 0)
NIGHT_PERIOD_END: Final = time(6, 0)
FULL_DAY_START: Final = time(0, 0)
FULL_DAY_END: Final = time(23, 59)

# Time zone abbreviations used in NWS product headers, mapped to IANA zones so
# that period selection can be done in the local time of the forecast office.
TZ_ABBREVIATIONS: Final[dict[str, str]] = {
    "EDT": "America/New_York",
    "EST": "America/New_York",
    "CDT": "America/Chicago",
    "CST": "America/Chicago",
    "MDT": "America/Denver",
    "MST": "America/Denver",
    "PDT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "AKDT": "America/Anchorage",
    "AKST": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    "AST": "America/Halifax",
    "ADT": "America/Halifax",
    "NST": "America/St_Johns",
    "NDDT": "America/St_Johns",
    "NDT": "America/St_Johns",
    "AST4": "America/Halifax",
    "GMT": "UTC",
    "UTC": "UTC",
    "Z": "UTC",
    "UTCZ": "UTC",
}
