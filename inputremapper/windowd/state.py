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
"""State machine for debounced profile switching based on the focused window.

G HUB model
-----------
- Automatic profile switching: match an app/game rule to pick an active Profile.
- Persistent profile: lock a Profile globally and disable switching.
- Desktop Profile: used when no rule matches (or no window focused).

At any time, each device has at most one effective preset injected (or none).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from inputremapper.logging.logger import logger
from inputremapper.profiles.config import BLANK_PRESET, ProfilesConfig
from inputremapper.windowd.matcher import WindowInfo
from inputremapper.windowd.config import WindowRule


class WindowDaemonState:
    """Tracks the current window and applies the correct Profile to devices."""

    DEBOUNCE_MS = 200
    NONE_WINDOW_GRACE_MS = 800

    def __init__(
        self,
        profiles_config: ProfilesConfig,
        start_injecting_fn: Callable[[str, str], bool],
        stop_injecting_fn: Callable[[str], None],
    ):
        self._profiles_config = profiles_config
        self._start_injecting = start_injecting_fn
        self._stop_injecting = stop_injecting_fn

        self.current_window: Optional[WindowInfo] = None
        # Name of the last profile that was applied to devices.
        self.current_profile: str = ""
        self._debounce_id: Optional[int] = None
        self._none_grace_id: Optional[int] = None

        # group_key -> preset_name (only for active injections)
        self.applied_presets: Dict[str, str] = {}
        # Devices currently managed by profile switching
        self._managed_devices: set[str] = set()
        # Per device: whether profile automation is enabled
        # group_key -> bool
        self._automation_enabled: Dict[str, bool] = {}

    # ---- Window event entrypoints ----

    def on_window_changed(self, window_info: Optional[WindowInfo]):
        if window_info is not None and self._none_grace_id is not None:
            GLib.source_remove(self._none_grace_id)
            self._none_grace_id = None

        self.current_window = window_info

        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None

        self._debounce_id = GLib.timeout_add(self.DEBOUNCE_MS, self._on_debounced)

    def evaluate_now(self):
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        if self._none_grace_id is not None:
            GLib.source_remove(self._none_grace_id)
            self._none_grace_id = None
        self._on_debounced()

    # ---- Core reconcile ----

    def _on_debounced(self) -> bool:
        self._debounce_id = None

        # Ensure migration happens once if needed.
        try:
            self._profiles_config.ensure_migrated_from_window_rules()
        except Exception:
            pass

        doc = self._profiles_config.load()

        if self.current_window is None:
            # Desktop / lockscreen: apply grace window to avoid transient focus.
            if self._managed_devices and self._none_grace_id is None:
                self._none_grace_id = GLib.timeout_add(
                    self.NONE_WINDOW_GRACE_MS,
                    self._on_none_grace_elapsed,
                )
            # If no device is managed, nothing to do.
            return False

        target_profile = self._pick_target_profile(doc)
        self._apply_profile(doc, target_profile)
        return False

    def _on_none_grace_elapsed(self) -> bool:
        self._none_grace_id = None
        if self.current_window is not None:
            return False

        doc = self._profiles_config.load()
        target_profile = self._pick_target_profile(doc, window_present=False)
        self._apply_profile(doc, target_profile)
        return False

    def _pick_target_profile(self, doc, window_present: bool = True) -> str:
        """Return the profile name that should be active now."""
        # Persistent overrides everything.
        if doc.persistent_profile and doc.persistent_profile in doc.profiles:
            return doc.persistent_profile

        if not doc.profile_switching_enabled:
            if doc.active_profile in doc.profiles:
                return doc.active_profile
            return doc.desktop_profile

        # Automatic switching enabled
        if not window_present:
            return doc.desktop_profile

        from inputremapper.windowd.profile_matcher import find_matching_app_rule

        rule = (
            find_matching_app_rule(doc.app_rules, self.current_window)
            if self.current_window is not None
            else None
        )
        if rule is not None and rule.profile in doc.profiles:
            return rule.profile
        return doc.desktop_profile

    def _compute_device_targets(self, doc, profile_name: str) -> Dict[str, str]:
        """Compute desired preset per device for *profile_name*.

        Desktop Profile acts as a base; the selected profile overrides it.
        Missing entries fall back to BLANK.
        """
        base = doc.profiles.get(doc.desktop_profile)
        target = doc.profiles.get(profile_name)

        mapping: Dict[str, str] = {}
        if base is not None:
            mapping.update({str(k): str(v) for k, v in base.device_presets.items()})
        if target is not None:
            mapping.update({str(k): str(v) for k, v in target.device_presets.items()})
        return mapping

    def _apply_profile(self, doc, profile_name: str) -> None:
        self.current_profile = str(profile_name or "")
        device_targets = self._compute_device_targets(doc, profile_name)

        # Filter by automation enablement: windowd should only manage devices that
        # opted into automation. This preserves the legacy Apply/Stop workflow.
        device_targets = {
            group_key: preset
            for group_key, preset in device_targets.items()
            if self.get_device_automation(group_key)
        }

        # Devices we should consider are: anything in device_targets or currently managed.
        wanted_devices = set(device_targets.keys()) | set(self._managed_devices)

        for group_key in sorted(wanted_devices):
            desired = str(device_targets.get(group_key, BLANK_PRESET) or BLANK_PRESET)
            current = self.applied_presets.get(group_key)

            if desired == BLANK_PRESET:
                if current is not None:
                    logger.info(
                        'Profile "%s": stopping device "%s" (blank)',
                        profile_name,
                        group_key,
                    )
                    self._stop_injecting(group_key)
                    self.applied_presets.pop(group_key, None)
                continue

            if current == desired:
                continue

            if current is not None:
                logger.info(
                    'Profile "%s": switching device "%s" from "%s" to "%s"',
                    profile_name,
                    group_key,
                    current,
                    desired,
                )
                self._stop_injecting(group_key)
                self.applied_presets.pop(group_key, None)
            else:
                logger.info(
                    'Profile "%s": starting device "%s" with preset "%s"',
                    profile_name,
                    group_key,
                    desired,
                )

            if self._start_injecting(group_key, desired):
                self.applied_presets[group_key] = desired
            else:
                logger.error(
                    'Profile "%s": failed to start preset "%s" for device "%s"',
                    profile_name,
                    desired,
                    group_key,
                )

        self._managed_devices = set(device_targets.keys())

    # ---- Inspection helpers ----

    def get_managed_device_presets(self) -> Dict[str, str]:
        return dict(self.applied_presets)

    def test_rule(self, rule: WindowRule) -> bool:
        """Evaluate *rule* against the current window without side-effects."""
        if self.current_window is None:
            return False

        match = rule.match
        # Reuse the same matching semantics as profile rules.
        # This keeps the GUI "Test match" behavior consistent while we migrate.
        if match.window_class_equals is not None:
            if self.current_window.window_class != match.window_class_equals:
                return False
        if match.window_class_regex is not None:
            import re

            if not re.search(match.window_class_regex, self.current_window.window_class):
                return False
        if match.title_equals is not None:
            if self.current_window.title != match.title_equals:
                return False
        if match.title_starts_with is not None:
            if not self.current_window.title.startswith(match.title_starts_with):
                return False
        if match.title_regex is not None:
            import re

            if not re.search(match.title_regex, self.current_window.title):
                return False
        if match.pid_cmdline_contains is not None:
            if match.pid_cmdline_contains not in self.current_window.cmdline_for_matching:
                return False
        if match.pid_cmdline_regex is not None:
            import re

            if not re.search(match.pid_cmdline_regex, self.current_window.cmdline_for_matching):
                return False
        return True

    # ---- Device automation (compat) ----

    def set_device_automation(self, group_key: str, enabled: bool) -> None:
        """Enable/disable automation for *group_key*.

        When disabling, stops injection and forgets managed state so that
        profile rules do not immediately restart injection.
        """
        self._automation_enabled[str(group_key)] = bool(enabled)
        if enabled:
            return

        if group_key in self.applied_presets:
            self._stop_injecting(group_key)
            self.applied_presets.pop(group_key, None)
        self._managed_devices.discard(group_key)

    def get_device_automation(self, group_key: str) -> bool:
        """Return whether automation is enabled for *group_key*.

        Defaults to ``False`` for backward compatibility with the legacy
        Apply/Stop workflow.
        """
        return bool(self._automation_enabled.get(str(group_key), False))

    def reset(self):
        for group_key in list(self.applied_presets.keys()):
            self._stop_injecting(group_key)
        self.applied_presets.clear()
        self._managed_devices.clear()
        self._automation_enabled.clear()
        self.current_window = None
        self.current_profile = ""
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        if self._none_grace_id is not None:
            GLib.source_remove(self._none_grace_id)
            self._none_grace_id = None
