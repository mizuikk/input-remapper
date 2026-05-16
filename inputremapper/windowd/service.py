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
"""Session D-Bus service for receiving KWin window focus notifications.

This service implements G HUB-like Profile switching:
- Automatic switching (by app/window rules)
- Persistent (locked) profile
"""

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
from inputremapper.daemon import DAEMON as SYSTEM_DAEMON
from inputremapper.logging.logger import logger
from inputremapper.user import UserUtils
from inputremapper.profiles.config import ProfilesConfig, AppRuleModel
from inputremapper.configs.global_config import GlobalConfig
from inputremapper.windowd.config import WindowRulesConfig, WindowRule, WindowMatch
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
                <method name='SetActiveProfile'>
                    <arg type='s' name='profile' direction='in'/>
                </method>
                <method name='SetProfileSwitchingEnabled'>
                    <arg type='b' name='enabled' direction='in'/>
                </method>
                <method name='SetPersistentProfile'>
                    <arg type='s' name='profile' direction='in'/>
                </method>
                <!-- G HUB-like: while in automatic switching, bind a selection to the current app -->
                <method name='BindPresetToCurrentApp'>
                    <arg type='s' name='group_key' direction='in'/>
                    <arg type='s' name='preset' direction='in'/>
                    <arg type='b' name='ok' direction='out'/>
                </method>
                <!-- Backward-compatible per-device automation toggle -->
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
        # Keep legacy window-rules config around for the GUI editor during migration.
        self._rules_config = WindowRulesConfig(config_dir)
        self._rules_config.load()
        self._global_config = GlobalConfig()
        self._global_config.load_config(os.path.join(config_dir, "config.json"))

        self._profiles_config = ProfilesConfig(config_dir)
        self._profiles_config.ensure_migrated_from_window_rules(config_dir)
        self._profiles_config.load()

        # Connect to the system daemon
        self._system_daemon_proxy = self._connect_system_daemon()

        self._state = WindowDaemonState(
            profiles_config=self._profiles_config,
            start_injecting_fn=self._start_injecting,
            stop_injecting_fn=self._stop_injecting,
        )
        self._sync_automation_from_config()

        self._event_loop: Optional[EventLoop] = None

    def _sync_automation_from_config(self) -> None:
        """Initialize per-device automation from ``config.json``.

        During the migration, the GUI persists per-device automation as
        "manual" (default) or "automatic" in ``window_rules_automation``.
        windowd mirrors this into its runtime state so rules do not override
        manual injection unless explicitly enabled.
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
        """Reload ``profiles.json`` and reconcile immediately."""
        logger.info("WindowDaemonService: EvaluateNow requested")
        # Keep the legacy file in sync for GUI editing flows.
        try:
            self._rules_config.load()
        except Exception:
            pass
        self._profiles_config.load()
        self._state.evaluate_now()

    def TestRule(self, rule_json: str) -> str:
        """Validate and test a single rule against the current window.

        Parameters
        ----------
        rule_json
            JSON string serialized from a legacy ``WindowRule`` (GUI dialog).

        Returns
        -------
        str
            JSON with keys ``valid`` (bool), ``matches`` (bool), and
            ``error`` (str or null).
        """
        try:
            data = json.loads(rule_json)
            rule = WindowRule(**data)
        except Exception as exc:
            return json.dumps({
                "valid": False,
                "matches": False,
                "error": str(exc),
            })
        matches = bool(self._state.test_rule(rule))
        return json.dumps({
            "valid": True,
            "matches": matches,
            "error": None,
        })

    def GetStatus(self) -> str:
        """Return runtime status information as JSON.

        Keys include: ``running``, ``currentWindowPresent``, ``managedDevices``,
        ``configPath``, ``activeProfile``, ``persistentProfile``,
        ``profileSwitchingEnabled``.
        """
        window = self._state.current_window
        doc = self._profiles_config.load()
        # Best-effort: what profile should be active right now (based on focus),
        # vs what profile was last applied (after debounce/grace).
        try:
            effective_profile = self._state._pick_target_profile(  # type: ignore[attr-defined]
                doc,
                window_present=window is not None,
            )
        except Exception:
            effective_profile = doc.desktop_profile

        desired_presets = {}
        try:
            desired_presets = self._state._compute_device_targets(  # type: ignore[attr-defined]
                doc, effective_profile
            )
            # Mirror the same automation filter used during apply, so the GUI
            # reflects what windowd will actually manage.
            desired_presets = {
                str(k): str(v)
                for k, v in desired_presets.items()
                if self._state.get_device_automation(str(k))
            }
        except Exception:
            desired_presets = {}
        status = {
            "running": True,
            "currentWindowPresent": window is not None,
            "managedDevices": list(
                self._state.get_managed_device_presets().keys()
            ),
            "configPath": self._config_dir or "",
            "activeProfile": doc.active_profile,
            "effectiveProfile": effective_profile,
            "appliedProfile": getattr(self._state, "current_profile", "") or "",
            "persistentProfile": doc.persistent_profile or "",
            "profileSwitchingEnabled": bool(doc.profile_switching_enabled),
            "appliedDevicePresets": self._state.get_managed_device_presets(),
            "desiredDevicePresets": desired_presets,
        }
        return json.dumps(status)

    def SetActiveProfile(self, profile: str) -> None:
        """Set the manually active profile (used when switching is disabled)."""
        doc = self._profiles_config.load()
        if profile and profile in doc.profiles:
            doc.active_profile = str(profile)
            self._profiles_config.save(doc)
            self._state.evaluate_now()

    def SetProfileSwitchingEnabled(self, enabled: bool) -> None:
        """Enable/disable automatic profile switching."""
        doc = self._profiles_config.load()
        doc.profile_switching_enabled = bool(enabled)
        self._profiles_config.save(doc)
        self._state.evaluate_now()

    def SetPersistentProfile(self, profile: str) -> None:
        """Set (or clear) the persistent profile.

        Pass empty string to clear.
        """
        doc = self._profiles_config.load()
        if not profile:
            doc.persistent_profile = None
        elif profile in doc.profiles:
            doc.persistent_profile = str(profile)
        self._profiles_config.save(doc)
        self._state.evaluate_now()

    def BindPresetToCurrentApp(self, group_key: str, preset: str) -> bool:
        """Bind *(group_key -> preset)* to the currently focused app.

        Intended to mimic G HUB automatic-mode behavior: a manual selection
        affects only the frontmost app/game, not all windows globally.
        """
        window = self._state.current_window
        if window is None:
            return False

        try:
            window_class = str(getattr(window, "window_class", "") or "").strip()
            cmdline = str(getattr(window, "cmdline_for_matching", "") or "").strip()
            title = str(getattr(window, "title", "") or "").strip()

            # Do not create rules for the GUI itself; it causes confusing
            # self-referential switching when the user focuses the app.
            if window_class == "input-remapper-gtk":
                return False

            if window_class:
                from inputremapper.windowd.config import WindowMatch

                match = WindowMatch(window_class_equals=window_class)
                self._profiles_config.bind_device_preset_to_match(
                    match,
                    kind="class",
                    value=window_class,
                    group_key=str(group_key),
                    preset=str(preset),
                )
            elif cmdline:
                # Use only the executable token to keep the match stable.
                exe = cmdline.split()[0] if cmdline else ""
                if not exe:
                    return False
                from inputremapper.windowd.config import WindowMatch

                match = WindowMatch(pid_cmdline_contains=exe)
                self._profiles_config.bind_device_preset_to_match(
                    match,
                    kind="cmdline",
                    value=exe,
                    group_key=str(group_key),
                    preset=str(preset),
                )
            elif title:
                # Title can be volatile; prefer a short prefix for stability.
                from inputremapper.windowd.config import WindowMatch

                prefix = title[:20]
                match = WindowMatch(title_starts_with=prefix)
                self._profiles_config.bind_device_preset_to_match(
                    match,
                    kind="title",
                    value=prefix,
                    group_key=str(group_key),
                    preset=str(preset),
                )
            else:
                return False
        except Exception as exc:
            logger.error("BindPresetToCurrentApp failed: %s", exc)
            return False

        self._state.evaluate_now()
        return True

    def SetDeviceAutomation(self, group_key: str, enabled: bool) -> None:
        """(Compat) Enable/disable profile management for a single device."""
        doc = self._profiles_config.load()
        doc.device_automation[str(group_key)] = bool(enabled)
        self._profiles_config.save(doc)
        try:
            self._state.set_device_automation(str(group_key), bool(enabled))
        except Exception:
            pass
        self._state.evaluate_now()

    def GetDeviceAutomation(self, group_key: str) -> bool:
        """(Compat) Return whether profile management is enabled for a device."""
        try:
            return bool(self._state.get_device_automation(str(group_key)))
        except Exception:
            doc = self._profiles_config.load()
            return bool(doc.device_automation.get(str(group_key), False))

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
