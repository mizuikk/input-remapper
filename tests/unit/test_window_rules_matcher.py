#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# input-remapper - GUI for device specific keyboard mappings
# Copyright (C) 2025 sezanzeb <b8x45ygc9@mozmail.com>
#
# This file is part of input-remapper.
#
# input-remapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# input-remapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with input-remapper.  If not, see <https://www.gnu.org/licenses/>.

import unittest

from inputremapper.windowd.config import WindowMatch, WindowRule
from inputremapper.windowd.matcher import (
    WindowInfo,
    find_matching_rules_by_device,
    match_rule,
)


def _make_rule(
    rule_id="test",
    device="Mouse",
    preset="Preset",
    priority=0,
    enabled=True,
    **match_kwargs,
):
    return WindowRule(
        id=rule_id,
        device=device,
        preset=preset,
        priority=priority,
        enabled=enabled,
        match=WindowMatch(**match_kwargs),
    )


def _make_window(
    window_class="class1",
    title="Title",
    pid=1234,
    cmdline="",
):
    return WindowInfo(
        window_class=window_class,
        title=title,
        pid=pid,
        pid_cmdline=cmdline,
    )


class TestMatchRule(unittest.TestCase):
    def test_window_class_equals_match(self):
        rule = _make_rule(window_class_equals="class1")
        window = _make_window(window_class="class1")
        self.assertTrue(match_rule(rule, window))

    def test_window_class_equals_no_match(self):
        rule = _make_rule(window_class_equals="class1")
        window = _make_window(window_class="other")
        self.assertFalse(match_rule(rule, window))

    def test_window_class_regex_match(self):
        rule = _make_rule(window_class_regex=r"class\d+")
        window = _make_window(window_class="class42")
        self.assertTrue(match_rule(rule, window))

    def test_window_class_regex_no_match(self):
        rule = _make_rule(window_class_regex=r"game.*")
        window = _make_window(window_class="browser")
        self.assertFalse(match_rule(rule, window))

    def test_title_equals_match(self):
        rule = _make_rule(title_equals="Visual Studio Code")
        window = _make_window(title="Visual Studio Code")
        self.assertTrue(match_rule(rule, window))

    def test_title_equals_no_match(self):
        rule = _make_rule(title_equals="Exact Match")
        window = _make_window(title="Different Title")
        self.assertFalse(match_rule(rule, window))

    def test_title_starts_with_match(self):
        rule = _make_rule(title_starts_with="Black")
        window = _make_window(title="Black Desert")
        self.assertTrue(match_rule(rule, window))

    def test_title_starts_with_no_match(self):
        rule = _make_rule(title_starts_with="Black")
        window = _make_window(title="Not Black")
        self.assertFalse(match_rule(rule, window))

    def test_title_regex_match(self):
        rule = _make_rule(title_regex=r"Black\s+Desert")
        window = _make_window(title="Black Desert")
        self.assertTrue(match_rule(rule, window))

    def test_pid_cmdline_contains_match(self):
        rule = _make_rule(pid_cmdline_contains="steam")
        window = _make_window(pid=0, cmdline="/usr/bin/steam-runtime")
        self.assertTrue(match_rule(rule, window))

    def test_pid_cmdline_contains_no_match(self):
        rule = _make_rule(pid_cmdline_contains="steam")
        window = _make_window(pid=0, cmdline="/usr/bin/firefox")
        self.assertFalse(match_rule(rule, window))

    def test_pid_cmdline_regex_match(self):
        rule = _make_rule(pid_cmdline_regex=r".*steam.*")
        window = _make_window(pid=0, cmdline="/usr/bin/steam")
        self.assertTrue(match_rule(rule, window))

    def test_all_conditions_must_match(self):
        """All non-None match fields are ANDed."""
        rule = _make_rule(
            window_class_equals="code",
            title_starts_with="Visual",
        )
        window = _make_window(window_class="code", title="Visual Studio Code")
        self.assertTrue(match_rule(rule, window))

    def test_all_conditions_fail_if_one_mismatches(self):
        """AND semantics: one mismatch should fail the whole rule."""
        rule = _make_rule(
            window_class_equals="code",
            title_equals="Visual Studio Code",
        )
        window = _make_window(window_class="code", title="Different Title")
        self.assertFalse(match_rule(rule, window))

    def test_empty_match_always_matches(self):
        """A rule with all-None match fields matches anything."""
        rule = _make_rule()
        window = _make_window()
        self.assertTrue(match_rule(rule, window))

    def test_match_with_none_window_class(self):
        """match_rule should handle empty window_class."""
        rule = _make_rule(window_class_equals="nothing")
        window = _make_window(window_class="")
        self.assertFalse(match_rule(rule, window))

    def test_default_cmdline_from_pid_cached(self):
        """When pid is 0, pid_cmdline is used directly."""
        window = _make_window(pid=0, cmdline="/usr/bin/test --flag")
        self.assertIn("test", window.cmdline_for_matching)


class TestFindMatchingRulesByDevice(unittest.TestCase):
    def test_single_device_matches(self):
        """One device matched should return one entry."""
        rules = [
            _make_rule(rule_id="r1", device="Mouse", window_class_equals="game"),
        ]
        window = _make_window(window_class="game")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["Mouse"].id, "r1")

    def test_two_devices_both_match(self):
        """Same window can match rules for two different devices."""
        rules = [
            _make_rule(rule_id="r1", device="Mouse", window_class_equals="game"),
            _make_rule(rule_id="r2", device="Keyboard", window_class_equals="game"),
        ]
        window = _make_window(window_class="game")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["Mouse"].id, "r1")
        self.assertEqual(result["Keyboard"].id, "r2")

    def test_two_devices_one_matches(self):
        """Only the device whose rule matches should be returned."""
        rules = [
            _make_rule(rule_id="r1", device="Mouse", window_class_equals="game"),
            _make_rule(rule_id="r2", device="Keyboard", window_class_equals="browser"),
        ]
        window = _make_window(window_class="game")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["Mouse"].id, "r1")
        self.assertNotIn("Keyboard", result)

    def test_same_device_returns_highest_priority(self):
        """If two rules target the same device, the higher priority wins."""
        rules = [
            _make_rule(
                rule_id="low", device="Mouse", priority=10,
                window_class_equals="target",
            ),
            _make_rule(
                rule_id="high", device="Mouse", priority=100,
                window_class_equals="target",
            ),
        ]
        window = _make_window(window_class="target")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["Mouse"].id, "high")

    def test_same_device_same_priority_preserves_order(self):
        """Ties should be broken by list order (first in config wins)."""
        rules = [
            _make_rule(
                rule_id="first", device="Mouse", priority=0,
                window_class_equals="target",
            ),
            _make_rule(
                rule_id="second", device="Mouse", priority=0,
                window_class_equals="target",
            ),
        ]
        window = _make_window(window_class="target")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["Mouse"].id, "first")

    def test_skips_disabled_rules(self):
        """Disabled rules should not be considered at all."""
        rules = [
            _make_rule(
                rule_id="disabled", device="Mouse", enabled=False,
                window_class_equals="target",
            ),
            _make_rule(
                rule_id="enabled", device="Keyboard", enabled=True,
                window_class_equals="target",
            ),
        ]
        window = _make_window(window_class="target")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["Keyboard"].id, "enabled")

    def test_returns_empty_when_no_match(self):
        """No matching rule returns an empty dict."""
        rules = [
            _make_rule(rule_id="r1", window_class_equals="game"),
        ]
        window = _make_window(window_class="browser")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(result, {})

    def test_returns_empty_empty_rules(self):
        """Empty rule list returns an empty dict."""
        result = find_matching_rules_by_device([], _make_window())
        self.assertEqual(result, {})

    def test_lower_priority_for_other_device_not_affected(self):
        """Per-device winner is independent; priority is compared within device."""
        rules = [
            _make_rule(
                rule_id="high-mouse", device="Mouse", priority=200,
                window_class_equals="target",
            ),
            _make_rule(
                rule_id="low-mouse", device="Mouse", priority=10,
                title_equals="irrelevant",
            ),
            _make_rule(
                rule_id="only-keyboard", device="Keyboard", priority=0,
                window_class_equals="target",
            ),
        ]
        window = _make_window(window_class="target", title="irrelevant")
        result = find_matching_rules_by_device(rules, window)
        self.assertEqual(len(result), 2)
        # Mouse should pick the higher-priority rule (high-mouse)
        self.assertEqual(result["Mouse"].id, "high-mouse")
        # Keyboard should also match
        self.assertEqual(result["Keyboard"].id, "only-keyboard")


if __name__ == "__main__":
    unittest.main()
