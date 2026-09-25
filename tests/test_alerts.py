"""Tests for NWS CAP alert normalization."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from custom_components.noaa_marine_forecast.alerts import (
    build_alert_bundle,
    format_alert_text,
    format_alert_window,
    normalize_alert,
    parse_alert_payload,
    select_top_alert,
    top_alert_detail,
)
from custom_components.noaa_marine_forecast.flags import (
    FLAG_GALE_WARNING,
    FLAG_HURRICANE_WARNING,
    FLAG_NONE,
    FLAG_SMALL_CRAFT_ADVISORY,
    FLAG_STORM_WARNING,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _iso(hours: float) -> str:
    """Return an ISO timestamp relative to NOW."""
    return (NOW + timedelta(hours=hours)).isoformat()


def _props(
    event: str,
    *,
    onset: float | None = None,
    ends: float | None = None,
    expires: float | None = None,
    alert_id: str = "urn:oid:1",
) -> dict:
    """Build a CAP properties object."""
    return {
        "id": alert_id,
        "event": event,
        "status": "Actual",
        "messageType": "Alert",
        "severity": "Severe",
        "certainty": "Observed",
        "urgency": "Immediate",
        "areaDesc": "Boston Harbor",
        "senderName": "NWS Boston/Norton MA",
        "headline": f"{event} in effect",
        "sent": _iso(-1),
        "onset": _iso(onset) if onset is not None else None,
        "ends": _iso(ends) if ends is not None else None,
        "expires": _iso(expires) if expires is not None else None,
    }


class TestNormalizeAlert(unittest.TestCase):
    """CAP property normalization."""

    def test_fields(self) -> None:
        alert = normalize_alert(
            _props("Storm Warning", onset=-2, ends=20), "active", NOW
        )
        self.assertEqual(alert.event, "STORM WARNING")
        self.assertEqual(alert.event_slug, "storm_warning")
        self.assertEqual(alert.flag, FLAG_STORM_WARNING)
        self.assertEqual(alert.lifecycle, "active")
        self.assertEqual(alert.severity, "Severe")
        self.assertEqual(alert.area, "Boston Harbor")
        self.assertEqual(alert.onset, NOW - timedelta(hours=2))
        self.assertEqual(alert.effective_end, NOW + timedelta(hours=20))

    def test_expires_used_when_ends_missing(self) -> None:
        alert = normalize_alert(_props("Gale Warning", expires=5), "active", NOW)
        self.assertEqual(alert.effective_end, NOW + timedelta(hours=5))

    def test_zulu_timestamps_parsed(self) -> None:
        props = _props("Gale Warning", onset=1)
        props["onset"] = "2026-09-25T13:00:00Z"
        alert = normalize_alert(props, "pending", NOW)
        assert alert.onset is not None
        self.assertEqual(alert.onset.tzinfo, timezone.utc)

    def test_attributes_are_compact(self) -> None:
        alert = normalize_alert(
            _props("Gale Warning", onset=1, ends=10), "pending", NOW
        )
        attributes = alert.as_attributes()
        self.assertNotIn("description", attributes)
        self.assertEqual(attributes["event_slug"], "gale_warning")
        self.assertEqual(attributes["lifecycle"], "pending")


class TestParsePayload(unittest.TestCase):
    """GeoJSON handling."""

    def test_features_extracted(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {"properties": _props("Gale Warning")},
                {"properties": _props("Storm Warning")},
            ],
        }
        self.assertEqual(len(parse_alert_payload(payload)), 2)

    def test_bad_payloads(self) -> None:
        self.assertEqual(parse_alert_payload(None), [])
        self.assertEqual(parse_alert_payload({}), [])
        self.assertEqual(parse_alert_payload({"features": "nope"}), [])
        self.assertEqual(parse_alert_payload({"features": [{"no": "props"}]}), [])


class TestAlertBundle(unittest.TestCase):
    """Active/pending assembly and flag derivation."""

    def test_active_alerts_drive_flags(self) -> None:
        bundle = build_alert_bundle(
            [_props("Storm Warning", onset=-2, ends=20)], [], NOW
        )
        self.assertEqual(len(bundle.active), 1)
        self.assertEqual(bundle.pending, ())
        self.assertEqual(bundle.active_flags, (FLAG_STORM_WARNING,))
        self.assertEqual(bundle.highest_flag, FLAG_STORM_WARNING)
        self.assertEqual(bundle.highest_lifecycle, "active")
        self.assertEqual(
            bundle.combination, "storm_warning:active"
        )

    def test_pending_requires_future_onset(self) -> None:
        pending = _props("Hurricane Warning", onset=6, ends=48)
        bundle = build_alert_bundle([], [pending], NOW)
        self.assertEqual(len(bundle.pending), 1)
        self.assertEqual(bundle.highest_flag, FLAG_HURRICANE_WARNING)
        self.assertEqual(bundle.highest_lifecycle, "pending")

    def test_already_effective_is_not_pending(self) -> None:
        bundle = build_alert_bundle(
            [], [_props("Gale Warning", onset=-5, ends=5)], NOW
        )
        self.assertEqual(bundle.pending, ())

    def test_expired_alerts_dropped_from_pending(self) -> None:
        bundle = build_alert_bundle(
            [], [_props("Gale Warning", onset=-10, ends=-2)], NOW
        )
        self.assertEqual(bundle.pending, ())

    def test_alert_without_onset_counts_as_pending(self) -> None:
        bundle = build_alert_bundle([], [_props("Gale Warning", ends=10)], NOW)
        self.assertEqual(len(bundle.pending), 1)

    def test_duplicate_not_shown_twice(self) -> None:
        storm = _props("Storm Warning", onset=-2, ends=20)
        duplicate = dict(storm, id="urn:oid:2")
        bundle = build_alert_bundle([storm], [duplicate], NOW)
        self.assertEqual(len(bundle.active), 1)
        self.assertEqual(bundle.pending, ())

    def test_ignored_events_excluded(self) -> None:
        bundle = build_alert_bundle(
            [_props("Beach Hazards Statement", onset=-1, ends=10)], [], NOW
        )
        self.assertEqual(bundle.active, ())
        self.assertEqual(bundle.highest_flag, FLAG_NONE)

    def test_non_marine_events_excluded(self) -> None:
        bundle = build_alert_bundle(
            [_props("Winter Weather Advisory", onset=-1, ends=10)], [], NOW
        )
        self.assertEqual(bundle.active, ())
        self.assertEqual(bundle.highest_flag, FLAG_NONE)

    def test_other_marine_alert_tracked_without_flag(self) -> None:
        bundle = build_alert_bundle(
            [_props("Hazardous Seas Warning", onset=-1, ends=4)], [], NOW
        )
        self.assertEqual(len(bundle.active), 1)
        self.assertIsNone(bundle.active[0].flag)
        self.assertEqual(len(bundle.other), 1)
        self.assertEqual(bundle.highest_flag, FLAG_NONE)
        self.assertEqual(bundle.combination, FLAG_NONE)

    def test_highest_across_lifecycles(self) -> None:
        bundle = build_alert_bundle(
            [_props("Gale Warning", onset=-1, ends=6)],
            [_props("Storm Warning", onset=3, ends=30)],
            NOW,
        )
        self.assertEqual(bundle.highest_flag, FLAG_STORM_WARNING)
        self.assertEqual(bundle.highest_lifecycle, "pending")
        self.assertEqual(
            bundle.combination,
            "gale_warning:active | storm_warning:pending",
        )

    def test_same_flag_active_and_pending_reported_once(self) -> None:
        bundle = build_alert_bundle(
            [_props("Small Craft Advisory", onset=-1, ends=6)],
            [
                dict(
                    _props("Small Craft Advisory", onset=8, ends=30),
                    id="urn:oid:later",
                )
            ],
            NOW,
        )
        self.assertEqual(len(bundle.active), 1)
        self.assertEqual(len(bundle.pending), 1)
        self.assertEqual(bundle.combination, "small_craft_advisory:active")
        self.assertEqual(bundle.highest_flag, FLAG_SMALL_CRAFT_ADVISORY)
        self.assertEqual(bundle.highest_lifecycle, "active")

    def test_all_marine_includes_both(self) -> None:
        bundle = build_alert_bundle(
            [_props("Gale Warning", onset=-1, ends=6)],
            [_props("Storm Warning", onset=3, ends=30)],
            NOW,
        )
        self.assertEqual(len(bundle.all_marine), 2)

    def test_empty_bundle(self) -> None:
        bundle = build_alert_bundle([], [], NOW)
        self.assertEqual(bundle.active, ())
        self.assertEqual(bundle.pending, ())
        self.assertEqual(bundle.highest_flag, FLAG_NONE)
        self.assertIsNone(bundle.highest_lifecycle)
        self.assertEqual(bundle.combination, FLAG_NONE)


class FormatAlertWindowTest(unittest.TestCase):
    """Tests for the compact local-time window formatting."""

    def test_no_end_time(self) -> None:
        self.assertEqual(format_alert_window(None), "")

    def test_on_the_hour_drops_minutes(self) -> None:
        end = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(format_alert_window(end), "Saturday 8pm")

    def test_keeps_minutes_when_off_the_hour(self) -> None:
        end = datetime(2026, 9, 26, 20, 30, tzinfo=timezone.utc)
        self.assertEqual(format_alert_window(end), "Saturday 8:30pm")

    def test_midnight_is_twelve_am_not_zero(self) -> None:
        end = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(format_alert_window(end), "Saturday 12am")

    def test_noon_is_twelve_pm(self) -> None:
        end = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(format_alert_window(end), "Saturday 12pm")

    def test_tz_converts_the_instant(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        # 00:30 UTC on the 27th is 20:30 on the 26th in Eastern.
        end = datetime(2026, 9, 27, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(format_alert_window(end, eastern), "Saturday 8:30pm")


class FormatAlertTextTest(unittest.TestCase):
    """Tests for the one line alert summary."""

    def test_none_when_clear(self) -> None:
        self.assertIsNone(format_alert_text(build_alert_bundle([], [], NOW)))

    def test_title_with_window(self) -> None:
        bundle = build_alert_bundle(
            [_props("Storm Warning", onset=-1, ends=6)], [], NOW
        )
        # NOW is 2026-09-25 12:00 UTC, so ends is 18:00 UTC = 2pm Eastern.
        text = format_alert_text(bundle, timezone(timedelta(hours=-4)))
        self.assertEqual(text, "Storm Warning until Friday 2pm")

    def test_falls_back_to_bare_title_without_end_time(self) -> None:
        bundle = build_alert_bundle(
            [_props("Gale Warning", onset=-1, ends=None)], [], NOW
        )
        self.assertEqual(format_alert_text(bundle), "Gale Warning")

    def test_window_comes_from_the_flag_driving_alert(self) -> None:
        """A pending hurricane must not borrow the active gale's end time."""
        bundle = build_alert_bundle(
            [_props("Gale Warning", onset=-1, ends=2)],
            [_props("Hurricane Warning", onset=3, ends=50)],
            NOW,
        )
        self.assertEqual(bundle.highest_flag, FLAG_HURRICANE_WARNING)
        text = format_alert_text(bundle, timezone(timedelta(hours=-4)))
        # NOW+50h is Sun 14:00 UTC = Sun 10:00am Eastern. The gale ends at
        # NOW+2h, so borrowing its window would say "Friday 10am".
        self.assertEqual(text, "Hurricane Warning until Sunday 10am")


class SelectTopAlertTest(unittest.TestCase):
    """Tests for picking the alert that drives the highest flag."""

    def test_none_when_clear(self) -> None:
        bundle = build_alert_bundle([], [], NOW)
        self.assertIsNone(select_top_alert(bundle))
        self.assertIsNone(top_alert_detail(bundle))

    def test_prefers_flag_driver_over_first_alert(self) -> None:
        bundle = build_alert_bundle(
            [_props("Gale Warning", onset=-1, ends=2)],
            [_props("Hurricane Warning", onset=3, ends=50)],
            NOW,
        )
        top = select_top_alert(bundle)
        assert top is not None
        self.assertEqual(top.event, "HURRICANE WARNING")

    def test_detail_carries_alert_fields(self) -> None:
        bundle = build_alert_bundle(
            [_props("Storm Warning", onset=-1, ends=6)], [], NOW
        )
        detail = top_alert_detail(bundle)
        assert detail is not None
        self.assertEqual(detail["flag"], FLAG_STORM_WARNING)
        self.assertEqual(detail["flag_title"], "Storm Warning")
        self.assertEqual(detail["lifecycle"], "active")
        self.assertEqual(detail["severity"], "Severe")
        self.assertEqual(detail["area"], "Boston Harbor")
        self.assertTrue(str(detail["headline"]).startswith("Storm Warning"))
        # NOW is 2026-09-25 12:00 UTC; ends is +6h.
        self.assertEqual(detail["ends"], "2026-09-25T18:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
