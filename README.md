# NOAA Marine Forecast

Home Assistant integration for NOAA marine data. Pick a product type when you
add an entry:

| Product | Source | What you get |
| --- | --- | --- |
| **Marine forecast zone** | NWS coastal waters forecast text and NWS alerts | Conditions, periods, alert flags, flag image |
| **Tide station** | NOAA CO-OPS Tides & Currents API | Water level, next high/low tide, tide state, met observations |
| **Buoy / coastal weather station** | NOAA NDBC realtime observations | Wind, waves, pressure, air and water temperature |

Each entry is one location (one zone, one station or one buoy). Add as many as
you like.

> **Beta:** tide stations and buoys are new in `0.1.0-beta.1`. Existing marine
> zone entries are migrated automatically and keep their entities.

## Installation

### HACS

1. Add this repository as a custom repository in HACS (category: *Integration*).
2. Install **NOAA Marine Forecast**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/noaa_marine_forecast` into your Home Assistant
`config/custom_components` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → NOAA Marine Forecast**,
then choose a product type.

### Marine forecast zone

| Field | Example | Notes |
| --- | --- | --- |
| Marine zone ID | `ANZ230` | 6 alphanumeric characters; validated against NOAA on save |
| Name | `NOAA Marine Forecast` | Prefix for the device name |

### Tide station

| Field | Example | Notes |
| --- | --- | --- |
| Station ID | `8443970` | 7 digits; find yours at [tidesandcurrents.noaa.gov](https://tidesandcurrents.noaa.gov/) |
| Name | `Boston` | Optional; defaults to the station's NOAA name |
| Vertical datum | `MLLW` | Reference for water level and predictions. Use `IGLD` for Great Lakes stations |

### Buoy or coastal weather station

| Field | Example | Notes |
| --- | --- | --- |
| Station ID | `44013` | NDBC station ID (buoys such as `44013`, C-MAN stations such as `BUZM3`) |
| Name | `NDBC 44013` | Optional |

The update interval can be changed per entry via **Configure** (default
10 minutes, minimum 1 minute). NWS asks that clients not poll more often than
roughly every 30 seconds.

## Entities

### Marine forecast zone

One device per configured zone, named `<Name> <ZoneID>` (for example
`NOAA Marine Forecast ANZ230`).

#### Conditions

| Entity | Description |
| --- | --- |
| Conditions Now | The period currently in effect |
| Periods | Number of periods in the product; the `periods` attribute lists every period (`label`, `text`, `date`, `part`, `order`, `start`, `end`) for dashboards |

Not every product contains every period marker. `Conditions Now` is
derived from the periods that are actually present, so an evening product that
starts at `.TONIGHT...` reports Tonight as Now. Individual day and night
periods (today, tonight, tomorrow and so on) are available from the `Periods`
sensor's attribute rather than as separate sensors.

Attributes on `Conditions Now`:

| Attribute | Description |
| --- | --- |
| `period_label` | Raw NOAA marker, e.g. `THIS AFTERNOON` |
| `period_date` | Local date the period applies to |
| `period_part` | `day` or `night` |
| `full_text` | The complete raw NOAA product |
| `hazard_summary` | Hazard preamble from the product |
| `selection_method` | How Now was chosen |

Because NOAA text has no explicit period timestamps, day/night boundaries are
approximated as 06:00–18:00 local for daytime periods, 18:00–06:00 for night
periods, and 12:00–18:00 for `THIS AFTERNOON`. Selection uses the issuing
office's time zone from the product header, so `Now` is correct for the coast
being forecast, not just for Home Assistant's time zone.

#### Alerts

| Entity | Description |
| --- | --- |
| Alert | One line alert text (all clear when nothing is in force) |
| Alert Flags | Combined flag state, e.g. `gale_warning:active \| storm_warning:pending` |
| Active Alerts | Count of active marine alerts |
| Pending Alerts | Count of marine alerts that have not started yet |
| Alert Summary | Human readable list of active and pending events |
| Alert Flag (image) | Image of the highest severity flag |

Flag severities, lowest to highest:

1. `small_craft_advisory`
2. `gale_warning`
3. `storm_warning`
4. `hurricane_warning`

`Hurricane Force Wind Warning` maps to `hurricane_warning`. Other marine alerts
(`Hazardous Seas Warning`, `Tropical Storm Warning`, `Marine Weather Statement`,
and similar) are reported as alerts with full details but do not drive a flag,
so if one of those is in force without any of the four flags, the image entity
is simply unavailable. Watch the Alert Summary sensor if you need to see them.
Beach Hazards and Rip Current statements are ignored entirely.

The image shows the **highest severity flag across active and pending alerts**.
So a pending hurricane warning is shown as a hurricane flag even while a gale
warning is active; the `lifecycle` attribute (`active` or `pending`) and the
Alert Flags sensor carry the detail. Active, pending and full combinations are
always available from the sensor.

The image entity reports **unavailable** whenever no alert matching one of the
four flags is in force, so a dashboard with it as the card `entity` shows
nothing at all in clear conditions rather than an all-clear picture. Combine it
with the Alert Flags sensor in a `picture-elements` card, or gate the card on
that sensor, if you want the text visible at all times.

If the alert service cannot be reached, the last known alert state is retained
rather than being reset to all clear, and `alerts_available` is set to `false`.
A stale-but-retained flag stays available on purpose: blanking the dashboard on
a transient API error would hide a warning that may well still be in force.

#### Diagnostics

| Entity | Example |
| --- | --- |
| Zone ID | `ANZ230` |
| Zone Name | `Boston Harbor` |
| Forecast Office | `KBOX` (attribute `office_name`) |
| Product Title | `Coastal Waters Forecast for Massachusetts and Rhode Island` |
| WMO Identifier | `FZUS51` |
| AWIPS Identifier | `CWFBOX` |
| Issued At | `2026-09-25T10:03:00-04:00` |
| Expires At | `2026-09-26T03:00:00+00:00` |
| Checked At | Last successful poll |

### Tide station

One device per station, named `<Name> (<StationID>)`. A station only gets the
entities it actually reports: not every station measures water level, wind or
pressure, so check what the station offers on its NOAA page. Entities are
created from what the first successful poll returns.

| Entity | Description |
| --- | --- |
| Water level | Latest observed level relative to the chosen datum (attributes `datum`, `observed_at`) |
| Tide state | `rising` or `falling`, from the next predicted high or low |
| Next high tide / Next low tide | Timestamp of the next predicted extreme |
| Next high tide level / Next low tide level | Predicted height at that extreme |
| Air temperature, Water temperature | Latest observation |
| Pressure | Barometric pressure |
| Wind speed, Wind gust, Wind direction | Latest wind observation |
| Station ID | The configured station ID, with a `station_name` attribute (diagnostic) |
| Checked at | Last successful poll (diagnostic) |

Values are fetched in metric and converted by Home Assistant to your unit
system. Predicted tides cover roughly the next two days.

### Buoy or coastal weather station

One device per station, named `<Name> (<StationID>)`. Only measurements the
station reports are created.

| Entity | Description |
| --- | --- |
| Wind speed, Wind gust, Wind direction | Wind |
| Wave height | Significant wave height |
| Dominant wave period, Average wave period | Wave periods |
| Wave direction | Mean wave direction |
| Pressure | Sea-level pressure |
| Air temperature, Water temperature, Dew point | Temperatures |
| Observed at | Time of the newest observation (diagnostic) |
| Station ID | The configured station ID, with a `station_name` attribute (diagnostic) |
| Checked at | Last successful poll (diagnostic) |

NDBC stations do not report every field on every observation (waves are often
only on some rows), so each value comes from the newest of the last eight
observations that contains it. Each sensor's `observed_at` attribute shows the
time that value was measured.

## Dashboard example

```yaml
type: picture-elements
image: /api/image_proxy/api/image/serve/image.noaa_marine_anz230_alert_flag/512?token=IMAGE_TOKEN
elements:
  - type: state
    entity: sensor.noaa_marine_anz230_alert_flags
  - type: state
    entity: sensor.noaa_marine_anz230_conditions_now
```

Entity ids depend on the name you chose; check yours under
**Settings → Devices & Services**.

The image entity can also be used directly in a `picture-elements` card as the
`entity`, which avoids hardcoding an image proxy token:

```yaml
type: picture-elements
entity: image.noaa_marine_anz230_alert_flag
elements:
  - type: state
    entity: sensor.noaa_marine_anz230_alert_flags
```

## Data sources

- Forecast text: NOAA/NWS `tgftp` public text products.
- Alerts: NWS public API (`api.weather.gov`) (marine forecast zones only).
- Tides and observations: NOAA CO-OPS data API and metadata API
  (`api.tidesandcurrents.noaa.gov`).
- Buoys: NDBC realtime files (`www.ndbc.noaa.gov/data/realtime2/`).

Each entry refreshes every 10 minutes by default.

## Development

The test suite runs in two tiers.

### Fast tier

```bash
make test          # or: python3 -m unittest discover -s tests -t . -v
```

No dependencies and no Home Assistant. The forecast parser (`parser.py`), flag
model (`flags.py`), alert normalization (`alerts.py`), asset loading
(`assets.py`) and the tide (`tides.py`) and buoy (`buoy.py`) parsers are free of Home Assistant imports so they can be tested
standalone; `homeassistant`, `aiohttp` and `voluptuous` are stubbed for the
modules that need them, so this tier also catches import and missing-name errors
before anything is deployed.

### Real Home Assistant tier

```bash
make venv          # one-time: Python 3.14 + requirements-dev.txt
make test-ha       # or: .venv/bin/pytest
```

This tier runs the entity, config flow and coordinator code against a real
Home Assistant install via `pytest-homeassistant-custom-component`, which is
what exercises the paths the fast tier can only inspect statically: the
`available` contract, state writes, image bytes, form validation and the config
entry state machine. NOAA HTTP is mocked, so the suite is offline and
deterministic. Tide and buoy fixtures in `tests/data/` are real API captures.

Home Assistant 2026.9 requires Python 3.14. `pytest-homeassistant-custom-component`
pins an exact `homeassistant` version, so the two are upgraded together; keep
the pin in step with the Home Assistant version you actually run, or these
tests will describe an installation you are not running.

### Both

```bash
make test-all
```

A live Home Assistant instance is still the final check for anything the tiers
cannot see: manifest and translation loading by the integration loader, and
the flag image actually being served over HTTP.

## Disclaimer

This project is not affiliated with or endorsed by NOAA or the National Weather
Service. Forecast and alert data is provided as-is; always consult official NWS
products before making marine decisions.
