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
import unittest
from unittest.mock import MagicMock, patch

from inputremapper.windowd.config import WindowRule, WindowMatch, WindowRulesConfig
from inputremapper.windowd.service import WindowDaemonService


class TestWindowDaemonService(unittest.TestCase):
    def setUp(self):
        # Patch the system daemon proxy and rules config to avoid real D-Bus
        self.config_patcher = patch(
            "inputremapper.configs.paths.PathUtils.config_path"
        )
        config_patch = self.config_patcher.start()
        config_patch.return_value = "/tmp/test-input-remapper-windowd-service"

        # Create a real WindowDaemonService with a mocked _connect_system_daemon
        with patch.object(
            WindowDaemonService, "_connect_system_daemon", return_value=MagicMock()
        ):
            self.service = WindowDaemonService(config_dir="/tmp/test-windowd")
            self.service._rules_config = MagicMock(spec=WindowRulesConfig)
            self.service._state = MagicMock()

    def tearDown(self):
        self.config_patcher.stop()

    def test_get_current_window_returns_json_with_none_window(self):
        """When no window is focused, GetCurrentWindow returns empty fields."""
        self.service._state.current_window = None
        raw = self.service.GetCurrentWindow()
        data = json.loads(raw)
        self.assertEqual(data["windowClass"], "")
        self.assertEqual(data["title"], "")
        self.assertEqual(data["pid"], 0)
        self.assertEqual(data["pidCmdline"], "")
        self.assertEqual(data["internalId"], "")

    def test_get_current_window_returns_filled_json(self):
        """When a window is focused, GetCurrentWindow returns its fields."""
        window = MagicMock()
        window.window_class = "firefox"
        window.title = "Mozilla Firefox"
        window.pid = 1234
        window.cmdline_for_matching = "/usr/lib/firefox/firefox"
        window.internal_id = "0xdeadbeef"
        self.service._state.current_window = window

        raw = self.service.GetCurrentWindow()
        data = json.loads(raw)
        self.assertEqual(data["windowClass"], "firefox")
        self.assertEqual(data["title"], "Mozilla Firefox")
        self.assertEqual(data["pid"], 1234)
        self.assertEqual(data["pidCmdline"], "/usr/lib/firefox/firefox")
        self.assertEqual(data["internalId"], "0xdeadbeef")

    def test_evaluate_now_reloads_and_reconciles(self):
        """EvaluateNow should reload config and call state.evaluate_now."""
        self.service.EvaluateNow()
        self.service._rules_config.load.assert_called_once()
        self.service._state.evaluate_now.assert_called_once()

    def test_test_rule_valid_match(self):
        """A valid rule that matches the current window returns matches=True."""
        self.service._state.test_rule.return_value = True
        rule_json = json.dumps({
            "id": "test",
            "device": "Mouse",
            "preset": "Game",
            "enabled": True,
            "priority": 0,
            "match": {"window_class_equals": "game"},
        })
        raw = self.service.TestRule(rule_json)
        data = json.loads(raw)
        self.assertTrue(data["valid"])
        self.assertTrue(data["matches"])
        self.assertIsNone(data["error"])

    def test_test_rule_no_match(self):
        """A valid rule that does NOT match returns matches=False."""
        self.service._state.test_rule.return_value = False
        rule_json = json.dumps({
            "id": "test",
            "device": "Mouse",
            "preset": "Browser",
            "enabled": True,
            "priority": 0,
            "match": {"window_class_equals": "chrome"},
        })
        raw = self.service.TestRule(rule_json)
        data = json.loads(raw)
        self.assertTrue(data["valid"])
        self.assertFalse(data["matches"])
        self.assertIsNone(data["error"])

    def test_test_rule_invalid_json(self):
        """Invalid rule JSON should return valid=False with an error."""
        raw = self.service.TestRule("not json")
        data = json.loads(raw)
        self.assertFalse(data["valid"])
        self.assertFalse(data["matches"])
        self.assertIsNotNone(data["error"])

    def test_test_rule_invalid_regex(self):
        """A rule with an invalid regex should return valid=False."""
        rule_json = json.dumps({
            "id": "bad-re",
            "device": "Mouse",
            "preset": "Game",
            "enabled": True,
            "priority": 0,
            "match": {"window_class_regex": "[invalid"},
        })
        raw = self.service.TestRule(rule_json)
        data = json.loads(raw)
        self.assertFalse(data["valid"])
        self.assertFalse(data["matches"])
        self.assertIsNotNone(data["error"])

    def test_get_status_returns_keys(self):
        """GetStatus should return a JSON object with the expected keys."""
        self.service._state.current_window = MagicMock()
        self.service._state.get_managed_device_presets.return_value = {
            "Mouse": "Game"
        }
        self.service._config_dir = "/some/path"

        raw = self.service.GetStatus()
        data = json.loads(raw)
        self.assertTrue(data["running"])
        self.assertTrue(data["currentWindowPresent"])
        self.assertIn("Mouse", data["managedDevices"])
        self.assertEqual(data["configPath"], "/some/path")

    def test_set_device_automation_forwards_to_state(self):
        self.service.SetDeviceAutomation("Mouse", True)
        self.service._state.set_device_automation.assert_called_once_with("Mouse", True)

    def test_get_device_automation_forwards_to_state(self):
        self.service._state.get_device_automation.return_value = False
        self.assertFalse(self.service.GetDeviceAutomation("Mouse"))
        self.service._state.get_device_automation.assert_called_once_with("Mouse")

    def test_sync_automation_from_config_enables_automatic_devices(self):
        self.service._state.reset_mock()
        self.service._global_config._config["window_rules_automation"] = {
            "Mouse": "automatic",
            "Keyboard": "manual",
        }
        self.service._sync_automation_from_config()
        self.service._state.set_device_automation.assert_called_once_with("Mouse", True)


if __name__ == "__main__":
    unittest.main()
