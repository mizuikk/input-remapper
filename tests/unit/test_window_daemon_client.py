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

from dasbus.error import DBusError


class TestWindowDaemonClient(unittest.TestCase):
    def setUp(self):
        self.proxy_patcher = patch(
            "inputremapper.windowd.client.WINDOW_DAEMON"
        )
        self.daemon_id = self.proxy_patcher.start()
        self.mock_proxy = MagicMock()
        self.daemon_id.get_proxy.return_value = self.mock_proxy

    def tearDown(self):
        self.proxy_patcher.stop()

    def _make_client(self, connected=True):
        """Helper to create a WindowDaemonClient with controlled connectivity."""
        with patch("inputremapper.windowd.client.logger"):
            from inputremapper.windowd.client import WindowDaemonClient

            client = WindowDaemonClient.__new__(WindowDaemonClient)
            client._proxy = self.mock_proxy
            client.connected = connected
            return client

    def test_connected_when_introspect_succeeds(self):
        """If Introspect succeeds, connected should be True."""
        from inputremapper.windowd.client import WindowDaemonClient

        client = WindowDaemonClient()
        self.assertTrue(client.connected)

    def test_not_connected_when_introspect_fails(self):
        """If Introspect raises DBusError, connected should be False."""
        self.mock_proxy.Introspect.side_effect = DBusError("not reachable")
        from inputremapper.windowd.client import WindowDaemonClient

        client = WindowDaemonClient()
        self.assertFalse(client.connected)

    def test_get_current_window_returns_data(self):
        """get_current_window should return parsed JSON when connected."""
        client = self._make_client(connected=True)
        self.mock_proxy.GetCurrentWindow.return_value = json.dumps({
            "windowClass": "firefox",
            "title": "Mozilla",
            "pid": 1234,
            "pidCmdline": "/usr/bin/firefox",
            "internalId": "0x1",
        })
        data = client.get_current_window()
        self.assertEqual(data["windowClass"], "firefox")
        self.assertEqual(data["title"], "Mozilla")
        self.assertEqual(data["pid"], 1234)

    def test_get_current_window_returns_none_when_disconnected(self):
        """get_current_window should return None when not connected."""
        client = self._make_client(connected=False)
        self.assertIsNone(client.get_current_window())

    def test_evaluate_now_returns_true_when_connected(self):
        """evaluate_now should return True on success."""
        client = self._make_client(connected=True)
        self.assertTrue(client.evaluate_now())
        self.mock_proxy.EvaluateNow.assert_called_once()

    def test_evaluate_now_returns_false_when_disconnected(self):
        """evaluate_now should return False when not connected."""
        client = self._make_client(connected=False)
        self.assertFalse(client.evaluate_now())

    def test_test_rule_returns_result(self):
        """test_rule should return parsed result dict."""
        client = self._make_client(connected=True)
        self.mock_proxy.TestRule.return_value = json.dumps({
            "valid": True,
            "matches": True,
            "error": None,
        })
        result = client.test_rule('{"id":"r1"}')
        self.assertTrue(result["valid"])
        self.assertTrue(result["matches"])

    def test_test_rule_returns_none_when_disconnected(self):
        """test_rule should return None when not connected."""
        client = self._make_client(connected=False)
        self.assertIsNone(client.test_rule("{}"))

    def test_get_status_returns_data(self):
        """get_status should return parsed status dict."""
        client = self._make_client(connected=True)
        self.mock_proxy.GetStatus.return_value = json.dumps({
            "running": True,
            "currentWindowPresent": True,
            "managedDevices": ["Mouse"],
            "configPath": "/tmp",
        })
        status = client.get_status()
        self.assertTrue(status["running"])
        self.assertIn("Mouse", status["managedDevices"])

    def test_get_status_returns_none_when_disconnected(self):
        """get_status should return None when not connected."""
        client = self._make_client(connected=False)
        self.assertIsNone(client.get_status())


if __name__ == "__main__":
    unittest.main()
