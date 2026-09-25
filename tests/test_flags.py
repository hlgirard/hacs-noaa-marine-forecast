"""Tests for the marine warning flag model."""

from __future__ import annotations

import unittest

from custom_components.noaa_marine_forecast.flags import (
    FLAG_GALE_WARNING,
    FLAG_HURRICANE_WARNING,
    FLAG_NONE,
    FLAG_SMALL_CRAFT_ADVISORY,
    FLAG_STORM_WARNING,
    flag_for_event,
    format_flag_combination,
    highest_flag,
    is_ignored_event,
    is_marine_event,
    normalize_event_name,
)


class TestEventMapping(unittest.TestCase):
    """NWS event name to flag mapping."""

    def test_flag_for_event(self) -> None:
        self.assertEqual(
            flag_for_event("Small Craft Advisory"), FLAG_SMALL_CRAFT_ADVISORY
        )
        self.assertEqual(flag_for_event("Gale Warning"), FLAG_GALE_WARNING)
        self.assertEqual(flag_for_event("Storm Warning"), FLAG_STORM_WARNING)
        self.assertEqual(
            flag_for_event("Hurricane Warning"), FLAG_HURRICANE_WARNING
        )

    def test_hurricane_force_wind_is_hurricane(self) -> None:
        self.assertEqual(
            flag_for_event("Hurricane Force Wind Warning"),
            FLAG_HURRICANE_WARNING,
        )

    def test_case_and_whitespace_insensitive(self) -> None:
        self.assertEqual(flag_for_event("  gale   warning "), FLAG_GALE_WARNING)
        self.assertEqual(normalize_event_name("Small  Craft Advisory"),
                         "SMALL CRAFT ADVISORY")

    def test_unknown_event_has_no_flag(self) -> None:
        self.assertIsNone(flag_for_event("Hazardous Seas Warning"))
        self.assertIsNone(flag_for_event(None))

    def test_ignored_events(self) -> None:
        self.assertTrue(is_ignored_event("Beach Hazards Statement"))
        self.assertTrue(is_ignored_event("Rip Current Statement"))

    def test_ignored_events_are_not_marine(self) -> None:
        self.assertFalse(is_marine_event("Beach Hazards Statement"))
        self.assertFalse(is_marine_event("Rip Current Statement"))
        self.assertTrue(is_marine_event("Storm Warning"))
        self.assertTrue(is_marine_event("Hazardous Seas Warning"))
        self.assertFalse(is_marine_event("Winter Weather Advisory"))


class TestHighestFlag(unittest.TestCase):
    """Highest severity selection."""

    def test_no_flags(self) -> None:
        self.assertEqual(highest_flag([], []), (FLAG_NONE, None))

    def test_single_active(self) -> None:
        self.assertEqual(
            highest_flag([FLAG_GALE_WARNING], []),
            (FLAG_GALE_WARNING, "active"),
        )

    def test_single_pending(self) -> None:
        self.assertEqual(
            highest_flag([], [FLAG_GALE_WARNING]), (FLAG_GALE_WARNING, "pending")
        )

    def test_multiple_active_picks_highest(self) -> None:
        self.assertEqual(
            highest_flag(
                [FLAG_SMALL_CRAFT_ADVISORY, FLAG_STORM_WARNING], []
            ),
            (FLAG_STORM_WARNING, "active"),
        )

    def test_severity_order(self) -> None:
        ordered = [
            FLAG_SMALL_CRAFT_ADVISORY,
            FLAG_GALE_WARNING,
            FLAG_STORM_WARNING,
            FLAG_HURRICANE_WARNING,
        ]
        for index in range(len(ordered) - 1):
            self.assertEqual(
                highest_flag([ordered[index]], [ordered[index + 1]])[0],
                ordered[index + 1],
            )

    def test_pending_outranks_active(self) -> None:
        self.assertEqual(
            highest_flag([FLAG_GALE_WARNING], [FLAG_HURRICANE_WARNING]),
            (FLAG_HURRICANE_WARNING, "pending"),
        )

    def test_input_order_does_not_matter(self) -> None:
        self.assertEqual(
            highest_flag(
                [FLAG_STORM_WARNING, FLAG_SMALL_CRAFT_ADVISORY], []
            ),
            (FLAG_STORM_WARNING, "active"),
        )


class TestCombination(unittest.TestCase):
    """Dashboard friendly combination string."""

    def test_none(self) -> None:
        self.assertEqual(format_flag_combination([], []), FLAG_NONE)

    def test_active_only(self) -> None:
        self.assertEqual(
            format_flag_combination([FLAG_GALE_WARNING], []),
            "gale_warning:active",
        )

    def test_active_and_pending_sorted_by_severity(self) -> None:
        self.assertEqual(
            format_flag_combination(
                [FLAG_GALE_WARNING], [FLAG_STORM_WARNING]
            ),
            "gale_warning:active | storm_warning:pending",
        )

    def test_duplicates_collapsed(self) -> None:
        self.assertEqual(
            format_flag_combination(
                [FLAG_GALE_WARNING, FLAG_GALE_WARNING], []
            ),
            "gale_warning:active",
        )

    def test_active_flag_not_repeated_as_pending(self) -> None:
        # The NWS returns a new alert instance per lifecycle, so the same flag
        # can be both active and pending; it must be reported once.
        self.assertEqual(
            format_flag_combination(
                [FLAG_SMALL_CRAFT_ADVISORY], [FLAG_SMALL_CRAFT_ADVISORY]
            ),
            "small_craft_advisory:active",
        )

    def test_pending_distinct_flags_both_shown(self) -> None:
        self.assertEqual(
            format_flag_combination(
                [FLAG_SMALL_CRAFT_ADVISORY], [FLAG_STORM_WARNING]
            ),
            "small_craft_advisory:active | storm_warning:pending",
        )


if __name__ == "__main__":
    unittest.main()
