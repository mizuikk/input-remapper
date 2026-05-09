#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# input-remapper - GUI for device specific keyboard mappings
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

from __future__ import annotations

import unittest

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import GObject, Gtk, GtkSource  # noqa: E402

GObject.type_register(GtkSource.View)

from inputremapper.gui.components.window_rules import WindowRules  # noqa: E402
from inputremapper.windowd.config import WindowMatch, WindowRule  # noqa: E402


class _DataManager:
    def get_window_rules_for_device_preset(self, device, preset):
        return [
            WindowRule(
                id="rule-a",
                device=device,
                preset=preset,
                match=WindowMatch(window_class_equals="original"),
            )
        ]

    def create_default_window_rule(self, device, preset):
        return WindowRule(
            id="rule-new",
            device=device,
            preset=preset,
            match=WindowMatch(),
        )


class _Controller:
    def __init__(self):
        self.data_manager = _DataManager()

    def capture_current_window(self):
        return None

    def test_window_rule_match(self, rule):
        return None

    def save_window_rules(self, rules):
        raise AssertionError("save should not be called in this test")


class TestWindowRulesComponent(unittest.TestCase):
    def setUp(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file("data/input-remapper.glade")
        self.component = WindowRules(
            None,
            _Controller(),
            dialog=self.builder.get_object("window-rules-dialog"),
            title=self.builder.get_object("window_rules_title"),
            listbox=self.builder.get_object("window_rules_listbox"),
            detail_grid=self.builder.get_object("window_rules_detail_grid"),
            enabled_switch=self.builder.get_object("window_rule_enabled"),
            priority_spin=self.builder.get_object("window_rule_priority"),
            class_eq=self.builder.get_object("window_rule_class_eq"),
            class_re=self.builder.get_object("window_rule_class_re"),
            title_eq=self.builder.get_object("window_rule_title_eq"),
            title_sw=self.builder.get_object("window_rule_title_sw"),
            title_re=self.builder.get_object("window_rule_title_re"),
            cmdline_contains=self.builder.get_object(
                "window_rule_cmdline_contains"
            ),
            cmdline_re=self.builder.get_object("window_rule_cmdline_re"),
            add_btn=self.builder.get_object("window_rules_add_btn"),
            duplicate_btn=self.builder.get_object("window_rules_duplicate_btn"),
            delete_btn=self.builder.get_object("window_rules_delete_btn"),
            capture_btn=self.builder.get_object("window_rules_capture_btn"),
            test_btn=self.builder.get_object("window_rules_test_btn"),
            cancel_btn=self.builder.get_object("window_rules_cancel_btn"),
            save_btn=self.builder.get_object("window_rules_save_btn"),
        )
        self.component.open("Mouse", "Game")

    def test_add_keeps_selected_row_edits(self):
        class_eq = self.builder.get_object("window_rule_class_eq")
        class_eq.set_text("edited-before-add")

        self.component._on_add()

        self.assertEqual(
            self.component._rules[0].match.window_class_equals,
            "edited-before-add",
        )


if __name__ == "__main__":
    unittest.main()
