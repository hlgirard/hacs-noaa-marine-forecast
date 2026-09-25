"""Tests for NWS CAP alert normalization."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from custom_components.noaa_marine_forecast.alerts import (
    build_alert_bundle,
    normalize_alert,
    parse_alert_payload,
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


if __name__ == "__main__":
    unittest.main()
