# NOAA Marine Forecast

Home Assistant integration for NOAA coastal waters forecast text and NWS marine
alerts, exposed as sensors and a flag image per marine zone.

- **Forecast text**: `https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/{ab}/{zone}.txt`
- **Active alerts**: `https://api.weather.gov/alerts/active/zone/{ZoneID}`
- **Pending alerts**: the zone filtered alert query (NWS exposes no "pending"
  status, so pending is derived from CAP onset/expiry timestamps)

## Installation

### HACS

1. Add this repository as a custom repository in HACS (category: *Integration*).
2. Install **NOAA Marine Forecast**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/noaa_marine_forecast` into your Home Assistant
`config/custom_components` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → NOAA Marine Forecast**

| Field | Example | Notes |
| --- | --- | --- |
| Marine zone ID | `ANZ230` | 6 alphanumeric characters; validated against NOAA on save |
| Name | `NOAA Marine Forecast` | Prefix for the device name |

Add one entry per marine zone. The update interval can be changed per entry via
**Configure** (default 10 minutes, minimum 1 minute). NWS asks that clients not
poll more often than roughly every 30 seconds.

## Entities

One device per configured zone, named `<Name> <ZoneID>` (for example
`NOAA Marine Forecast ANZ230`).

### Conditions

| Entity | Description |
| --- | --- |
| Conditions Now | The period currently in effect |
| Conditions Next | The period immediately following Now |
| Conditions Today | Daytime period for the issue date |
| Conditions Tonight | Nighttime period for the issue date |
| Conditions Tomorrow | Daytime period for the next day |
| Conditions Tomorrow Night | Nighttime period for the next day |

Not every product contains every period marker. `Conditions Now` and
`Conditions Next` are derived from the periods that are actually present, so an
evening product that starts at `.TONIGHT...` reports Tonight as Now and the next
period as Next. A period that is genuinely absent from the product reports
`unknown`.

Attributes on the condition sensors:

| Attribute | Description |
| --- | --- |
| `period_label` | Raw NOAA marker, e.g. `THIS AFTERNOON` |
| `period_date` | Local date the period applies to |
| `period_part` | `day` or `night` |
| `full_text` | The complete raw NOAA product (Conditions Now only) |
| `hazard_summary` | Hazard preamble from the product (Conditions Now only) |
| `selection_method` | How Now was chosen (Conditions Now only) |

Because NOAA text has no explicit period timestamps, day/night boundaries are
approximated as 06:00–18:00 local for daytime periods, 18:00–06:00 for night
periods, and 12:00–18:00 for `THIS AFTERNOON`. Selection uses the issuing
office's time zone from the product header, so `Now` is correct for the coast
being forecast, not just for Home Assistant's time zone.

### Alerts

| Entity | Description |
| --- | --- |
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

### Diagnostics

| Entity | Example |
| --- | --- |
| Zone Name | `Boston Harbor` |
| Forecast Office | `KBOX` (attribute `office_name`) |
| Product Title | `Coastal Waters Forecast for Massachusetts and Rhode Island` |
| WMO Identifier | `FZUS51` |
| AWIPS Identifier | `CWFBOX` |
| Issued At | `2026-09-25T10:03:00-04:00` |
| Expires At | `2026-09-26T03:00:00+00:00` |
| Checked At | Last successful poll |

## Dashboard example

```yaml
type: picture-elements
image: /api/image_proxy/api/image/serve/image.noaa_marine_anz230_alert_flag/512?token=IMAGE_TOKEN
elements:
  - type: state
    entity: sensor.noaa_marine_anz230_alert_flags
  - type: state
    entity: sensor.noaa_marine_anz230_conditions_now
  - type: state
    entity: sensor.noaa_marine_anz230_conditions_next
```

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
- Alerts: NWS public API (`api.weather.gov`). Refresh default to 10 minutes per zone.

## Development

```bash
python -m unittest discover -s tests -t . -v
```

The forecast parser (`parser.py`), flag model (`flags.py`), alert
normalization (`alerts.py`) and asset loading (`assets.py`) are free of
Home Assistant imports so they can be tested standalone.

## Disclaimer

This project is not affiliated with or endorsed by NOAA or the National Weather
Service. Forecast and alert data is provided as-is; always consult official NWS
products before making marine decisions.
