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
"""Store which presets should be enabled for which device on login."""

from __future__ import annotations

import copy
import json
import os
from typing import Optional

from inputremapper.configs.paths import PathUtils
from inputremapper.logging.logger import logger, VERSION
from inputremapper.user import UserUtils

MOUSE = "mouse"
WHEEL = "wheel"
BUTTONS = "buttons"
NONE = "none"

INITIAL_CONFIG = {
    "version": VERSION,
    "autoload": {},
    # Per device group_key: "manual" | "automatic"
    # "manual" keeps the legacy Apply/Stop workflow.
    # "automatic" lets window rules control injection.
    "window_rules_automation": {},
    # Per device group_key: preset name to use when no window rule matches.
    # This is the G HUB-like "Desktop: Default" profile.
    # When unset, window rules default to a built-in blank (no injection).
    "desktop_default": {},
    # Remember last UI selection to restore workspace on next start.
    "last_active_group_key": None,
    "last_active_preset": {},
    # Home (Devices page): show non-typical/unknown devices too.
    "show_other_devices": False,
}


class GlobalConfig:
    """Configures stuff like autoloading in ~/.config/input-remapper-2/config.json."""

    def __init__(self):
        self.path = os.path.join(PathUtils.config_path(), "config.json")
        self._config = copy.deepcopy(INITIAL_CONFIG)

    def get_dir(self) -> str:
        """The folder containing this config."""
        return os.path.split(self.path)[0]

    def get_autoload_preset(self, group_key: str) -> Optional[str]:
        # modifications are only allowed via the setter, because it needs to write
        # the config file too. Therefore return a copy to prevent inconsistencies.
        return copy.deepcopy(self._config["autoload"].get(group_key))

    def get_window_rules_mode(self, group_key: str) -> str:
        """Return the window-rules automation mode for *group_key*.

        Returns "manual" by default for backward compatibility.
        """
        return str(
            self._config.get("window_rules_automation", {}).get(group_key, "manual")
        )

    def get_desktop_default_preset(self, group_key: str) -> Optional[str]:
        """Return the per-device Desktop Default preset name (or ``None``)."""
        value = self._config.get("desktop_default", {}).get(group_key)
        if value is None:
            return None
        return str(value)

    def set_desktop_default_preset(self, group_key: str, preset: Optional[str]):
        """Set the Desktop Default preset for *group_key*.

        Parameters
        ----------
        group_key
            Unique identifier of the device group.
        preset
            Preset name, or ``None`` to clear.
        """
        if preset is None:
            self._config.get("desktop_default", {}).pop(group_key, None)
        else:
            self._config.setdefault("desktop_default", {})[group_key] = str(preset)
        self._save_config()

    def is_desktop_default_blank(self, group_key: str) -> bool:
        """Return True if Desktop Default is configured as built-in blank."""
        return self.get_desktop_default_preset(group_key) == "__blank__"

    def set_window_rules_mode(self, group_key: str, mode: str):
        """Set the window-rules automation mode for *group_key*.

        Parameters
        ----------
        group_key
            Unique identifier of the device group.
        mode
            "manual" or "automatic".
        """
        if mode not in ("manual", "automatic"):
            raise ValueError('Expected mode to be "manual" or "automatic"')

        if mode == "manual":
            # Keep file small: store only non-default values.
            self._config.get("window_rules_automation", {}).pop(group_key, None)
        else:
            self._config.setdefault("window_rules_automation", {})[group_key] = mode

        self._save_config()

    def set_autoload_preset(self, group_key: str, preset: Optional[str]):
        """Set a preset to be automatically applied on start.

        Parameters
        ----------
        group_key
            the unique identifier of the group. This is used instead of the
            name to enable autoloading two different presets when two similar
            devices are connected.
        preset
            if None, don't autoload something for this device.
        """
        if preset is not None:
            self._config["autoload"][group_key] = preset
        else:
            logger.info('Not injecting for "%s" automatically anmore', group_key)
            del self._config["autoload"][group_key]

        self._save_config()

    def get_last_active_group_key(self) -> Optional[str]:
        value = self._config.get("last_active_group_key")
        if value is None:
            return None
        return str(value)

    def set_last_active_group_key(self, group_key: Optional[str]):
        self._config["last_active_group_key"] = str(group_key) if group_key else None
        self._save_config()

    def get_last_active_preset(self, group_key: str) -> Optional[str]:
        value = self._config.get("last_active_preset", {}).get(group_key)
        if value is None:
            return None
        return str(value)

    def set_last_active_preset(self, group_key: str, preset: Optional[str]):
        if preset is None:
            self._config.get("last_active_preset", {}).pop(group_key, None)
        else:
            self._config.setdefault("last_active_preset", {})[group_key] = str(preset)
        self._save_config()

    def get_show_other_devices(self) -> bool:
        return bool(self._config.get("show_other_devices", False))

    def set_show_other_devices(self, enabled: bool):
        self._config["show_other_devices"] = bool(enabled)
        self._save_config()

    def iterate_autoload_presets(self):
        """Get tuples of (device, preset)."""
        return self._config.get("autoload", {}).items()

    def is_autoloaded(self, group_key: Optional[str], preset: Optional[str]):
        """Should this preset be loaded automatically?"""
        if group_key is None or preset is None:
            raise ValueError("Expected group_key and preset to not be None")

        return self._config.get("autoload", {}).get(group_key) == preset

    def load_config(self, path: Optional[str] = None):
        """Load the config from the file system.
        Parameters
        ----------
        path
            If set, will change the path to load from and save to.
        """
        if path is not None:
            if not os.path.exists(path):
                logger.error('Config at "%s" not found', path)
                return

            self.path = path

        self._clear_config()

        if not os.path.exists(self.path):
            # treated like an empty config
            logger.debug('Config "%s" doesn\'t exist yet', self.path)
            self._clear_config()
            self._save_config()
            return

        with open(self.path, "r") as file:
            try:
                loaded = json.load(file)
                # Start from defaults so new keys get sensible values even when
                # loading older config files.
                self._clear_config()
                if isinstance(loaded, dict):
                    self._config.update(loaded)
                logger.info('Loaded config from "%s"', self.path)
            except json.decoder.JSONDecodeError as error:
                logger.error(
                    'Failed to parse config "%s": %s. Using defaults',
                    self.path,
                    str(error),
                )
                self._clear_config()

    def _save_config(self):
        """Save the config to the file system."""
        if UserUtils.user == "root":
            logger.debug("Skipping config file creation for the root user")
            return

        PathUtils.touch(self.path)

        with open(self.path, "w") as file:
            json.dump(self._config, file, indent=4)
            logger.info("Saved config to %s", self.path)
            file.write("\n")

    def _clear_config(self):
        """Remove all configurations in memory."""
        self._config = copy.deepcopy(INITIAL_CONFIG)
