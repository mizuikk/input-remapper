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
from inputremapper.profiles.config import (
    ProfilesConfig,
    ProfilesDocument,
    ProfileModel,
    AppRuleModel,
)
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
        # ProfilesConfig drives the new state machine. For these tests we keep it
        # in-memory and patch load() to return a document derived from the legacy
        # window_rules.json file.
        #
        # NOTE: The legacy model had per-device independent switching. The new
        # model picks exactly one Profile at a time. For unit tests in this
        # migration window we interpret legacy rules as "profile definitions":
        # - rules that share the same match (+priority) are merged into one Profile
        #   so that one active Profile can still start multiple devices.
        self.profiles_config = ProfilesConfig(self.config_dir)

        desktop_defaults: dict[str, str] = {}

        def _doc_from_legacy_rules() -> ProfilesDocument:
            # Load the latest rules file and convert to a minimal ProfilesDocument:
            # - DESKTOP profile is blank
            # - Rules with the same match (+priority) are merged into one Profile
            #   so that a single active Profile may include multiple devices.
            rules = self.rules_config.load()
            profiles = {"DESKTOP": ProfileModel(device_presets={})}
            app_rules: list[AppRuleModel] = []

            def _match_key(m: WindowMatch) -> str:
                # stable grouping key: same semantics as JSON representation
                return json.dumps(m.dict(), sort_keys=True)

            by_key: dict[tuple[int, str], list[WindowRule]] = {}
            for rule in rules:
                key = (int(getattr(rule, "priority", 0)), _match_key(rule.match))
                by_key.setdefault(key, []).append(rule)

            # Keep deterministic ordering: higher priority first, then match key.
            for (priority, match_json), grouped in sorted(
                by_key.items(), key=lambda t: (-t[0][0], t[0][1])
            ):
                # Construct a synthetic profile name based on the first rule id.
                # Within that profile, include all devices from the group.
                profile_name = str(grouped[0].id)
                profiles.setdefault(profile_name, ProfileModel(device_presets={}))
                for r in grouped:
                    profiles[profile_name].device_presets[str(r.device)] = str(r.preset)

                app_rules.append(
                    AppRuleModel(
                        id=str(grouped[0].id),
                        enabled=all(bool(getattr(r, "enabled", True)) for r in grouped),
                        priority=int(priority),
                        profile=profile_name,
                        match=WindowMatch(**json.loads(match_json)),
                    )
                )
            return ProfilesDocument(
                profiles=profiles,
                desktop_profile="DESKTOP",
                active_profile="DESKTOP",
                persistent_profile=None,
                profile_switching_enabled=True,
                app_rules=app_rules,
            )

        self.profiles_config.load = _doc_from_legacy_rules  # type: ignore

        self.state = WindowDaemonState(
            profiles_config=self.profiles_config,
            start_injecting_fn=start_injecting,
            stop_injecting_fn=stop_injecting,
        )
        # For legacy tests, treat "autoload/desktop default" as a test-only
        # injection target so we can assert revert behavior.
        self.state._compute_device_targets = (  # type: ignore
            lambda doc, profile_name: (
                dict(desktop_defaults)
                if profile_name == "DESKTOP"
                else WindowDaemonState._compute_device_targets(self.state, doc, profile_name)
            )
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

        # Default is manual mode (automation disabled): should not start.
        self.assertEqual(len(self.start_calls), 0)
        self.assertEqual(self.state.get_managed_device_presets(), {})

        # Enabling automation should allow rules to apply.
        self.state.set_device_automation("Mouse", True)
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
        self.state.set_device_automation("Mouse", True)

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
        self.state.set_device_automation("Mouse", True)

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
        self.state.set_device_automation("Mouse", True)

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)
        self.assertIn("Mouse", self.state.get_managed_device_presets())

        # Desktop / lockscreen — managed device should revert
        self.state.on_window_changed(None)
        self._process_debounce()
        # Injection should still be active during grace window
        self.assertEqual(len(self.stop_calls), 0)
        # Grace timer should revert after NONE_WINDOW_GRACE_MS
        self.state._on_none_grace_elapsed()
        self.assertEqual(len(self.stop_calls), 1)
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
        self.state.set_device_automation("Mouse", True)

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
        self.state.set_device_automation("Mouse", True)

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 1)

        # Now switch to non-matching window
        self.state.on_window_changed(_make_window(window_class="browser"))
        self._process_debounce()
        # Should have stopped
        self.assertEqual(len(self.stop_calls), 1)
        self.assertNotIn("Mouse", self.state.get_managed_device_presets())

    def test_fallback_to_second_rule_when_first_fails(self):
        """If the best-matching rule cannot be applied (start_injecting False),
        the state should try the next matching rule for the same device.

        Note: the new Profile model selects one Profile, so it will not
        automatically fall back to a second independent profile definition.
        """
        self._write_rules([
            {
                "id": "bad",
                "device": "Mouse",
                "preset": "Missing",
                "priority": 10,
                "match": {"window_class_equals": "game"},
            },
            {
                "id": "good",
                "device": "Mouse",
                "preset": "Game",
                "priority": 0,
                "match": {"window_class_equals": "game"},
            },
        ])
        self.rules_config.load()
        self.state.set_device_automation("Mouse", True)

        # Make the first start fail, second succeed.
        original_start = self.state._start_injecting

        def start_injecting(group_key, preset):
            self.start_calls.append((group_key, preset))
            if preset == "Missing":
                return False
            return original_start(group_key, preset)

        self.state._start_injecting = start_injecting  # type: ignore

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()

        self.assertEqual(self.start_calls[0], ("Mouse", "Missing"))
        self.assertNotEqual(
            self.state.get_managed_device_presets().get("Mouse"), "Game"
        )

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
        self.state.set_device_automation("Mouse", True)

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
        self.state.set_device_automation("Mouse", True)
        self.state.set_device_automation("Keyboard", True)

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
        self.state.set_device_automation("Mouse", True)
        self.state.set_device_automation("Keyboard", True)

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
        # Keyboard should have been stopped (desktop default is blank in new model)
        self.assertIn("Keyboard", self.stop_calls)
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
        self.state.set_device_automation("Mouse", True)

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
        self.state.set_device_automation("Mouse", True)
        self.state.set_device_automation("Keyboard", True)

        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(len(self.start_calls), 2)

        # Switch to a non-matching window — both should revert
        self.state.on_window_changed(_make_window(window_class="other"))
        self._process_debounce()

        self.assertEqual(len(self.stop_calls), 2)
        self.assertEqual(self.state.get_managed_device_presets(), {})

    def test_disable_device_automation_stops_and_blocks_restart(self):
        self._write_rules([
            {
                "id": "r1",
                "device": "Mouse",
                "preset": "Game",
                "match": {"window_class_equals": "game"},
            }
        ])
        self.rules_config.load()

        self.state.set_device_automation("Mouse", True)

        # Enabled: should start
        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(self.start_calls, [("Mouse", "Game")])

        # Disable automation: should stop and forget
        self.state.set_device_automation("Mouse", False)
        self.assertEqual(self.stop_calls, ["Mouse"])
        self.assertEqual(self.state.get_managed_device_presets(), {})

        # Same window focus again: must not restart while disabled
        self.state.on_window_changed(_make_window(window_class="game"))
        self._process_debounce()
        self.assertEqual(self.start_calls, [("Mouse", "Game")])

        # Re-enable and evaluate: should start again
        self.state.set_device_automation("Mouse", True)
        self.state.evaluate_now()
        self.assertEqual(self.start_calls, [("Mouse", "Game"), ("Mouse", "Game")])


if __name__ == "__main__":
    unittest.main()
