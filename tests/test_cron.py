import datetime as dt
import unittest
from harbor.cron import Cron


class TestCron(unittest.TestCase):
    def test_every_15_min(self):
        c = Cron("*/15 * * * *")
        base = dt.datetime(2026, 8, 18, 10, 0, 0)
        self.assertTrue(c.matches(base))
        self.assertFalse(c.matches(dt.datetime(2026, 8, 18, 10, 7, 0)))
        self.assertEqual(c.next_after(base), dt.datetime(2026, 8, 18, 10, 15, 0))

    def test_daily_7am(self):
        c = Cron("0 7 * * *")
        nxt = c.next_after(dt.datetime(2026, 8, 18, 8, 0, 0))
        self.assertEqual(nxt, dt.datetime(2026, 8, 19, 7, 0, 0))

    def test_lists_and_ranges(self):
        c = Cron("0 9-17 * * 1-5")
        self.assertTrue(c.matches(dt.datetime(2026, 8, 18, 12, 0, 0)))  # Tue noon
        self.assertFalse(c.matches(dt.datetime(2026, 8, 22, 12, 0, 0)))  # Sat

    def test_invalid_field_count(self):
        with self.assertRaises(ValueError):
            Cron("0 7 * *")
