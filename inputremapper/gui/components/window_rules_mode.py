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

"""Window rules automation mode switch.

This is a per-device setting (group_key) stored in config.json:
- Manual: legacy Apply/Stop buttons control injection.
- Automatic: window rules control injection for the device.
"""

from __future__ import annotations

from typing import Optional

from gi.repository import Gtk

from inputremapper.gui.controller import Controller
from inputremapper.gui.gettext import _
from inputremapper.gui.messages.message_broker import MessageBroker, MessageType
from inputremapper.gui.messages.message_data import GroupData, PresetData
from inputremapper.gui.utils import HandlerDisabled


class WindowRulesModeSwitch:
    """Gtk.Switch that toggles window rules automation per active device group."""

    def __init__(
        self,
        message_broker: MessageBroker,
        controller: Controller,
        switch: Gtk.Switch,
        label: Optional[Gtk.Label] = None,
    ):
        self._message_broker = message_broker
        self._controller = controller
        self._gui = switch
        self._label = label

        self._active_group_key: Optional[str] = None

        self._gui.connect("state-set", self._on_gtk_toggle)
        self._message_broker.subscribe(MessageType.group, self._on_group_changed)
        self._message_broker.subscribe(MessageType.preset, self._on_preset_changed)

        self._update_from_active_group()

    def _on_group_changed(self, data: GroupData):
        self._active_group_key = data.group_key
        self._update_from_active_group()

    def _on_preset_changed(self, _data: PresetData):
        # Mode is per device group, but preset changes should still refresh
        # button states/tooltips.
        self._update_from_active_group()

    def _update_from_active_group(self):
        group_key = (
            self._controller.data_manager.active_group.key
            if self._controller.data_manager.active_group
            else None
        )
        self._active_group_key = group_key

        enabled = group_key is not None
        self._gui.set_sensitive(enabled)
        if self._label is not None:
            self._label.set_sensitive(enabled)

        if group_key is None:
            with HandlerDisabled(self._gui, self._on_gtk_toggle):
                self._gui.set_active(False)
            self._gui.set_tooltip_text(
                _("Select a device to configure window rules automation")
            )
            return

        mode = self._controller.data_manager.get_window_rules_mode(group_key)
        is_automatic = mode == "automatic"
        with HandlerDisabled(self._gui, self._on_gtk_toggle):
            self._gui.set_active(is_automatic)

        self._gui.set_tooltip_text(
            _("When enabled, window rules control which preset is injected for this device")
        )
        self._controller.update_manual_controls_for_window_rules_mode()

    def _on_gtk_toggle(self, *_):
        group_key = self._active_group_key
        if group_key is None:
            return

        mode = "automatic" if self._gui.get_active() else "manual"
        self._controller.set_window_rules_mode(group_key, mode)

