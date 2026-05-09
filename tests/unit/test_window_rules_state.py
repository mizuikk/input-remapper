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

import json
import os
import unittest
from unittest.mock import patch

from inputremapper.configs.paths import PathUtils
from inputremapper.windowd.config import WindowMatch, WindowRule, WindowRulesConfig
from inputremapper.windowd.matcher import WindowInfo
from inputremapper.windowd.state import WindowDaemonState
from tests.lib.tmp import tmp


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


def _make_window(window_class="class1", title="Title", pid=0, cmdline=""):
    return WindowInfo(
        window_class=window_class,
        title=title,
        pid=pid,
        pid_cmdline=cmdline,
    )


class TestWindowDaemonState(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("inputremapper.configs.paths.PathUtils.config_path"),
        ]
        self.config_dir = os.path.join(tmp, ".config", "input-remapper-2")
        self.config_path_patch = self.patches[0]
        self.config_path_patch.start()
        PathUtils.config_path.return_value = self.config_dir  # type: ignore

        os.makedirs(self.config_dir, exist_ok=True)
        self.rules_config = WindowRulesConfig(self.config_dir)
        self.start_calls = []
        self.stop_calls = []
        self.autoload_calls = []

        def start_injecting(group_key, preset):
            self.start_calls.append((group_key, preset))
            return True

        def stop_injecting(group_key):
            self.stop_calls.append(group_key)

        def autoload_single(group_key):
            self.autoload_calls.append(group_key)

        self.state = WindowDaemonState(
            rules_config=self.rules_config,
            start_injecting_fn=start_injecting,
            stop_injecting_fn=stop_injecting,
            autoload_single_fn=autoload_single,
        )

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _write_rules(self, rules_data):
        path = os.path.join(self.config_dir, self.rules_config.FILE_NAME)
        with open(path, "w") as f:
            json.dump(rules_data, f, indent=4)

    def _process_debounce(self):
        """Simulate the debounce timer firing by calling _on_debounced directly."""
        self.state._on_debounced()

    def test_initial_state_empty(self):
        """Fresh state should have no applied presets."""
        self.assertEqual(self.state.get_managed_device_presets(), {})
        self.assertIsNone(self.state.current_window)

    def test_matched_rule_starts_injection(self):
        """A matched rule should trigger start_injecting."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        window = _make_window(window_class="game")
        self.state.on_window_changed(window)
        self._process_debounce()

        self.assertEqual(len(self.start_calls), 1)
        self.assertEqual(self.start_calls[0], ("Mouse", "Game"))
        self.assertIn("Mouse", self.state.get_managed_device_presets())

    def test_no_match_does_not_start(self):
        """If no rule matches, nothing should be started."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "other"},
            }
        ])
        self.rules_config.load()

        window = _make_window(window_class="browser")
        self.state.on_window_changed(window)
        self._process_debounce()

        self.assertEqual(len(self.start_calls), 0)
        self.assertEqual(self.state.get_managed_device_presets(), {})

    def test_dedup_same_preset(self):
        """Switching to a window that matches the same (device, preset) should
        not call start_injecting again."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        window = _make_window(window_class="game")
        self.state.on_window_changed(window)
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)

        # Same window again
        self.state.on_window_changed(window)
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1, "Should not re-apply same preset")

    def test_different_window_switches_preset(self):
        """When a new window triggers a different rule for the same device,
        the old preset should be stopped and the new one started."""
        self._write_rules([
            {
                "id": "game",
                "device": "Mouse",
                "preset": "Game",
                "priority": 100,
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "browser",
                "device": "Mouse",
                "preset": "Browser",
                "priority": 50,
                "match": {"window_class_equals": "browser"},
            },
        ])
        self.rules_config.load()

        # Start with game
        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)
        self.assertEqual(self.start_calls[0], ("Mouse", "Game"))

        # Switch to browser
        self.state.on_window_changed(_make_window(window_class="browser"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 2)
        self.assertEqual(self.start_calls[1], ("Mouse", "Browser"))
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.stop_calls[0], "Mouse")

    def test_none_window_reverts_managed_devices(self):
        """A None window (desktop/lockscreen) should revert all managed devices."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)
        self.assertIn("Mouse", self.state.get_managed_device_presets())

        # Desktop / lockscreen — managed device should revert
        self.state.on_window_changed(None)
        self._process_debounce()
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(len(self.autoload_calls), 1)
        self.assertEqual(self.state.get_managed_device_presets(), {})

    def test_reset_clears_state(self):
        """reset() should stop all injections and clear state."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)

        self.state.reset()
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.state.get_managed_device_presets(), {})
        self.assertIsNone(self.state.current_window)

    def test_revert_to_default(self):
        """When no rule matches for a managed device, it should revert."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)

        # Now switch to non-matching window
        self.state.on_window_changed(_make_window(window_class="browser"))
        self._process_debounce()
        # Should have stopped and called autoload_single
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(len(self.autoload_calls), 1)
        self.assertEqual(self.autoload_calls[0], "Mouse")
        self.assertNotIn("Mouse", self.state.get_managed_device_presets())

    def test_priority_respected(self):
        """Higher priority rules should win."""
        self._write_rules([
            {
                "id": "low",
                "device": "Mouse",
                "preset": "Low",
                "priority": 10,
                "match": {"window_class_equals": "target"},
            },
            {
                "id": "high",
                "device": "Mouse",
                "preset": "High",
                "priority": 100,
                "match": {"window_class_equals": "target"},
            },
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="target"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)
        self.assertEqual(self.start_calls[0], ("Mouse", "High"))

    # ── Multi-device tests ──────────────────────────────────────────────

    def test_two_devices_both_started(self):
        """A single window matching rules for two devices should start both."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "r2",
                "device": "Keyboard",
                "preset": "GameKeys",
                "match": {"window_class_equals": "game"},
            },
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()

        self.assertIn(("Mouse", "Game"), self.start_calls)
        self.assertIn(("Keyboard", "GameKeys"), self.start_calls)
        self.assertEqual(len(self.start_calls), 2)

    def test_one_device_falls_off_while_other_stays(self):
        """Bug #1 repro: from window matching A+B to window matching only A.
        B should revert while A stays applied."""
        self._write_rules([
            {
                "id": "mouse-game",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "kb-game",
                "device": "Keyboard",
                "preset": "GameKeys",
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "mouse-browser",
                "device": "Mouse",
                "preset": "Browser",
                "match": {"window_class_equals": "browser"},
            },
        ])
        self.rules_config.load()

        # Phase 1: game window should start both devices
        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 2)
        self.assertEqual(len(self.stop_calls), 0)

        # Phase 2: switch to browser window — Mouse gets Browser, Keyboard reverts
        self.state.on_window_changed(_make_window(window_class="browser"))
        self._process_debounce()

        # Mouse should have switched to "Browser"
        self.assertEqual(len(self.start_calls), 3)
        self.assertEqual(self.start_calls[2], ("Mouse", "Browser"))
        # Keyboard should have been stopped and reverted
        self.assertIn("Keyboard", self.stop_calls)
        self.assertIn("Keyboard", self.autoload_calls)
        self.assertGreaterEqual(len(self.stop_calls), 1)

        # Keyboard is no longer in managed presets
        presets = self.state.get_managed_device_presets()
        self.assertIn("Mouse", presets)
        self.assertEqual(presets["Mouse"], "Browser")
        self.assertNotIn("Keyboard", presets)

    # ── evaluate_now and test_rule ────────────────────────────────────

    def test_evaluate_now_performs_reconcile(self):
        """evaluate_now should perform a full reconcile immediately."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        # Call evaluate_now directly instead of relying on the debounce timer
        self.state.evaluate_now()

        self.assertEqual(len(self.start_calls), 1)
        self.assertEqual(self.start_calls[0], ("Mouse", "Game"))

    def test_test_rule_matches(self):
        """test_rule should return True when the rule matches the current window."""
        self.state.current_window = _make_window(
            window_class="firefox", title="Mozilla Firefox"
        )
        rule = _make_rule(
            rule_id="test-match",
            window_class_equals="firefox",
        )
        self.assertTrue(self.state.test_rule(rule))

    def test_test_rule_no_match(self):
        """test_rule should return False when the rule does not match."""
        self.state.current_window = _make_window(
            window_class="firefox", title="Mozilla Firefox"
        )
        rule = _make_rule(
            rule_id="test-no-match",
            window_class_equals="chrome",
        )
        self.assertFalse(self.state.test_rule(rule))

    def test_test_rule_none_window(self):
        """test_rule should return False when no window is focused."""
        self.state.current_window = None
        rule = _make_rule(rule_id="test-none", window_class_equals="anything")
        self.assertFalse(self.state.test_rule(rule))

    def test_neither_device_matches_revert_both(self):
        """When neither device matches globally, both managed ones revert."""
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "r2",
                "device": "Keyboard",
                "preset": "GameKeys",
                "match": {"window_class_equals": "game"},
            },
        ])
        self.rules_config.load()

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 2)

        # Switch to a non-matching window — both should revert
        self.state.on_window_changed(_make_window(window_class="other"))
        self._process_debounce()

        self.assertEqual(len(self.stop_calls), 2)
        self.assertEqual(len(self.autoload_calls), 2)
        self.assertIn("Mouse", self.autoload_calls)
        self.assertIn("Keyboard", self.autoload_calls)
        self.assertEqual(self.state.get_managed_device_presets(), {})


if __name__ == "__main__":
    unittest.main()
