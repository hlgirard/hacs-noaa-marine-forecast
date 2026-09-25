"""Tests for the NOAA forecast parser."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from custom_components.noaa_marine_forecast.parser import (
    PART_DAY,
    PART_NIGHT,
    format_hazard_title,
    parse_forecast,
    select_now_next,
)
from tests.fixtures import ANZ230_PRODUCT, EVENING_PRODUCT, GMZ130_PRODUCT

EASTERN = ZoneInfo("America/New_York")


class TestProductMetadata(unittest.TestCase):
    """Header and metadata parsing."""

    def setUp(self) -> None:
        self.product = parse_forecast(ANZ230_PRODUCT, "ANZ230")

    def test_wmo_and_awips(self) -> None:
        self.assertEqual(self.product.wmo_id, "FZUS51")
        self.assertEqual(self.product.awips_id, "CWFBOX")
        self.assertEqual(self.product.office, "KBOX")
        self.assertEqual(self.product.raw_header, "FZUS51 KBOX 251404")

    def test_office_and_title(self) -> None:
        self.assertEqual(
            self.product.office_name, "National Weather Service Boston/Norton MA"
        )
        self.assertEqual(
            self.product.product_title,
            "Coastal Waters Forecast for Massachusetts and Rhode Island",
        )

    def test_area_description(self) -> None:
        self.assertEqual(
            self.product.area_description,
            "Coastal waters from the Merrimack River MA to Watch Hill RI "
            "out to 60 NM",
        )

    def test_issue_and_expiry(self) -> None:
        self.assertEqual(
            self.product.issued, datetime(2026, 9, 25, 10, 3, tzinfo=EASTERN)
        )
        self.assertEqual(
            self.product.expires, datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(self.product.tz_abbreviation, "EDT")
        self.assertEqual(self.product.timezone, EASTERN)

    def test_zone_and_name(self) -> None:
        self.assertEqual(self.product.zones, ("ANZ230",))
        self.assertEqual(self.product.zone_name(), "Boston Harbor")

    def test_hazard_summary_joins_wrapped_lines(self) -> None:
        self.assertEqual(
            self.product.hazard_summary,
            "STORM WARNING IN EFFECT FROM 2 PM EDT THIS AFTERNOON THROUGH "
            "SATURDAY EVENING",
        )

    def test_hazard_title_normalizes_first_statement(self) -> None:
        self.assertEqual(
            format_hazard_title(self.product.hazard_summary),
            "Storm Warning in Effect from 2 PM EDT This Afternoon through "
            "Saturday Evening",
        )

    def test_hazard_title_takes_first_statement_only(self) -> None:
        self.assertEqual(
            format_hazard_title("GALE WARNING TONIGHT | SMALL CRAFT ADVISORY SAT."),
            "Gale Warning Tonight",
        )

    def test_hazard_title_none_for_empty(self) -> None:
        self.assertIsNone(format_hazard_title(None))
        self.assertIsNone(format_hazard_title(""))
        self.assertIsNone(format_hazard_title("..."))

    def test_additional_text_after_periods(self) -> None:
        assert self.product.additional_text is not None
        self.assertIn("significant wave height", self.product.additional_text)

    def test_no_parse_errors(self) -> None:
        self.assertEqual(self.product.parse_errors, ())


class TestPeriods(unittest.TestCase):
    """Period normalization."""

    def setUp(self) -> None:
        self.product = parse_forecast(ANZ230_PRODUCT, "ANZ230")

    def test_period_count_and_labels(self) -> None:
        labels = [period.source_label for period in self.product.periods]
        self.assertEqual(
            labels,
            [
                "THIS AFTERNOON",
                "TONIGHT",
                "SAT",
                "SAT NIGHT",
                "SUN",
                "SUN NIGHT",
                "MON",
            ],
        )

    def test_period_dates(self) -> None:
        friday = date(2026, 9, 25)
        saturday = date(2026, 9, 26)
        sunday = date(2026, 9, 27)
        monday = date(2026, 9, 28)
        by_label = {p.source_label: p for p in self.product.periods}
        self.assertEqual(by_label["THIS AFTERNOON"].period_date, friday)
        self.assertEqual(by_label["TONIGHT"].period_date, friday)
        self.assertEqual(by_label["SAT"].period_date, saturday)
        self.assertEqual(by_label["SAT NIGHT"].period_date, saturday)
        self.assertEqual(by_label["SUN"].period_date, sunday)
        self.assertEqual(by_label["MON"].period_date, monday)

    def test_day_and_night_parts(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        self.assertEqual(by_label["THIS AFTERNOON"].part, PART_DAY)
        self.assertEqual(by_label["SAT"].part, PART_DAY)
        self.assertEqual(by_label["TONIGHT"].part, PART_NIGHT)
        self.assertEqual(by_label["SAT NIGHT"].part, PART_NIGHT)

    def test_afternoon_window(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        afternoon = by_label["THIS AFTERNOON"]
        self.assertEqual(afternoon.start_time, time(12, 0))
        self.assertEqual(afternoon.end_time, time(18, 0))

    def test_night_window_spans_midnight(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        tonight = by_label["TONIGHT"]
        self.assertEqual(tonight.start_time, time(18, 0))
        self.assertEqual(tonight.end_time, time(6, 0))
        self.assertTrue(tonight.end_next_day)

    def test_combined_period_is_split(self) -> None:
        labels = [p.source_label for p in self.product.periods]
        self.assertIn("SUN", labels)
        self.assertIn("SUN NIGHT", labels)
        day = next(p for p in self.product.periods if p.source_label == "SUN")
        night = next(p for p in self.product.periods if p.source_label == "SUN NIGHT")
        self.assertEqual(day.part, PART_DAY)
        self.assertEqual(night.part, PART_NIGHT)
        self.assertEqual(day.text, night.text)

    def test_wrapped_text_is_joined(self) -> None:
        tonight = next(
            p for p in self.product.periods if p.source_label == "TONIGHT"
        )
        self.assertEqual(
            tonight.text,
            "NE winds 20 to 25 kt with gusts up to 40 kt. Waves 2 to 3 ft, "
            "except 4 to 6 ft at the outer harbor entrance. A chance of rain. "
            "Patchy fog after midnight.",
        )

    def test_periods_by_part_lookup(self) -> None:
        lookup = self.product.periods_by_part()
        friday = date(2026, 9, 25)
        self.assertEqual(lookup[(friday, PART_NIGHT)].source_label, "TONIGHT")
        # THIS AFTERNOON stands in for the "today" daytime period, since this
        # product has no plain TODAY marker.
        self.assertEqual(
            lookup[(friday, PART_DAY)].source_label, "THIS AFTERNOON"
        )


class TestNowNextSelection(unittest.TestCase):
    """Now/Next selection across products and times of day."""

    def test_afternoon_product_selects_this_afternoon(self) -> None:
        product = parse_forecast(ANZ230_PRODUCT, "ANZ230")
        moment = datetime(2026, 9, 25, 14, 0, tzinfo=EASTERN)
        now, nxt, method = select_now_next(product, moment)
        assert now is not None
        assert nxt is not None
        self.assertEqual(now.source_label, "THIS AFTERNOON")
        self.assertEqual(nxt.source_label, "TONIGHT")
        self.assertEqual(method, "current_window")

    def test_evening_product_selects_tonight(self) -> None:
        product = parse_forecast(EVENING_PRODUCT, "ANZ230")
        moment = datetime(2026, 9, 25, 21, 0, tzinfo=EASTERN)
        now, nxt, method = select_now_next(product, moment)
        assert now is not None
        assert nxt is not None
        self.assertEqual(now.source_label, "TONIGHT")
        self.assertEqual(nxt.source_label, "SAT")
        self.assertEqual(method, "current_window")

    def test_no_this_afternoon_in_evening_product(self) -> None:
        product = parse_forecast(EVENING_PRODUCT, "ANZ230")
        labels = [p.source_label for p in product.periods]
        self.assertNotIn("THIS AFTERNOON", labels)
        self.assertEqual(labels[0], "TONIGHT")

    def test_morning_selects_today(self) -> None:
        product = parse_forecast(GMZ130_PRODUCT, "GMZ130")
        central = ZoneInfo("America/Chicago")
        moment = datetime(2026, 9, 25, 8, 0, tzinfo=central)
        now, nxt, _ = select_now_next(product, moment)
        assert now is not None and nxt is not None
        self.assertEqual(now.source_label, "TODAY")
        self.assertEqual(nxt.source_label, "TONIGHT")

    def test_moment_after_last_period_uses_last_available(self) -> None:
        product = parse_forecast(ANZ230_PRODUCT, "ANZ230")
        moment = datetime(2026, 10, 20, 12, 0, tzinfo=EASTERN)
        now, nxt, method = select_now_next(product, moment)
        assert now is not None
        self.assertEqual(now.source_label, "MON")
        self.assertIsNone(nxt)
        self.assertEqual(method, "last_available")

    def test_moment_before_first_period_uses_upcoming(self) -> None:
        product = parse_forecast(ANZ230_PRODUCT, "ANZ230")
        moment = datetime(2026, 9, 20, 12, 0, tzinfo=EASTERN)
        now, _, method = select_now_next(product, moment)
        assert now is not None
        self.assertEqual(now.source_label, "THIS AFTERNOON")
        self.assertEqual(method, "upcoming")

    def test_no_periods_returns_none(self) -> None:
        product = parse_forecast("nothing useful here\n", "ANZ230")
        now, nxt, method = select_now_next(
            product, datetime(2026, 9, 25, 12, tzinfo=EASTERN)
        )
        self.assertIsNone(now)
        self.assertIsNone(nxt)
        self.assertEqual(method, "no_periods")


#: A product with composite ``THROUGH`` ranges, mirroring the live ANZ230
#: product of 2026-09-25.
THROUGH_PRODUCT = """\
FZUS51 KBOX 252004
CWFBOX

Coastal Waters Forecast for Massachusetts and Rhode Island
National Weather Service Boston/Norton MA
403 PM EDT Fri Sep 25 2026

Coastal waters from the Merrimack River MA to Watch Hill RI out
to 60 NM

ANZ230-260900-
Boston Harbor-
403 PM EDT Fri Sep 25 2026

...STORM WARNING IN EFFECT THROUGH SATURDAY EVENING...

.TONIGHT...NE winds 20 to 25 kt with gusts up to 35 kt. Waves 2 to 3 ft.
.SAT...NE winds 20 to 25 kt, increasing to 25 to 30 kt in the afternoon. Rain.
.SAT NIGHT...NE winds 25 to 30 kt with gusts up to 50 kt. Rain.
.SUN...NE winds 20 to 25 kt with gusts up to 45 kt. Rain.
.SUN NIGHT THROUGH MON NIGHT...NE winds 15 to 20 kt with gusts up to 35 kt. Rain.
.TUE...N winds 5 to 10 kt. Waves 1 foot or less.
.TUE NIGHT THROUGH WED NIGHT...SW winds around 5 kt. Waves 1 foot or less.

Seas are reported as significant wave height.

$$
"""


class TestThroughRanges(unittest.TestCase):
    """Composite ``THROUGH`` labels span the whole range, with no gaps."""

    def setUp(self) -> None:
        self.product = parse_forecast(THROUGH_PRODUCT, "ANZ230")

    def test_composite_gets_end_date(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        span = by_label["SUN NIGHT THROUGH MON NIGHT"]
        self.assertEqual(span.period_date, date(2026, 9, 27))
        self.assertEqual(span.end_date, date(2026, 9, 28))
        start, end = span.window(EASTERN)
        self.assertEqual(start, datetime(2026, 9, 27, 18, 0, tzinfo=EASTERN))
        # Monday night ends Tuesday at 06:00.
        self.assertEqual(end, datetime(2026, 9, 29, 6, 0, tzinfo=EASTERN))

    def test_single_periods_have_no_end_date(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        self.assertIsNone(by_label["SAT"].end_date)
        start, end = by_label["SAT"].window(EASTERN)
        self.assertEqual(start, datetime(2026, 9, 26, 6, 0, tzinfo=EASTERN))
        self.assertEqual(end, datetime(2026, 9, 26, 18, 0, tzinfo=EASTERN))

    def test_no_gap_across_full_horizon(self) -> None:
        """Every 6h step from Friday evening to Wednesday noon is covered."""
        expected = {
            (25, 20): "TONIGHT",
            (26, 2): "TONIGHT",
            (26, 8): "SAT",
            (26, 14): "SAT",
            (26, 20): "SAT NIGHT",
            (27, 2): "SAT NIGHT",
            (27, 8): "SUN",
            (27, 14): "SUN",
            (27, 20): "SUN NIGHT THROUGH MON NIGHT",
            (28, 2): "SUN NIGHT THROUGH MON NIGHT",
            (28, 8): "SUN NIGHT THROUGH MON NIGHT",
            (28, 14): "SUN NIGHT THROUGH MON NIGHT",
            (28, 20): "SUN NIGHT THROUGH MON NIGHT",
            (29, 2): "SUN NIGHT THROUGH MON NIGHT",
            (29, 8): "TUE",
            (29, 14): "TUE",
            (29, 20): "TUE NIGHT THROUGH WED NIGHT",
            (30, 2): "TUE NIGHT THROUGH WED NIGHT",
        }
        for (day, hour), label in expected.items():
            moment = datetime(2026, 9, day, hour, tzinfo=EASTERN)
            now, _, method = select_now_next(self.product, moment, EASTERN)
            assert now is not None, f"gap at {moment}"
            self.assertEqual(now.source_label, label, f"at {moment}")
            self.assertEqual(method, "current_window", f"at {moment}")


class TestGroupedProduct(unittest.TestCase):
    """Products covering several zones."""

    def setUp(self) -> None:
        self.product = parse_forecast(GMZ130_PRODUCT, "GMZ130")

    def test_all_zone_ids_expanded(self) -> None:
        self.assertEqual(self.product.zones, ("GMZ130", "GMZ132", "GMZ135"))

    def test_all_zone_names_parsed_including_wrapped(self) -> None:
        self.assertEqual(len(self.product.zone_names), 3)
        self.assertEqual(
            self.product.zone_names[1],
            "Laguna Madre from the Arroyo Colorado To 5 NM north of Port "
            "Mansfield TX",
        )

    def test_zone_name_lookup(self) -> None:
        product = parse_forecast(GMZ130_PRODUCT, "GMZ135")
        self.assertEqual(
            product.zone_name(),
            "Laguna Madre from 5 nm north of Port Mansfield to Baffin Bay TX",
        )

    def test_weekday_words_resolve_to_dates(self) -> None:
        by_label = {p.source_label: p for p in self.product.periods}
        self.assertEqual(by_label["SATURDAY"].period_date, date(2026, 9, 26))
        self.assertEqual(
            by_label["SATURDAY NIGHT"].period_date, date(2026, 9, 26)
        )


class TestRobustness(unittest.TestCase):
    """Malformed or unusual input."""

    def test_empty_input(self) -> None:
        product = parse_forecast("", "ANZ230")
        self.assertEqual(product.periods, ())
        self.assertTrue(product.parse_errors)

    def test_missing_zone_block_reports_error(self) -> None:
        product = parse_forecast("FZUS51 KBOX 251404\n", "ANZ230")
        self.assertTrue(
            any("zone group" in error for error in product.parse_errors)
        )

    def test_product_without_awips_line(self) -> None:
        text = (
            "FZUS51 KBOX 251404\n"
            "\n"
            "Coastal Waters Forecast\n"
            "National Weather Service Boston/Norton MA\n"
            "1003 AM EDT Fri Sep 25 2026\n"
            "\n"
            "ANZ230-260300-\n"
            "Boston Harbor-\n"
            "1003 AM EDT Fri Sep 25 2026\n"
            "\n"
            ".TONIGHT...W winds 20 to 30 kt.\n"
            "\n"
            "$$\n"
        )
        product = parse_forecast(text, "ANZ230")
        self.assertEqual(product.wmo_id, "FZUS51")
        self.assertIsNone(product.awips_id)
        self.assertEqual(len(product.periods), 1)

    def test_today_and_tomorrow_labels(self) -> None:
        text = (
            "FZUS51 KBOX 251404\n"
            "CWFBOX\n"
            "\n"
            "Coastal Waters Forecast\n"
            "National Weather Service Boston/Norton MA\n"
            "1003 AM EDT Fri Sep 25 2026\n"
            "\n"
            "ANZ230-260300-\n"
            "Boston Harbor-\n"
            "1003 AM EDT Fri Sep 25 2026\n"
            "\n"
            ".TODAY...W winds 10 kt.\n"
            ".TONIGHT...W winds 20 kt.\n"
            ".TOMORROW...W winds 15 kt.\n"
            ".TOMORROW NIGHT...W winds 25 kt.\n"
            "\n"
            "$$\n"
        )
        product = parse_forecast(text, "ANZ230")
        by_label = {p.source_label: p for p in product.periods}
        self.assertEqual(by_label["TODAY"].period_date, date(2026, 9, 25))
        self.assertEqual(by_label["TOMORROW"].period_date, date(2026, 9, 26))
        self.assertEqual(
            by_label["TOMORROW NIGHT"].period_date, date(2026, 9, 26)
        )
        self.assertEqual(by_label["TOMORROW NIGHT"].part, PART_NIGHT)


if __name__ == "__main__":
    unittest.main()
