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
"""Session D-Bus client for the window daemon.

Provides a thin wrapper around the ``inputremapper.WindowDaemon`` session bus
service so that the GUI can call ``GetCurrentWindow``, ``EvaluateNow``,
``TestRule``, and ``GetStatus`` without dealing with raw D-Bus.
"""

from __future__ import annotations

import json
from typing import Optional

from dasbus.error import DBusError

from inputremapper.logging.logger import logger
from inputremapper.windowd.service import WINDOW_DAEMON


class WindowDaemonClient:
    """Thin D-Bus proxy for the window daemon on the session bus.

    All methods gracefully return ``None`` when the service is not reachable.
    Check ``self.connected`` to determine whether the service responded to
    introspection.
    """

    def __init__(self):
        self._proxy = WINDOW_DAEMON.get_proxy()
        self.connected: bool = False

        # Verify connectivity with an introspection call
        try:
            self._proxy.Introspect()
            self.connected = True
            logger.info("WindowDaemonClient: connected to window daemon")
        except DBusError as exc:
            logger.warning(
                "WindowDaemonClient: window daemon not reachable (%s)", exc
            )

    # ------------------------------------------------------------------ #
    # Public methods called by the GUI / controller
    # ------------------------------------------------------------------ #

    def get_current_window(self) -> Optional[dict]:
        """Return the current foreground-window info, or ``None``.

        The returned dict has the keys ``windowClass``, ``title``, ``pid``,
        ``pidCmdline``, and ``internalId``.  All values will be empty when no
        application window is focused.
        """
        if not self.connected:
            return None
        try:
            raw = self._proxy.GetCurrentWindow()
            return json.loads(raw)
        except (DBusError, json.JSONDecodeError) as exc:
            logger.error("WindowDaemonClient.GetCurrentWindow failed: %s", exc)
            return None

    def evaluate_now(self) -> bool:
        """Tell the window daemon to re-evaluate rules immediately.

        Returns ``True`` if the D-Bus call succeeded.
        """
        if not self.connected:
            return False
        try:
            self._proxy.EvaluateNow()
            return True
        except DBusError as exc:
            logger.error("WindowDaemonClient.EvaluateNow failed: %s", exc)
            return False

    def test_rule(self, rule_json: str) -> Optional[dict]:
        """Ask the window daemon to test *rule_json* against the current window.

        Returns a dict with keys ``valid``, ``matches``, and ``error``, or
        ``None`` if the call failed.
        """
        if not self.connected:
            return None
        try:
            raw = self._proxy.TestRule(rule_json)
            return json.loads(raw)
        except (DBusError, json.JSONDecodeError) as exc:
            logger.error("WindowDaemonClient.TestRule failed: %s", exc)
            return None

    def get_status(self) -> Optional[dict]:
        """Return runtime status information, or ``None``.

        The returned dict has keys ``running``, ``currentWindowPresent``,
        ``managedDevices``, and ``configPath``.
        """
        if not self.connected:
            return None
        try:
            raw = self._proxy.GetStatus()
            return json.loads(raw)
        except (DBusError, json.JSONDecodeError) as exc:
            logger.error("WindowDaemonClient.GetStatus failed: %s", exc)
            return None

    def set_device_automation(self, group_key: str, enabled: bool) -> bool:
        """Enable/disable window-rule automation for *group_key*.

        Returns ``True`` if the call succeeded.
        """
        if not self.connected:
            return False
        try:
            self._proxy.SetDeviceAutomation(group_key, bool(enabled))
            return True
        except DBusError as exc:
            logger.error("WindowDaemonClient.SetDeviceAutomation failed: %s", exc)
            return False

    def get_device_automation(self, group_key: str) -> Optional[bool]:
        """Return whether automation is enabled for *group_key*, or ``None``."""
        if not self.connected:
            return None
        try:
            return bool(self._proxy.GetDeviceAutomation(group_key))
        except DBusError as exc:
            logger.error("WindowDaemonClient.GetDeviceAutomation failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # G HUB-like profile switching (new API)
    # ------------------------------------------------------------------ #

    def set_active_profile(self, profile: str) -> bool:
        """Set the manually active profile (used when auto switching is disabled)."""
        if not self.connected:
            return False
        try:
            self._proxy.SetActiveProfile(str(profile))
            return True
        except DBusError as exc:
            logger.error("WindowDaemonClient.SetActiveProfile failed: %s", exc)
            return False

    def set_profile_switching_enabled(self, enabled: bool) -> bool:
        """Enable/disable automatic profile switching."""
        if not self.connected:
            return False
        try:
            self._proxy.SetProfileSwitchingEnabled(bool(enabled))
            return True
        except DBusError as exc:
            logger.error(
                "WindowDaemonClient.SetProfileSwitchingEnabled failed: %s", exc
            )
            return False

    def set_persistent_profile(self, profile: str) -> bool:
        """Set the persistent (locked) profile.

        Pass empty string to clear.
        """
        if not self.connected:
            return False
        try:
            self._proxy.SetPersistentProfile(str(profile))
            return True
        except DBusError as exc:
            logger.error("WindowDaemonClient.SetPersistentProfile failed: %s", exc)
            return False

    def bind_preset_to_current_app(self, group_key: str, preset: str) -> bool:
        """Bind *(group_key -> preset)* to the currently focused app in windowd.

        Returns ``True`` if the call succeeded and the daemon accepted the bind.
        """
        if not self.connected:
            return False
        try:
            return bool(self._proxy.BindPresetToCurrentApp(str(group_key), str(preset)))
        except DBusError as exc:
            logger.error("WindowDaemonClient.BindPresetToCurrentApp failed: %s", exc)
            return False
