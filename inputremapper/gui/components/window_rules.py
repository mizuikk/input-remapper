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
"""Window Rules GUI component.

Provides ``WindowRuleRow`` for the ``Gtk.ListBox`` and ``WindowRules`` as the
main component that manages the window-rule editing dialog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

from gi.repository import Gtk

from inputremapper.gui.gettext import _
from inputremapper.gui.utils import HandlerDisabled

if TYPE_CHECKING:
    from inputremapper.gui.controller import Controller
    from inputremapper.gui.messages.message_broker import MessageBroker
    from inputremapper.windowd.config import WindowMatch, WindowRule


class WindowRuleRow(Gtk.ListBoxRow):
    """A single rule displayed as a row in the window-rules listbox.

    Shows:
    - A ``Gtk.Switch`` for enabled/disabled.
    - A ``Gtk.Label`` for the priority number.
    - A ``Gtk.Label`` with a summary of the match conditions.
    """

    def __init__(
        self,
        rule: "WindowRule",
        on_toggled: Callable[["WindowRule"], None],
    ):
        super().__init__()
        self.rule = rule

        hbox = Gtk.Box(spacing=6, margin_start=6, margin_end=6,
                       margin_top=3, margin_bottom=3)
        hbox.set_visible(True)

        # Enabled switch
        self._switch = Gtk.Switch()
        self._switch.set_visible(True)
        self._switch.set_active(rule.enabled)
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch.connect("notify::active", self._on_switch_toggled)
        hbox.pack_start(self._switch, False, True, 0)

        # Priority label
        priority_label = Gtk.Label(label=str(rule.priority))
        priority_label.set_visible(True)
        priority_label.set_width_chars(3)
        priority_label.set_xalign(0.5)
        priority_label.set_halign(Gtk.Align.CENTER)
        priority_label.set_opacity(0.7)
        hbox.pack_start(priority_label, False, True, 0)

        # Match summary label
        self._summary_label = Gtk.Label(
            label=self._summarize_match(rule.match)
        )
        self._summary_label.set_visible(True)
        self._summary_label.set_xalign(0)
        self._summary_label.set_halign(Gtk.Align.START)
        self._summary_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self._summary_label.set_opacity(0.9 if rule.enabled else 0.5)
        hbox.pack_start(self._summary_label, True, True, 0)

        self.add(hbox)
        self._on_toggled = on_toggled

    def _on_switch_toggled(self, _switch, _param):
        self.rule.enabled = self._switch.get_active()
        self._summary_label.set_opacity(0.9 if self.rule.enabled else 0.5)
        self._on_toggled(self.rule)

    def refresh(self):
        """Update the display from ``self.rule``."""
        self._switch.set_active(self.rule.enabled)
        self._summary_label.set_text(self._summarize_match(self.rule.match))
        self._summary_label.set_opacity(0.9 if self.rule.enabled else 0.5)

    @staticmethod
    def _summarize_match(match: "WindowMatch") -> str:
        """Return a human-readable summary of the match conditions."""
        parts = []
        if match.window_class_equals:
            parts.append(f"class={match.window_class_equals}")
        if match.window_class_regex:
            parts.append(f"class~/{match.window_class_regex}/")
        if match.title_equals:
            parts.append(f"title={match.title_equals}")
        if match.title_starts_with:
            parts.append(f"title→{match.title_starts_with}")
        if match.title_regex:
            parts.append(f"title~/{match.title_regex}/")
        if match.pid_cmdline_contains:
            parts.append(f"cmd∈{match.pid_cmdline_contains}")
        if match.pid_cmdline_regex:
            parts.append(f"cmd~/{match.pid_cmdline_regex}/")
        return "; ".join(parts) if parts else _("(no match conditions)")


class WindowRules:
    """Manages the window-rules editing dialog.

    All widgets are passed in explicitly (like the ``StatusBar`` pattern) to
    avoid fragile tree-scanning with ``Gtk.Buildable.get_name``.
    """

    def __init__(
        self,
        message_broker: "MessageBroker",
        controller: "Controller",
        dialog: Gtk.Window,
        title: Gtk.Label,
        listbox: Gtk.ListBox,
        detail_grid: Gtk.Grid,
        enabled_switch: Gtk.Switch,
        priority_spin: Gtk.SpinButton,
        class_eq: Gtk.Entry,
        class_re: Gtk.Entry,
        title_eq: Gtk.Entry,
        title_sw: Gtk.Entry,
        title_re: Gtk.Entry,
        cmdline_contains: Gtk.Entry,
        cmdline_re: Gtk.Entry,
        add_btn: Gtk.Button,
        duplicate_btn: Gtk.Button,
        delete_btn: Gtk.Button,
        capture_btn: Gtk.Button,
        test_btn: Gtk.Button,
        cancel_btn: Gtk.Button,
        save_btn: Gtk.Button,
    ):
        self._message_broker = message_broker
        self._controller = controller
        self._gui = dialog
        self._title = title

        # Widget references
        self._listbox = listbox
        self._detail_grid = detail_grid
        self._enabled_switch = enabled_switch
        self._priority_spin = priority_spin
        self._class_eq = class_eq
        self._class_re = class_re
        self._title_eq = title_eq
        self._title_sw = title_sw
        self._title_re = title_re
        self._cmdline_contains = cmdline_contains
        self._cmdline_re = cmdline_re
        self._add_btn = add_btn
        self._duplicate_btn = duplicate_btn
        self._delete_btn = delete_btn
        self._capture_btn = capture_btn
        self._test_btn = test_btn
        self._cancel_btn = cancel_btn
        self._save_btn = save_btn

        # Internal state
        self._device: str = ""
        self._preset: str = ""
        self._rules: List["WindowRule"] = []
        self._selected_index: Optional[int] = None

        self._connect_signals()

    def _connect_signals(self):
        self._listbox.connect("row-selected", self._on_row_selected)
        self._add_btn.connect("clicked", self._on_add)
        self._duplicate_btn.connect("clicked", self._on_duplicate)
        self._delete_btn.connect("clicked", self._on_delete)
        self._capture_btn.connect("clicked", self._on_capture)
        self._test_btn.connect("clicked", self._on_test)
        self._cancel_btn.connect("clicked", self._on_cancel)
        self._save_btn.connect("clicked", self._on_save)

        # Detail-field change handlers — auto-save into _rules
        self._enabled_switch.connect("notify::active", self._on_detail_changed)
        self._priority_spin.connect("value-changed", self._on_detail_changed)
        self._class_eq.connect("changed", self._on_detail_changed)
        self._class_re.connect("changed", self._on_detail_changed)
        self._title_eq.connect("changed", self._on_detail_changed)
        self._title_sw.connect("changed", self._on_detail_changed)
        self._title_re.connect("changed", self._on_detail_changed)
        self._cmdline_contains.connect("changed", self._on_detail_changed)
        self._cmdline_re.connect("changed", self._on_detail_changed)

        # Hide on delete-event (like combination-editor)
        self._gui.connect("delete-event", lambda d, *_: d.hide() or True)

    # ---- Public API ----

    def open(self, device: str, preset: str):
        """Open the dialog for *device* and *preset*."""
        self._device = device
        self._preset = preset

        # Load existing rules for this device + preset
        self._rules = list(
            self._controller.data_manager.get_window_rules_for_device_preset(
                device, preset
            )
        )
        if not self._rules:
            self._rules.append(
                self._controller.data_manager.create_default_window_rule(
                    device, preset
                )
            )

        # Update title
        self._title.set_text(
            _('Rules for "%(preset)s" on %(device)s')
            % {"preset": preset, "device": device}
        )

        self._rebuild_listbox()
        # _selected_index is set by _on_row_selected when the signal fires
        # during select_row() below — do NOT clear it after.
        self._gui.show()

    def get_edited_rules(self) -> List["WindowRule"]:
        """Return the current in-memory rule list (after collecting any pending edits)."""
        self._collect_detail_fields()
        return list(self._rules)

    # ---- Internal helpers ----

    def _rebuild_listbox(self):
        """Clear and re-populate the rule listbox."""
        # Remove existing rows
        row = self._listbox.get_row_at_index(0)
        while row is not None:
            self._listbox.remove(row)
            row = self._listbox.get_row_at_index(0)

        # Add a row for each rule
        for rule in self._rules:
            row = WindowRuleRow(rule, self._on_rule_toggled)
            row.set_visible(True)
            self._listbox.add(row)

        # Select the first row if any
        first = self._listbox.get_row_at_index(0)
        if first is not None:
            self._listbox.select_row(first)

    def _on_rule_toggled(self, _rule: "WindowRule"):
        """Called when a rule's enabled switch changes (in the row)."""
        selected = self._listbox.get_selected_row()
        if selected is not None:
            idx = selected.get_index()
            if 0 <= idx < len(self._rules):
                self._fill_detail_grid(idx)

    def _on_row_selected(self, _listbox, row: Optional[Gtk.ListBoxRow]):
        """Save edits for the previously selected row, then fill the detail grid."""
        self._collect_detail_fields()

        if row is None:
            self._selected_index = None
            self._detail_grid.set_sensitive(False)
            return

        idx = row.get_index()
        if 0 <= idx < len(self._rules):
            self._selected_index = idx
            self._detail_grid.set_sensitive(True)
            self._fill_detail_grid(idx)

    def _fill_detail_grid(self, index: int):
        """Populate the detail form from ``self._rules[index]``."""
        rule = self._rules[index]
        match = rule.match

        with HandlerDisabled(self._enabled_switch, self._on_detail_changed):
            self._enabled_switch.set_active(rule.enabled)
        with HandlerDisabled(self._priority_spin, self._on_detail_changed):
            self._priority_spin.set_value(rule.priority)

        entries = [
            (self._class_eq, match.window_class_equals or ""),
            (self._class_re, match.window_class_regex or ""),
            (self._title_eq, match.title_equals or ""),
            (self._title_sw, match.title_starts_with or ""),
            (self._title_re, match.title_regex or ""),
            (self._cmdline_contains, match.pid_cmdline_contains or ""),
            (self._cmdline_re, match.pid_cmdline_regex or ""),
        ]
        for entry, value in entries:
            with HandlerDisabled(entry, self._on_detail_changed):
                entry.set_text(value)

    def _collect_detail_fields(self):
        """Write detail-grid values back into ``self._rules[self._selected_index]``."""
        if self._selected_index is None:
            return
        if not (0 <= self._selected_index < len(self._rules)):
            return

        rule = self._rules[self._selected_index]
        rule.enabled = self._enabled_switch.get_active()
        rule.priority = int(self._priority_spin.get_value())

        match = rule.match
        match.window_class_equals = self._get_text_or_none(self._class_eq)
        match.window_class_regex = self._get_text_or_none(self._class_re)
        match.title_equals = self._get_text_or_none(self._title_eq)
        match.title_starts_with = self._get_text_or_none(self._title_sw)
        match.title_regex = self._get_text_or_none(self._title_re)
        match.pid_cmdline_contains = self._get_text_or_none(self._cmdline_contains)
        match.pid_cmdline_regex = self._get_text_or_none(self._cmdline_re)

    @staticmethod
    def _get_text_or_none(entry: Gtk.Entry) -> Optional[str]:
        """Return the entry text or ``None`` if empty."""
        text = entry.get_text().strip()
        return text if text else None

    # ---- Signal handlers ----

    def _on_detail_changed(self, *_args):
        """Called when any detail field changes. Auto-updates the summary."""
        self._collect_detail_fields()
        selected = self._listbox.get_selected_row()
        if selected is not None and isinstance(selected, WindowRuleRow):
            selected.refresh()

    def _on_add(self, *_args):
        """Add a new empty rule."""
        self._collect_detail_fields()
        rule = self._controller.data_manager.create_default_window_rule(
            self._device, self._preset
        )
        self._rules.append(rule)
        # Clear selection before rebuild so the row-selected(None) signal
        # doesn't write stale form data over an existing rule.
        self._selected_index = None
        self._rebuild_listbox()
        last = self._listbox.get_row_at_index(len(self._rules) - 1)
        if last is not None:
            self._listbox.select_row(last)

    def _on_duplicate(self, *_args):
        """Duplicate the selected rule."""
        if self._selected_index is None:
            return
        self._collect_detail_fields()

        from copy import deepcopy
        import uuid

        rule = deepcopy(self._rules[self._selected_index])
        rule.id = f"{rule.id}-{str(uuid.uuid4())[:4]}"

        insert_pos = self._selected_index + 1
        self._rules.insert(insert_pos, rule)
        # Clear selection before rebuild so the row-selected(None) signal
        # doesn't write stale form data over an existing rule.
        self._selected_index = None
        self._rebuild_listbox()
        new_row = self._listbox.get_row_at_index(insert_pos)
        if new_row is not None:
            self._listbox.select_row(new_row)

    def _on_delete(self, *_args):
        """Delete the selected rule."""
        if self._selected_index is None:
            return
        self._collect_detail_fields()
        del self._rules[self._selected_index]
        # Clear selection BEFORE rebuild: the row-selected(None) signal fires
        # during listbox row removal and calls _collect_detail_fields(). If
        # _selected_index still points to the deleted slot, stale form data
        # overwrites the adjacent rule that shifted into that position.
        self._selected_index = None
        self._rebuild_listbox()

    def _on_capture(self, *_args):
        """Capture the current window and fill match fields."""
        data = self._controller.capture_current_window()
        if data is None:
            return

        self._collect_detail_fields()
        if self._selected_index is None:
            return

        rule = self._rules[self._selected_index]

        if data.get("windowClass"):
            rule.match.window_class_equals = data["windowClass"]

        title = data.get("title", "")
        if title and len(title) > 20:
            rule.match.title_starts_with = title[:20]
        elif title:
            rule.match.title_equals = title

        cmdline = data.get("pidCmdline", "")
        if cmdline:
            exe = cmdline.split()[0] if cmdline else ""
            if exe:
                rule.match.pid_cmdline_contains = exe

        self._fill_detail_grid(self._selected_index)

    def _on_test(self, *_args):
        """Test the currently edited rule against the current window."""
        self._collect_detail_fields()
        if self._selected_index is None:
            return

        rule = self._rules[self._selected_index]
        self._controller.test_window_rule_match(rule)

    def _on_cancel(self, *_args):
        """Close the dialog and discard edits."""
        self._gui.hide()

    def _on_save(self, *_args):
        """Validate and save all rules."""
        self._collect_detail_fields()
        self._controller.save_window_rules(self.get_edited_rules())
