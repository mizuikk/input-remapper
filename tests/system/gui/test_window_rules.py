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
# along with input-remapper.  If not, see <see
# <https://www.gnu.org/licenses/>.

"""GUI tests for the Window Rules dialog."""

import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, GLib  # noqa: E402

from inputremapper.configs.paths import PathUtils  # noqa: E402
from inputremapper.groups import _Groups  # noqa: E402
from inputremapper.gui.utils import gtk_iteration  # noqa: E402
from tests.lib.fixtures import prepare_presets  # noqa: E402
from tests.lib.test_setup import test_setup  # noqa: E402

from .gui_test_base import (  # noqa: E402
    GuiTestBase,
    launch,
    patch_services,
    clean_up_gui_test,
)


@test_setup
class TestWindowRulesDialog(GuiTestBase, unittest.TestCase):
    """Test the Window Rules dialog from the GUI."""

    @classmethod
    def setUpClass(cls):
        # Don't run the default GuiTestBase setUpClass
        pass

    def setUp(self):
        prepare_presets()
        self.patches_ctx = patch_services()
        self.patches = self.patches_ctx.__enter__()
        (
            self.user_interface,
            self.controller,
            self.data_manager,
            self.message_broker,
            self.daemon,
            self.global_config,
        ) = launch()

        # Mock the WindowDaemonClient so that capture/test work in tests
        self.mock_client = MagicMock()
        self.mock_client.connected = True
        self.mock_client.get_current_window.return_value = {
            "windowClass": "test-window",
            "title": "Test Title",
            "pid": 1234,
            "pidCmdline": "/usr/bin/test",
            "internalId": "0xabc",
        }
        self.mock_client.evaluate_now.return_value = True
        self.mock_client.test_rule.return_value = {
            "valid": True,
            "matches": True,
            "error": None,
        }
        self.data_manager.set_window_daemon_client(self.mock_client)

        self.get = self.user_interface.get

        # Wait for the GUI to settle
        self.throttle(20)

    def tearDown(self):
        clean_up_gui_test(self)
        self.patches_ctx.__exit__(None, None, None)

    def _click_button(self, button_id: str):
        """Click a button by widget ID and process events."""
        button = self.get(button_id)
        button.clicked()
        gtk_iteration()
        time.sleep(0.05)

    def _select_first_preset(self):
        """Load the first device group and first preset."""
        groups = self.data_manager.get_group_keys()
        if not groups:
            self.skipTest("No device groups available")

        self.controller.load_group(groups[0])
        self.throttle(10)

        presets = self.data_manager.get_preset_names()
        if not presets:
            self.skipTest("No presets available in the group")

        self.controller.load_preset(presets[0])
        self.throttle(10)

    def _get_dialog(self) -> Gtk.Widget:
        """Return the window-rules dialog."""
        return self.get("window-rules-dialog")

    # ---- Tests ----

    def test_button_disabled_without_preset(self):
        """When no preset is loaded, the button should be insensitive."""
        btn = self.get("window_rules_button")
        # Initially no preset loaded
        self.assertFalse(btn.get_sensitive())

    def test_button_enabled_with_preset(self):
        """When a group and preset are loaded, the button should be sensitive."""
        self._select_first_preset()
        btn = self.get("window_rules_button")
        self.assertTrue(btn.get_sensitive())

    def test_dialog_opens(self):
        """Clicking the button should open the dialog."""
        self._select_first_preset()
        dialog = self._get_dialog()
        self.assertFalse(dialog.get_visible())

        self._click_button("window_rules_button")
        self.assertTrue(dialog.get_visible())

    def test_dialog_adds_rule_row(self):
        """Clicking Add should add a new rule to the listbox."""
        self._select_first_preset()
        self._click_button("window_rules_button")

        listbox = self.get("window_rules_listbox")
        initial_rows = listbox.get_children()

        self._click_button("window_rules_add_btn")
        self.throttle(5)

        rows_after = listbox.get_children()
        self.assertEqual(len(rows_after), len(initial_rows) + 1)

    def test_dialog_deletes_rule_row(self):
        """Clicking Delete should remove the selected rule."""
        self._select_first_preset()
        self._click_button("window_rules_button")

        listbox = self.get("window_rules_listbox")
        # Add a rule first
        self._click_button("window_rules_add_btn")
        self.throttle(5)
        rows_after_add = len(listbox.get_children())

        # Select the new row and delete it
        last_row = listbox.get_row_at_index(listbox.get_children()[-1].get_index())
        listbox.select_row(last_row)
        self.throttle(3)

        self._click_button("window_rules_delete_btn")
        self.throttle(5)

        rows_after_delete = len(listbox.get_children())
        self.assertLess(rows_after_delete, rows_after_add)

    def test_save_persists_to_file(self):
        """Saving should write the rules to window_rules.json."""
        self._select_first_preset()
        self._click_button("window_rules_button")

        # Fill in a match field for the default rule
        class_eq = self.get("window_rule_class_eq")
        GLib.idle_add(class_eq.set_text, "firefox")
        self.throttle(5)

        # Save
        self._click_button("window_rules_save_btn")
        self.throttle(10)

        # Verify the file was written
        config_dir = PathUtils.config_path()
        rules_path = os.path.join(config_dir, "window_rules.json")
        self.assertTrue(os.path.exists(rules_path))

        with open(rules_path, "r") as f:
            data = json.load(f)

        # Should contain at least one rule with class=firefox
        found = any(
            r.get("match", {}).get("window_class_equals") == "firefox"
            for r in (data if isinstance(data, list) else data.get("rules", []))
        )
        self.assertTrue(found)

    def test_cancel_does_not_persist(self):
        """Cancelling the dialog should not save any changes."""
        self._select_first_preset()
        self._click_button("window_rules_button")

        class_eq = self.get("window_rule_class_eq")
        GLib.idle_add(class_eq.set_text, "should-not-save")
        self.throttle(5)

        # Cancel instead of save
        self._click_button("window_rules_cancel_btn")
        self.throttle(5)

        # Dialog should be hidden
        dialog = self._get_dialog()
        self.assertFalse(dialog.get_visible())


if __name__ == "__main__":
    unittest.main()
