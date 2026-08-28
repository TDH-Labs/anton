"""config.py loading and DEFAULTS isolation."""
from __future__ import annotations

import unittest

from anton.config import DEFAULTS, deep_merge, load_config


class TestDeepMerge(unittest.TestCase):
    def test_override_wins_at_the_leaf(self):
        out = deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}})
        self.assertEqual(out, {"a": {"b": 9, "c": 2}})

    def test_a_non_dict_override_replaces_a_dict(self):
        self.assertEqual(deep_merge({"a": {"b": 1}}, {"a": 5}), {"a": 5})

    def test_empty_override_returns_an_equal_but_independent_copy(self):
        base = {"a": {"b": 1}}
        out = deep_merge(base, {})
        self.assertEqual(out, base)
        self.assertIsNot(out["a"], base["a"])


class TestDefaultsIsolation(unittest.TestCase):
    """load_config() must never hand out references into DEFAULTS: nested
    sections were aliased, so one caller mutating config['general'] rewrote
    the defaults for every later load in the same process. The dashboard's
    n8n write and apply_bridge_credential_overrides both mutate sections in
    place, and a test setting a dashboard token silently made every later
    app in the same pytest run demand that token."""

    def test_mutating_a_nested_section_does_not_leak_into_a_later_load(self):
        first = load_config()
        first["general"]["dashboard_token"] = "set-by-one-caller"
        first["routes"]["prefer"] = "cloud"
        second = load_config()
        self.assertIsNone(second["general"].get("dashboard_token"))
        self.assertEqual(second["routes"]["prefer"], "local")

    def test_nested_sections_are_not_the_defaults_objects(self):
        cfg = load_config()
        for section in ("general", "routes", "budgets", "n8n"):
            self.assertIsNot(cfg[section], DEFAULTS[section], section)

    def test_two_loads_do_not_share_nested_sections(self):
        a, b = load_config(), load_config()
        self.assertIsNot(a["general"], b["general"])


if __name__ == "__main__":
    unittest.main()
