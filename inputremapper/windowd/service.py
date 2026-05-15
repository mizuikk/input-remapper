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
"""Session D-Bus service for receiving KWin window focus notifications."""

from __future__ import annotations

import json
import os
import signal
import sys
from typing import Optional

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from dasbus.connection import SessionMessageBus
from dasbus.identifier import DBusServiceIdentifier
from dasbus.loop import EventLoop
from dasbus.error import DBusError

from inputremapper.configs.paths import PathUtils
from inputremapper.configs.global_config import GlobalConfig
from inputremapper.daemon import DAEMON as SYSTEM_DAEMON
from inputremapper.logging.logger import logger
from inputremapper.user import UserUtils
from inputremapper.windowd.config import WindowRulesConfig
from inputremapper.windowd.matcher import WindowInfo
from inputremapper.windowd.state import WindowDaemonState

SESSION_BUS = SessionMessageBus()

WINDOW_DAEMON = DBusServiceIdentifier(
    namespace=("inputremapper", "WindowDaemon"),
    message_bus=SESSION_BUS,
)


class WindowDaemonService:
    """Session D-Bus service that receives window focus changes from KWin.

    Exposes ``NotifyWindow``, ``Ping``, and ``Quit`` methods on the
    ``inputremapper.WindowDaemon`` session bus service.
    """

    __dbus_xml__ = f"""
        <node>
            <interface name='{WINDOW_DAEMON.interface_name}'>
                <method name='NotifyWindow'>
                    <arg type='s' name='window_json' direction='in'/>
                </method>
                <method name='Ping'>
                    <arg type='s' name='response' direction='out'/>
                </method>
                <method name='Quit'>
                </method>
                <method name='GetCurrentWindow'>
                    <arg type='s' name='response' direction='out'/>
                </method>
                <method name='EvaluateNow'>
                </method>
                <method name='TestRule'>
                    <arg type='s' name='rule_json' direction='in'/>
                    <arg type='s' name='response' direction='out'/>
                </method>
                <method name='GetStatus'>
                    <arg type='s' name='response' direction='out'/>
                </method>
                <method name='SetDeviceAutomation'>
                    <arg type='s' name='group_key' direction='in'/>
                    <arg type='b' name='enabled' direction='in'/>
                </method>
                <method name='GetDeviceAutomation'>
                    <arg type='s' name='group_key' direction='in'/>
                    <arg type='b' name='enabled' direction='out'/>
                </method>
            </interface>
        </node>
    """

    # Per the dasbus requirement: service name, object path, interface name
    service_name = WINDOW_DAEMON.service_name
    object_path = WINDOW_DAEMON.object_path

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = PathUtils.config_path()

        self._config_dir = config_dir
        self._rules_config = WindowRulesConfig(config_dir)
        self._rules_config.load()
        self._global_config = GlobalConfig()
        self._global_config.load_config(os.path.join(config_dir, "config.json"))

        # Connect to the system daemon
        self._system_daemon_proxy = self._connect_system_daemon()

        self._state = WindowDaemonState(
            rules_config=self._rules_config,
            start_injecting_fn=self._start_injecting,
            stop_injecting_fn=self._stop_injecting,
            autoload_single_fn=self._autoload_single,
            desktop_default_fn=self._desktop_default,
        )
        self._sync_automation_from_config()

        self._event_loop: Optional[EventLoop] = None

    def _sync_automation_from_config(self) -> None:
        """Initialize per-device automation from ``config.json``.

        The GUI persists the preference in ``window_rules_automation`` as
        "manual" (default) or "automatic".  windowd must mirror this so that
        rules do not override manual injection unless explicitly enabled.
        """
        try:
            self._global_config.load_config(os.path.join(self._config_dir, "config.json"))
        except Exception:
            return

        try:
            mapping = getattr(self._global_config, "_config", {}).get(
                "window_rules_automation", {}
            )
        except Exception:
            mapping = {}

        if not isinstance(mapping, dict):
            return

        for group_key, mode in mapping.items():
            if str(mode) == "automatic":
                try:
                    self._state.set_device_automation(str(group_key), True)
                except Exception:
                    continue

    def _connect_system_daemon(self):
        """Connect to the root daemon on the system bus."""
        try:
            proxy = SYSTEM_DAEMON.get_proxy()
            # Verify connectivity
            proxy.Introspect()
            proxy.set_config_dir(self._config_dir)
            logger.info("Connected to input-remapper system daemon")
            return proxy
        except DBusError as exc:
            logger.error("Failed to connect to system daemon: %s", exc)
            return None

    def publish(self):
        """Publish this service on the session D-Bus."""
        SESSION_BUS.publish_object(self.object_path, self)
        SESSION_BUS.register_service(self.service_name)
        logger.info(
            'Window daemon published on session bus as "%s" at "%s"',
            self.service_name,
            self.object_path,
        )

    def run(self):
        """Start the GLib event loop (blocks)."""
        self._event_loop = EventLoop()
        logger.info("Window daemon event loop started")
        self._event_loop.run()

    def quit_loop(self):
        """Stop the GLib event loop gracefully."""
        if self._event_loop is not None:
            self._event_loop.quit()
            self._event_loop = None

    # ---- D-Bus exposed methods ----

    def NotifyWindow(self, window_json: str) -> None:
        """Called by the KWin script when the foreground window changes.

        Parameters
        ----------
        window_json
            JSON string with keys: ``windowClass``, ``title``, ``pid``,
            ``internalId`` (optional).
        """
        try:
            data = json.loads(window_json)
        except json.JSONDecodeError as exc:
            logger.error("Invalid NotifyWindow JSON: %s", exc)
            return

        window_class = data.get("windowClass", "")
        title = data.get("title", "")
        pid = data.get("pid", 0)
        internal_id = data.get("internalId", "")

        if not window_class and not title:
            # KWin sends empty data for desktop / lockscreen
            self._state.on_window_changed(None)
            return

        window_info = WindowInfo(
            window_class=window_class,
            title=title,
            pid=pid,
            internal_id=internal_id,
        )
        self._state.on_window_changed(window_info)

    def Ping(self) -> str:
        """Health-check method."""
        return "pong"

    def Quit(self):
        """Shut down the window daemon gracefully."""
        logger.info("Window daemon Quit requested")
        self._state.reset()
        self.quit_loop()

    def GetCurrentWindow(self) -> str:
        """Return the current foreground window info as JSON.

        Returns a JSON object with keys ``windowClass``, ``title``, ``pid``,
        ``pidCmdline``, and ``internalId``.  All values are empty / zero when
        no application window is focused.
        """
        window = self._state.current_window
        if window is None:
            return json.dumps({
                "windowClass": "",
                "title": "",
                "pid": 0,
                "pidCmdline": "",
                "internalId": "",
            })
        return json.dumps({
            "windowClass": window.window_class,
            "title": window.title,
            "pid": window.pid,
            "pidCmdline": window.cmdline_for_matching,
            "internalId": window.internal_id,
        })

    def EvaluateNow(self):
        """Reload ``window_rules.json`` and reconcile immediately."""
        logger.info("WindowDaemonService: EvaluateNow requested")
        self._rules_config.load()
        self._state.evaluate_now()

    def TestRule(self, rule_json: str) -> str:
        """Validate and test a single window rule against the current window.

        Parameters
        ----------
        rule_json
            JSON string serialised from a ``WindowRule``.

        Returns
        -------
        str
            JSON with keys ``valid`` (bool), ``matches`` (bool), and
            ``error`` (str or null).
        """
        from inputremapper.windowd.config import WindowRule

        try:
            data = json.loads(rule_json)
            rule = WindowRule(**data)
        except Exception as exc:
            return json.dumps({
                "valid": False,
                "matches": False,
                "error": str(exc),
            })

        matches = self._state.test_rule(rule)
        return json.dumps({
            "valid": True,
            "matches": matches,
            "error": None,
        })

    def GetStatus(self) -> str:
        """Return runtime status information as JSON.

        Keys: ``running``, ``currentWindowPresent``, ``managedDevices``,
        ``configPath``.
        """
        window = self._state.current_window
        status = {
            "running": True,
            "currentWindowPresent": window is not None,
            "managedDevices": list(
                self._state.get_managed_device_presets().keys()
            ),
            "configPath": self._config_dir or "",
        }
        return json.dumps(status)

    def SetDeviceAutomation(self, group_key: str, enabled: bool) -> None:
        """Enable/disable window-rule automation for *group_key*.

        This does not persist any user preference; persistence is handled by the
        GUI via ``config.json``. Disabling immediately stops injection and clears
        managed state for that device so that rules won't restart it.
        """
        logger.info(
            'WindowDaemonService: SetDeviceAutomation group="%s" enabled=%s',
            group_key,
            enabled,
        )
        self._state.set_device_automation(group_key, bool(enabled))

    def GetDeviceAutomation(self, group_key: str) -> bool:
        """Return whether window-rule automation is enabled for *group_key*."""
        return bool(self._state.get_device_automation(group_key))

    # ---- System daemon proxy wrappers ----

    def _start_injecting(self, group_key: str, preset: str) -> bool:
        if self._system_daemon_proxy is None:
            logger.error("Cannot start injecting: not connected to system daemon")
            return False
        try:
            return bool(self._system_daemon_proxy.start_injecting(group_key, preset))
        except DBusError as exc:
            logger.error("DBus start_injecting failed: %s", exc)
            return False

    def _stop_injecting(self, group_key: str) -> None:
        if self._system_daemon_proxy is None:
            return
        try:
            self._system_daemon_proxy.stop_injecting(group_key)
        except DBusError as exc:
            logger.error("DBus stop_injecting failed: %s", exc)

    def _autoload_single(self, group_key: str) -> None:
        if self._system_daemon_proxy is None:
            return
        try:
            self._system_daemon_proxy.autoload_single(group_key)
        except DBusError as exc:
            logger.error("DBus autoload_single failed: %s", exc)

    def _desktop_default(self, group_key: str) -> None:
        """Apply the per-device Desktop Default preset (if configured)."""
        try:
            # Reload on every call to pick up edits from the GUI.
            self._global_config.load_config(os.path.join(self._config_dir, "config.json"))
            preset = self._global_config.get_desktop_default_preset(group_key)
        except Exception:
            preset = None

        if not preset:
            # Default to a built-in blank Desktop Default for better UX:
            # when no rule matches, stop injecting.
            if self._system_daemon_proxy is None:
                return
            try:
                self._system_daemon_proxy.stop_injecting(group_key)
            except DBusError:
                pass
            return

        if str(preset) == "__blank__":
            # Built-in blank: no injection on desktop.
            if self._system_daemon_proxy is None:
                return
            try:
                self._system_daemon_proxy.stop_injecting(group_key)
            except DBusError:
                pass
            return

        if self._system_daemon_proxy is None:
            return
        try:
            self._system_daemon_proxy.start_injecting(group_key, str(preset))
        except DBusError as exc:
            logger.error("DBus start_injecting (desktop default) failed: %s", exc)
