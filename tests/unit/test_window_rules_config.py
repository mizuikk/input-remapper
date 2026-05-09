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
from inputremapper.windowd.config import (
    WindowMatch,
    WindowRule,
    WindowRulesConfig,
)
from tests.lib.cleanup import cleanup
from tests.lib.tmp import tmp


class TestWindowMatch(unittest.TestCase):
    def test_validates_valid_regex(self):
        """Regex fields should accept valid patterns."""
        match = WindowMatch(window_class_regex="[Bb]lack.*Desert")
        self.assertEqual(match.window_class_regex, "[Bb]lack.*Desert")

    def test_rejects_invalid_regex(self):
        """Regex fields should reject invalid patterns."""
        with self.assertRaises(Exception):
            WindowMatch(window_class_regex=r"[invalid")

    def test_all_fields_optional(self):
        """All match fields should default to None."""
        match = WindowMatch()
        self.assertIsNone(match.window_class_equals)
        self.assertIsNone(match.window_class_regex)
        self.assertIsNone(match.title_equals)
        self.assertIsNone(match.title_starts_with)
        self.assertIsNone(match.title_regex)
        self.assertIsNone(match.pid_cmdline_contains)
        self.assertIsNone(match.pid_cmdline_regex)

    def test_accepts_all_fields_populated(self):
        """All match fields can be populated simultaneously."""
        match = WindowMatch(
            window_class_equals="code",
            window_class_regex="code.*",
            title_equals="Visual Studio Code",
            title_starts_with="Visual",
            title_regex="Visual.*",
            pid_cmdline_contains="code",
            pid_cmdline_regex=".*code.*",
        )
        self.assertEqual(match.window_class_equals, "code")
        self.assertEqual(match.window_class_regex, "code.*")


class TestWindowRule(unittest.TestCase):
    def test_basic_rule(self):
        """A minimal rule with a default (empty) match."""
        rule = WindowRule(
            id="test-1",
            device="Mouse",
            preset="Game",
            match=WindowMatch(),
        )
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.priority, 0)

    def test_rule_with_match(self):
        """A rule with match conditions."""
        rule = WindowRule(
            id="test-2",
            device="Keyboard",
            preset="Coding",
            priority=10,
            enabled=False,
            match=WindowMatch(
                window_class_equals="code",
                title_starts_with="Visual",
            ),
        )
        self.assertFalse(rule.enabled)
        self.assertEqual(rule.priority, 10)
        self.assertEqual(rule.match.window_class_equals, "code")

    def test_serialize_roundtrip(self):
        """WindowRule.dict() should produce valid input for WindowRule()."""
        rule = WindowRule(
            id="roundtrip",
            device="Dev",
            preset="Pre",
            match=WindowMatch(window_class_equals="foo"),
        )
        data = rule.dict()
        restored = WindowRule(**data)
        self.assertEqual(rule.id, restored.id)
        self.assertEqual(rule.device, restored.device)
        self.assertEqual(rule.preset, restored.preset)
        self.assertEqual(
            rule.match.window_class_equals,
            restored.match.window_class_equals,
        )


class TestWindowRulesConfig(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("inputremapper.configs.paths.PathUtils.config_path"),
        ]
        self.config_dir = os.path.join(tmp, ".config", "input-remapper-2")
        self.config_path_patch = self.patches[0]
        self.config_path_patch.start()
        PathUtils.config_path.return_value = self.config_dir  # type: ignore

        os.makedirs(self.config_dir, exist_ok=True)
        self.config = WindowRulesConfig(self.config_dir)

    def tearDown(self):
        config_path = os.path.join(self.config_dir, self.config.FILE_NAME)
        if os.path.exists(config_path):
            os.remove(config_path)
        for p in self.patches:
            p.stop()

    def _write_rules(self, data):
        path = os.path.join(self.config_dir, self.config.FILE_NAME)
        with open(path, "w") as f:
            json.dump(data, f, indent=4)

    def test_load_nonexistent_returns_empty(self):
        """Loading a non-existent file returns an empty list."""
        rules = self.config.load()
        self.assertEqual(rules, [])

    def test_load_valid_json_array(self):
        """Loading a JSON array of rules."""
        self._write_rules([
            {
                "id": "rule-1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        rules = self.config.load()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "rule-1")

    def test_load_valid_json_object_with_rules_key(self):
        """Loading a JSON object with a rules key."""
        self._write_rules({
            "rules": [
                {
                    "id": "rule-1",
                    "device": "Mouse",
                    "preset": "Game",
                    "match": {"window_class_equals": "game"},
                }
            ]
        })
        rules = self.config.load()
        self.assertEqual(len(rules), 1)

    def test_skips_invalid_rules(self):
        """Rules with validation errors should be skipped."""
        self._write_rules([
            {
                "id": "valid",
                "device": "Foo",
                "preset": "Bar",
                "match": {"window_class_equals": "baz"},
            },
            {
                "id": "invalid-regex",
                "device": "Foo",
                "preset": "Bar",
                "match": {"window_class_regex": r"[invalid"},
            },
            {
                "id": "incomplete",
            },
        ])
        rules = self.config.load()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "valid")

    def test_set_and_get_rules(self):
        """set_rules should persist and get_rules should return them."""
        rule = WindowRule(
            id="saved",
            device="Dev",
            preset="Pre",
            match=WindowMatch(title_equals="test"),
        )
        self.config.set_rules([rule])
        loaded = self.config.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "saved")

    def test_get_rules_without_load(self):
        """get_rules returns empty list if load was never called."""
        self.assertEqual(self.config.get_rules(), [])


if __name__ == "__main__":
    unittest.main()
