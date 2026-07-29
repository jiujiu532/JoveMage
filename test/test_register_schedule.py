from __future__ import annotations

import os
import unittest
from datetime import date, datetime, time as dt_time

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register_service import (
    SCHEDULE_DEFAULTS,
    _active_schedule_window,
    _next_schedule_window,
    _normalize_schedule,
    _normalize_window,
    _parse_hhmm,
    _window_bounds,
)
from utils.timezone import BEIJING_TZ


def _bj(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BEIJING_TZ)


class ParseHhmmTests(unittest.TestCase):
    def test_valid_full_and_single_digit_hour(self):
        self.assertEqual(_parse_hhmm("10:30"), dt_time(10, 30))
        self.assertEqual(_parse_hhmm("8:05"), dt_time(8, 5))
        self.assertEqual(_parse_hhmm("00:00"), dt_time(0, 0))
        self.assertEqual(_parse_hhmm("23:59"), dt_time(23, 59))

    def test_strips_whitespace(self):
        self.assertEqual(_parse_hhmm("  9:15  "), dt_time(9, 15))

    def test_invalid_values_return_none(self):
        for value in ("24:00", "12:60", "", None, "abc", "1:2", "25:01", "10:5", "10:300"):
            with self.subTest(value=value):
                self.assertIsNone(_parse_hhmm(value))


class NormalizeWindowTests(unittest.TestCase):
    def test_pads_zero_and_keeps_cross_day(self):
        self.assertEqual(
            _normalize_window({"start": "8:05", "end": "9:00"}),
            {"start": "08:05", "end": "09:00"},
        )
        self.assertEqual(
            _normalize_window({"start": "23:00", "end": "1:00"}),
            {"start": "23:00", "end": "01:00"},
        )

    def test_start_equals_end_is_invalid(self):
        self.assertIsNone(_normalize_window({"start": "10:00", "end": "10:00"}))

    def test_invalid_time_or_type_returns_none(self):
        self.assertIsNone(_normalize_window({"start": "24:00", "end": "10:00"}))
        self.assertIsNone(_normalize_window({"start": "10:00", "end": "abc"}))
        self.assertIsNone(_normalize_window("not-a-dict"))  # type: ignore[arg-type]
        self.assertIsNone(_normalize_window({}))


class NormalizeScheduleTests(unittest.TestCase):
    def test_defaults_when_empty(self):
        result = _normalize_schedule(None)
        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["threads"], SCHEDULE_DEFAULTS["threads"])
        self.assertEqual(result["max_relogin_retries"], SCHEDULE_DEFAULTS["max_relogin_retries"])
        self.assertEqual(result["preempt_minutes"], SCHEDULE_DEFAULTS["preempt_minutes"])
        self.assertEqual(result["drain_timeout_minutes"], SCHEDULE_DEFAULTS["drain_timeout_minutes"])

    def test_enabled_bool_coercion(self):
        self.assertTrue(_normalize_schedule({"enabled": "yes"})["enabled"])
        self.assertFalse(_normalize_schedule({"enabled": "off"})["enabled"])
        self.assertTrue(_normalize_schedule({"enabled": True})["enabled"])

    def test_filters_invalid_windows(self):
        result = _normalize_schedule(
            {
                "windows": [
                    {"start": "10:00", "end": "11:00"},
                    {"start": "10:00", "end": "10:00"},
                    {"start": "bad", "end": "11:00"},
                    "skip-me",
                    {"start": "23:00", "end": "01:00"},
                ]
            }
        )
        self.assertEqual(
            result["windows"],
            [
                {"start": "10:00", "end": "11:00"},
                {"start": "23:00", "end": "01:00"},
            ],
        )

    def test_clamps_numeric_fields(self):
        result = _normalize_schedule(
            {
                "threads": 999,
                "max_relogin_retries": -5,
                "preempt_minutes": "30",
                "drain_timeout_minutes": "not-int",
            }
        )
        self.assertEqual(result["threads"], 200)
        self.assertEqual(result["max_relogin_retries"], 0)
        self.assertEqual(result["preempt_minutes"], 30)
        self.assertEqual(result["drain_timeout_minutes"], SCHEDULE_DEFAULTS["drain_timeout_minutes"])


class WindowBoundsTests(unittest.TestCase):
    def test_same_day_window(self):
        day = date(2026, 7, 29)
        start_dt, end_dt = _window_bounds(day, dt_time(10, 0), dt_time(11, 0))
        self.assertEqual(start_dt, _bj(2026, 7, 29, 10, 0))
        self.assertEqual(end_dt, _bj(2026, 7, 29, 11, 0))

    def test_cross_day_end_is_next_day(self):
        day = date(2026, 7, 29)
        start_dt, end_dt = _window_bounds(day, dt_time(23, 0), dt_time(1, 0))
        self.assertEqual(start_dt, _bj(2026, 7, 29, 23, 0))
        self.assertEqual(end_dt, _bj(2026, 7, 30, 1, 0))


class ActiveScheduleWindowTests(unittest.TestCase):
    def test_hits_same_day_window(self):
        now = _bj(2026, 7, 29, 10, 30)
        hit = _active_schedule_window(now, [{"start": "10:00", "end": "11:00"}])
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["start"], "10:00")
        self.assertEqual(hit["end"], "11:00")
        self.assertEqual(hit["start_dt"], _bj(2026, 7, 29, 10, 0))
        self.assertEqual(hit["end_dt"], _bj(2026, 7, 29, 11, 0))

    def test_misses_outside_same_day_window(self):
        now = _bj(2026, 7, 29, 9, 0)
        self.assertIsNone(_active_schedule_window(now, [{"start": "10:00", "end": "11:00"}]))

    def test_hits_cross_day_first_half(self):
        now = _bj(2026, 7, 29, 23, 30)
        hit = _active_schedule_window(now, [{"start": "23:00", "end": "01:00"}])
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["start_dt"], _bj(2026, 7, 29, 23, 0))
        self.assertEqual(hit["end_dt"], _bj(2026, 7, 30, 1, 0))

    def test_hits_cross_day_second_half(self):
        now = _bj(2026, 7, 30, 0, 30)
        hit = _active_schedule_window(now, [{"start": "23:00", "end": "01:00"}])
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["start_dt"], _bj(2026, 7, 29, 23, 0))
        self.assertEqual(hit["end_dt"], _bj(2026, 7, 30, 1, 0))

    def test_misses_outside_cross_day_window(self):
        now = _bj(2026, 7, 30, 2, 0)
        self.assertIsNone(_active_schedule_window(now, [{"start": "23:00", "end": "01:00"}]))

    def test_end_boundary_is_exclusive(self):
        now = _bj(2026, 7, 29, 11, 0)
        self.assertIsNone(_active_schedule_window(now, [{"start": "10:00", "end": "11:00"}]))

    def test_empty_windows(self):
        self.assertIsNone(_active_schedule_window(_bj(2026, 7, 29, 10, 30), []))


class NextScheduleWindowTests(unittest.TestCase):
    def test_empty_windows_returns_none(self):
        self.assertIsNone(_next_schedule_window(_bj(2026, 7, 29, 10, 0), []))

    def test_returns_in_progress_window(self):
        now = _bj(2026, 7, 29, 10, 30)
        nxt = _next_schedule_window(now, [{"start": "10:00", "end": "11:00"}])
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(nxt["start_dt"], _bj(2026, 7, 29, 10, 0))
        self.assertEqual(nxt["end_dt"], _bj(2026, 7, 29, 11, 0))

    def test_returns_nearest_future_window(self):
        now = _bj(2026, 7, 29, 9, 0)
        nxt = _next_schedule_window(
            now,
            [
                {"start": "14:00", "end": "15:00"},
                {"start": "10:00", "end": "11:00"},
            ],
        )
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(nxt["start"], "10:00")
        self.assertEqual(nxt["start_dt"], _bj(2026, 7, 29, 10, 0))

    def test_wraps_to_next_day(self):
        now = _bj(2026, 7, 29, 20, 0)
        nxt = _next_schedule_window(now, [{"start": "10:00", "end": "11:00"}])
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(nxt["start_dt"], _bj(2026, 7, 30, 10, 0))

    def test_cross_day_in_progress(self):
        now = _bj(2026, 7, 30, 0, 30)
        nxt = _next_schedule_window(now, [{"start": "23:00", "end": "01:00"}])
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(nxt["start_dt"], _bj(2026, 7, 29, 23, 0))
        self.assertEqual(nxt["end_dt"], _bj(2026, 7, 30, 1, 0))


if __name__ == "__main__":
    unittest.main()
