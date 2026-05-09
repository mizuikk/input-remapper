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
"""State machine for debounced window-rule evaluation and preset switching.

After each debounce period the state machine performs a full *reconcile*:
it computes what each device *should* have based on the current window,
then adjusts the running injectors to match.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from inputremapper.logging.logger import logger
from inputremapper.windowd.config import WindowRule, WindowRulesConfig
from inputremapper.windowd.matcher import WindowInfo, find_matching_rules_by_device


class WindowDaemonState:
    """Tracks the current window, applied presets, and debounces changes.

    Responsibilities
    ----------------
    - Debounce rapid window changes (e.g. Alt+Tab, overlay windows).
    - Match rules against the current window.
    - Call the daemon proxy to start/stop injection.
    - Avoid redundant ``start_injecting`` calls for the same (device, preset).
    - Revert to default (autoload) when no rule matches.
    """

    DEBOUNCE_MS = 200

    def __init__(
        self,
        rules_config: WindowRulesConfig,
        start_injecting_fn: Callable[[str, str], bool],
        stop_injecting_fn: Callable[[str], None],
        autoload_single_fn: Callable[[str], None],
    ):
        self._rules_config = rules_config
        self._start_injecting = start_injecting_fn
        self._stop_injecting = stop_injecting_fn
        self._autoload_single = autoload_single_fn

        # Current window information (None = no window, desktop, lockscreen, etc.)
        self.current_window: Optional[WindowInfo] = None

        # Per device: which preset is currently applied
        # group_key -> preset_name
        self.applied_presets: Dict[str, str] = {}

        # Debounce timer ID for GLib
        self._debounce_id: Optional[int] = None

        # Track which devices are "managed" by window rules
        self._managed_devices: set = set()

    def on_window_changed(self, window_info: Optional[WindowInfo]):
        """Entry point called when KWin reports a new foreground window.

        Debounces rapid changes before evaluating rules.
        """
        self.current_window = window_info

        # Cancel any pending debounce timer
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None

        # Schedule evaluation after debounce
        self._debounce_id = GLib.timeout_add(
            self.DEBOUNCE_MS,
            self._on_debounced,
        )

    def _on_debounced(self) -> bool:
        """Called after debounce period. Reconcilies wanted vs applied state."""
        self._debounce_id = None

        # 1. Reload config on every trigger to pick up external edits
        rules = self._rules_config.load()

        # 2. Compute what each device *should* have.
        #    No window (desktop/lockscreen) → no rules apply → empty wanted.
        if self.current_window is None:
            wanted: Dict[str, WindowRule] = {}
        else:
            wanted = find_matching_rules_by_device(rules, self.current_window)

        # 3. Reconcile: apply changes for wanted devices
        for group_key, rule in wanted.items():
            preset = rule.preset
            current = self.applied_presets.get(group_key)

            if current == preset:
                logger.debug(
                    'Preset "%s" for device "%s" already active, skipping',
                    preset,
                    group_key,
                )
                continue

            # Stop current injection if changing preset
            if group_key in self.applied_presets:
                logger.info(
                    'Window rule "%s": switching device "%s" from "%s" to "%s"',
                    rule.id,
                    group_key,
                    current,
                    preset,
                )
                self._stop_injecting(group_key)
                del self.applied_presets[group_key]
            else:
                logger.info(
                    'Window rule "%s": starting device "%s" with preset "%s"',
                    rule.id,
                    group_key,
                    preset,
                )

            success = self._start_injecting(group_key, preset)
            if success:
                self.applied_presets[group_key] = preset
            else:
                logger.error(
                    'Failed to start injection for device "%s" with preset "%s"',
                    group_key,
                    preset,
                )

        # 4. Reconcile: revert devices that were managed but no longer match
        for group_key in list(self._managed_devices):
            if group_key not in wanted:
                logger.info(
                    'No rule matches device "%s", reverting to default',
                    group_key,
                )
                self._revert_to_default(group_key)

        # 5. Update managed set
        self._managed_devices = set(wanted.keys())

        return False

    def _revert_to_default(self, group_key: str):
        """Revert to the autoload default preset for *group_key*."""
        if group_key in self.applied_presets:
            self._stop_injecting(group_key)
            del self.applied_presets[group_key]

        # Let the daemon apply the configured autoload preset.
        # If none is configured, autoload_single is a no-op.
        self._autoload_single(group_key)

    def get_managed_device_presets(self) -> Dict[str, str]:
        """Return a copy of the currently applied presets for inspection."""
        return dict(self.applied_presets)

    def evaluate_now(self):
        """Perform an immediate reconcile without debouncing.

        Cancels any pending debounce timer, reloads rules from disk, and
        runs the full reconcile path.  Called by the D-Bus ``EvaluateNow``
        method so that the GUI can apply saved changes immediately.
        """
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        self._on_debounced()

    def test_rule(self, rule: WindowRule) -> bool:
        """Evaluate *rule* against the current window without side-effects.

        Returns ``True`` if the rule matches, ``False`` otherwise.
        Always returns ``False`` when no window is currently focused.
        """
        if self.current_window is None:
            return False
        from inputremapper.windowd.matcher import match_rule

        return match_rule(rule, self.current_window)

    def reset(self):
        """Stop all managed injections and clear state."""
        for group_key in list(self.applied_presets.keys()):
            self._stop_injecting(group_key)
        self.applied_presets.clear()
        self._managed_devices.clear()
        self.current_window = None
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
