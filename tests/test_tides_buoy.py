"""Pure-Python tests for the CO-OPS and NDBC parsers (real API fixtures)."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from custom_components.noaa_marine_forecast import buoy, tides

DATA = Path(__file__).parent / "data"
UTC = timezone.utc


def _json(name: str):
    return json.loads((DATA / name).read_text())


class TestStationInfo(unittest.TestCase):
    def test_parses_metadata(self) -> None:
        info = tides.parse_station_info(_json("coops_station.json"), "8443970")
        self.assertEqual(info.name, "Boston")
        self.assertEqual(info.state, "MA")
        self.assertFalse(info.great_lakes)
        self.assertAlmostEqual(info.latitude, 42.35389)

    def test_unknown_station(self) -> None:
        payload = {"errorMsg": "No station was found for id 9999999", "errorCode": 404}
        self.assertIsNone(tides.parse_station_info(payload, "9999999"))
        self.assertIsNone(tides.parse_station_info({}, "1"))


class TestReadings(unittest.TestCase):
    def test_water_level(self) -> None:
        reading = tides.parse_latest_reading(
            _json("coops_water_level.json"), "water_level"
        )
        self.assertEqual(reading.value, 3.251)
        self.assertEqual(reading.time, datetime(2026, 11, 13, 17, 36, tzinfo=UTC))

    def test_air_temperature(self) -> None:
        reading = tides.parse_latest_reading(
            _json("coops_air_temperature.json"), "air_temperature"
        )
        self.assertEqual(reading.value, 5.4)

    def test_no_data_and_error_payloads(self) -> None:
        for name in ("coops_no_data.json", "coops_error.json"):
            self.assertIsNone(
                tides.parse_latest_reading(_json(name), "wind"), name
            )

    def test_blank_values_skipped(self) -> None:
        payload = {
            "data": [
                {"t": "2026-11-13 17:30", "v": "2.0"},
                {"t": "2026-11-13 17:36", "v": ""},
            ]
        }
        reading = tides.parse_latest_reading(payload, "water_level")
        self.assertEqual(reading.value, 2.0)

    def test_wind_format(self) -> None:
        # Synthetic: shaped like the documented CO-OPS wind product
        # (s speed, d degrees, dr cardinal, g gust, f flags).
        payload = {
            "data": [
                {"t": "2026-11-13 17:36", "s": "5.1", "d": "270.00", "dr": "W",
                 "g": "7.2", "f": "0,0"}
            ]
        }
        reading = tides.parse_latest_reading(payload, "wind")
        self.assertEqual(reading.value, 5.1)
        self.assertEqual(reading.extra, {"gust": 7.2, "direction": 270.0})


class TestConvertLevel(unittest.TestCase):
    def test_conversions(self) -> None:
        self.assertEqual(tides.convert_level(1.0, "m"), 1.0)
        self.assertEqual(tides.convert_level(1.0, "ft"), 3.281)
        self.assertEqual(tides.convert_level(-0.5, "ft"), -1.64)
        self.assertEqual(tides.convert_level(2.621, "ft", 1), 8.6)
        self.assertEqual(tides.convert_level(2.621, "m", 1), 2.6)


class TestPredictions(unittest.TestCase):
    def setUp(self) -> None:
        self.data = tides.TideData(
            "8443970",
            "Boston",
            datetime(2026, 11, 13, 17, 36, tzinfo=UTC),
            {},
            tides.parse_predictions(_json("coops_hilo.json")),
            "MLLW",
        )

    def test_parsed_and_sorted(self) -> None:
        self.assertEqual(len(self.data.predictions), 7)
        times = [p.time for p in self.data.predictions]
        self.assertEqual(times, sorted(times))

    def test_next_tides(self) -> None:
        now = datetime(2026, 11, 13, 5, 0, tzinfo=UTC)
        high = self.data.next_tide(tides.TIDE_HIGH, now)
        low = self.data.next_tide(tides.TIDE_LOW, now)
        self.assertEqual(high.time, datetime(2026, 11, 13, 6, 30, tzinfo=UTC))
        self.assertEqual(low.time, datetime(2026, 11, 13, 12, 20, tzinfo=UTC))

    def test_upcoming_tide_is_next_of_either_kind(self) -> None:
        nxt = self.data.upcoming_tide(datetime(2026, 11, 13, 8, 0, tzinfo=UTC))
        self.assertEqual(nxt.kind, tides.TIDE_LOW)
        self.assertEqual(nxt.time, datetime(2026, 11, 13, 12, 20, tzinfo=UTC))
        self.assertIsNone(
            self.data.upcoming_tide(datetime(2026, 11, 14, 0, 0, tzinfo=UTC))
        )

    def test_tide_state(self) -> None:
        self.assertEqual(
            self.data.tide_state(datetime(2026, 11, 13, 3, 0, tzinfo=UTC)), "rising"
        )
        self.assertEqual(
            self.data.tide_state(datetime(2026, 11, 13, 8, 0, tzinfo=UTC)), "falling"
        )
        self.assertIsNone(
            self.data.tide_state(datetime(2026, 11, 14, 0, 0, tzinfo=UTC))
        )

    def test_error_gives_empty(self) -> None:
        self.assertEqual(tides.parse_predictions(_json("coops_error.json")), ())


class TestBuoy(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (DATA / "ndbc_44013.txt").read_text()

    def test_latest_values_and_missing_fill(self) -> None:
        observed, readings = buoy.parse_realtime(self.text)
        self.assertEqual(observed, datetime(2026, 11, 13, 17, 10, tzinfo=UTC))
        self.assertEqual(readings["WSPD"].value, 9.0)
        self.assertEqual(readings["WSPD"].time, observed)
        # Waves are MM on the newest rows; the value comes from the 16:50 row.
        self.assertEqual(readings["WVHT"].value, 2.4)
        self.assertEqual(
            readings["WVHT"].time, datetime(2026, 11, 13, 16, 50, tzinfo=UTC)
        )

    def test_build_data(self) -> None:
        data = buoy.build_buoy_data(
            "44013", "Boston Buoy", self.text, datetime(2026, 11, 13, 17, 20, tzinfo=UTC)
        )
        self.assertEqual(data.value("PRES"), 1000.9)
        self.assertIsNone(data.value("NOPE"))

    def test_truncated_and_short_rows_are_skipped(self) -> None:
        lines = self.text.splitlines()
        # Header, a row cut off mid-way, then complete rows.
        text = "\n".join(lines[:2] + ["2026 11 13 17 20  10  9"] + lines[2:5])
        observed, readings = buoy.parse_realtime(text)
        self.assertEqual(observed, datetime(2026, 11, 13, 17, 10, tzinfo=UTC))
        self.assertEqual(readings["WSPD"].value, 9.0)

    def test_rejects_garbage(self) -> None:
        for text in ("", "<html>Not found</html>", "#only header\n"):
            with self.assertRaises(ValueError, msg=text):
                buoy.parse_realtime(text)


class TestIcons(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).parent.parent / "custom_components" / "noaa_marine_forecast"
        self.icons = json.loads((base / "icons.json").read_text())["entity"]["sensor"]
        self.strings = json.loads((base / "strings.json").read_text())["entity"]["sensor"]

    def test_tide_state_and_next_tide_icons(self) -> None:
        self.assertEqual(self.icons["tide_state"]["default"], "mdi:waves")
        self.assertEqual(
            self.icons["tide_state"]["state"],
            {"rising": "mdi:wave-arrow-up", "falling": "mdi:wave-arrow-down"},
        )
        self.assertEqual(self.icons["next_tide"]["default"], "mdi:waves")
        self.assertEqual(
            self.icons["next_tide"]["state"],
            {"high": "mdi:wave-arrow-up", "low": "mdi:wave-arrow-down"},
        )

    def test_icon_states_match_translated_states(self) -> None:
        for key, entry in self.icons.items():
            self.assertIn(key, self.strings, key)
            for state in entry.get("state", {}):
                self.assertIn(state, self.strings[key]["state"], f"{key}.{state}")


if __name__ == "__main__":
    unittest.main()
