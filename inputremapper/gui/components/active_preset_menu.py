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

"""G HUB-style active preset dropdown.

This component is intentionally simple:
- Shows the currently active preset in the headerbar.
- Provides a searchable popover list of presets.
- Selecting a preset immediately applies it (auto-apply).
"""

from __future__ import annotations

from typing import List, Optional

from gi.repository import Gtk, GLib

from inputremapper.gui.controller import Controller
from inputremapper.gui.gettext import _
from inputremapper.gui.messages.message_broker import MessageBroker, MessageType
from inputremapper.gui.messages.message_data import GroupData, PresetData
from inputremapper.gui.utils import CTX_APPLY, CTX_WARNING


class _PresetRow(Gtk.ListBoxRow):
    def __init__(self, preset_name: str):
        super().__init__()
        self.preset_name = preset_name
        label = Gtk.Label(label=preset_name, xalign=0)
        label.set_visible(True)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_visible(True)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.pack_start(label, True, True, 0)
        self.add(box)
        self.show_all()


class ActivePresetMenu:
    _POLL_MS = 1000

    def __init__(
        self,
        message_broker: MessageBroker,
        controller: Controller,
        label: Gtk.Label,
        popover: Gtk.Popover,
        search: Gtk.SearchEntry,
        listbox: Gtk.ListBox,
        add_btn: Gtk.Button,
        manage_btn: Gtk.Button,
        lock_icon: Optional[Gtk.Image] = None,
    ):
        self._message_broker = message_broker
        self._controller = controller
        self._label = label
        self._lock_icon = lock_icon
        self._popover = popover
        self._search = search
        self._listbox = listbox
        self._add_btn = add_btn
        self._manage_btn = manage_btn

        self._active_group_key: Optional[str] = None
        self._presets: List[str] = []
        self._active_preset: str = ""
        self._poll_id: Optional[int] = None
        self._last_seen_running_preset: str = ""

        self._search.connect("search-changed", self._on_search_changed)
        self._listbox.connect("row-activated", self._on_row_activated)
        self._add_btn.connect("clicked", lambda *_: self._on_add_profile())
        self._manage_btn.connect("clicked", lambda *_: self._on_manage_profiles())

        self._message_broker.subscribe(MessageType.group, self._on_group_changed)
        self._message_broker.subscribe(MessageType.preset, self._on_preset_changed)
        self._message_broker.subscribe(
            MessageType.injector_state, lambda *_: self._refresh_active_label()
        )

        self._popover.hide()
        self._refresh_active_label()
        self._ensure_polling()

    def _on_add_profile(self):
        self._popover.popdown()
        self._controller.add_preset()

    def _on_manage_profiles(self):
        group = self._controller.data_manager.active_group
        if group is None:
            return

        dialog = Gtk.Dialog(
            title=_("Manage Profiles"),
            transient_for=self._controller.gui.window if self._controller.gui else None,
            modal=True,
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Save"), Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_spacing(12)

        info = Gtk.Label(
            label=_("Create new profiles from the dropdown. Desktop Default is used when no window rule matches."),
            xalign=0,
        )
        info.set_line_wrap(True)
        content.pack_start(info, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_halign(Gtk.Align.FILL)
        content.pack_start(row, False, False, 0)

        label = Gtk.Label(label=_("Desktop Default"), xalign=0)
        row.pack_start(label, True, True, 0)

        combo = Gtk.ComboBoxText()
        combo.set_hexpand(True)
        combo.append_text(_("Built-in blank (no injection)"))  # built-in desktop blank
        for preset in self._presets:
            combo.append_text(preset)
        row.pack_end(combo, False, False, 0)

        # Preselect current config value if possible
        try:
            current = self._controller.data_manager.config.get_desktop_default_preset(
                group.key
            )
        except Exception:
            current = None
        if not current or str(current) == "__blank__":
            combo.set_active(0)
        elif str(current) in self._presets:
            combo.set_active(1 + self._presets.index(str(current)))
        else:
            combo.set_active(0)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            chosen = (combo.get_active_text() or "").strip()
            if chosen == _("Built-in blank (no injection)"):
                self._controller.data_manager.config.set_desktop_default_preset(
                    group.key, "__blank__"
                )
            elif not chosen:
                self._controller.data_manager.config.set_desktop_default_preset(
                    group.key, None
                )
            else:
                self._controller.data_manager.config.set_desktop_default_preset(
                    group.key, chosen
                )
            try:
                client = getattr(self._controller.data_manager, "_window_daemon_client", None)
                if client is not None and getattr(client, "connected", False):
                    client.evaluate_now()
            except Exception:
                pass

        dialog.destroy()
        self._popover.popdown()

    def _on_group_changed(self, data: GroupData):
        self._active_group_key = data.group_key
        self._presets = list(data.presets)
        self._rebuild_list()
        self._refresh_active_label()
        self._ensure_polling()

    def _on_preset_changed(self, data: PresetData):
        # In this refactor, preset selection implies activation, so keep the label in sync.
        if data.name:
            self._active_preset = data.name
        self._refresh_active_label()

    def _on_search_changed(self, *_):
        self._rebuild_list()

    def _rebuild_list(self):
        query = (self._search.get_text() or "").strip().lower()

        # Clear existing rows
        row = self._listbox.get_row_at_index(0)
        while row is not None:
            self._listbox.remove(row)
            row = self._listbox.get_row_at_index(0)

        for preset in self._presets:
            if query and query not in preset.lower():
                continue
            self._listbox.add(_PresetRow(preset))

        self._listbox.show_all()

    def _on_row_activated(self, _listbox, row: Gtk.ListBoxRow):
        if not isinstance(row, _PresetRow):
            return
        preset = row.preset_name
        self._popover.popdown()

        self._controller.load_preset(preset)

        group = self._controller.data_manager.active_group
        if group is None:
            return

        client = getattr(self._controller.data_manager, "_window_daemon_client", None)
        status = None
        if client is not None and getattr(client, "connected", False):
            try:
                status = client.get_status()
            except Exception:
                status = None

        auto_for_device = self._controller.is_window_rules_automatic_for_active_group()
        auto_globally = bool(status and status.get("profileSwitchingEnabled"))

        if auto_for_device or auto_globally:
            # G HUB-like semantics: selecting a profile binds it to the current
            # foreground app (not a global override). If global switching is on
            # but this device isn't opted in yet, enable it automatically.
            if not auto_for_device:
                try:
                    self._controller.set_window_rules_mode(group.key, "automatic")
                except Exception:
                    pass

            ok = (
                client is not None
                and getattr(client, "connected", False)
                and client.bind_preset_to_current_app(group.key, preset)
            )
            if ok:
                self._controller.show_status(
                    CTX_APPLY,
                    _("Assigned this profile to the current app"),
                )
            else:
                self._controller.show_status(
                    CTX_WARNING,
                    _("Failed to assign this profile to the current app"),
                    _("Is windowd running and an app window focused?"),
                )
            return

        # Manual: selecting a preset applies it immediately.
        GLib.idle_add(self._controller.start_injecting)

    # end _on_row_activated

    def _refresh_active_label(self):
        group = self._controller.data_manager.active_group
        if group is None:
            self._label.set_text(_("Desktop: Default"))
            if self._lock_icon is not None:
                self._lock_icon.set_visible(False)
            return

        manual = not self._controller.is_window_rules_automatic_for_active_group()
        if self._lock_icon is not None:
            self._lock_icon.set_visible(bool(manual))
            if manual:
                self._lock_icon.set_tooltip_text(
                    _("Locked (Manual): profile will not auto-switch")
                )
            else:
                self._lock_icon.set_tooltip_text(
                    _("Automatic: window rules control switching")
                )

        try:
            active = self._controller.data_manager.get_active_preset_name(group.key)
        except Exception:
            active = ""

        # If windowd is running, show the *effective* preset for the current
        # window (including Desktop/blank), not just the currently running
        # injection which may lag behind during debounce/grace periods.
        if not manual:
            client = getattr(self._controller.data_manager, "_window_daemon_client", None)
            status = None
            if client is not None and getattr(client, "connected", False):
                try:
                    status = client.get_status()
                except Exception:
                    status = None

            if isinstance(status, dict):
                applied_profile = str(status.get("appliedProfile") or "")
                effective_profile = str(status.get("effectiveProfile") or "")
                profile_name = applied_profile or effective_profile

                desired_map = status.get("desiredDevicePresets") or {}
                desired = ""
                if isinstance(desired_map, dict):
                    desired = str(desired_map.get(group.key) or "")

                if desired == "__blank__":
                    self._label.set_text(_("Desktop: Default"))
                    return

                if desired:
                    self._label.set_text(desired)
                    return

                # If windowd didn't report a desired preset for this device,
                # fall back to a friendly Desktop label when possible.
                if profile_name and profile_name.upper() == "DESKTOP":
                    self._label.set_text(_("Desktop: Default"))
                    return

        if not active:
            # Fallback: show currently loaded preset, or Desktop Default placeholder.
            active = self._controller.data_manager.active_preset.name if self._controller.data_manager.active_preset else ""

        if not active:
            try:
                if self._controller.data_manager.config.is_desktop_default_blank(
                    group.key
                ):
                    self._label.set_text(_("Desktop: Default"))
                    return
            except Exception:
                pass

        self._label.set_text(active if active else _("Desktop: Default"))

    def _ensure_polling(self):
        """Poll the system daemon for preset changes.

        The GUI doesn't receive a push notification when windowd (or another
        process) switches presets. Polling keeps the header label and editor
        in sync with the actually injected preset, matching the G HUB
        'follow active' UX.
        """
        if self._poll_id is not None:
            return

        self._poll_id = GLib.timeout_add(self._POLL_MS, self._on_poll_tick)

    def _on_poll_tick(self) -> bool:
        group = self._controller.data_manager.active_group
        if group is None:
            self._last_seen_running_preset = ""
            self._refresh_active_label()
            return True

        running = self._controller.data_manager.get_active_preset_name(group.key) or ""
        if running != self._last_seen_running_preset:
            self._last_seen_running_preset = running
            self._refresh_active_label()

            # Follow active: if window rules switched presets, load it into the editor.
            if (
                running
                and self._controller.is_window_rules_automatic_for_active_group()
                and (
                    self._controller.data_manager.active_preset is None
                    or self._controller.data_manager.active_preset.name != running
                )
            ):
                try:
                    self._controller.load_preset(running)
                except Exception:
                    # Ignore invalid presets (e.g. deleted while running).
                    pass

        return True
