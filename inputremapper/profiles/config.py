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
"""Profiles configuration: G HUB-like global profiles and automatic switching.

This file introduces a new config file ``profiles.json`` next to ``config.json``.
It stores:
- Profiles: per-profile per-device preset selections
- Automatic profile switching (by window/app rules)
- Persistent (locked) profile
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

try:
    from pydantic.v1 import BaseModel, ValidationError, validator
except ImportError:
    from pydantic import BaseModel, ValidationError, validator

from inputremapper.configs.paths import PathUtils
from inputremapper.logging.logger import logger
from inputremapper.configs.global_config import GlobalConfig
from inputremapper.windowd.config import WindowMatch, WindowRulesConfig, WindowRule


BLANK_PRESET = "__blank__"
DEFAULT_DESKTOP_PROFILE = "DESKTOP"
APP_PROFILE_PREFIX = "APP:"
APP_RULE_PREFIX = "app:"


class ProfileModel(BaseModel):
    """A global profile consisting of per-device preset selections."""

    device_presets: Dict[str, str] = {}


class AppRuleModel(BaseModel):
    """Match a foreground window and switch to a target profile."""

    id: str
    enabled: bool = True
    priority: int = 0
    profile: str
    match: WindowMatch


class PersistentAutoloadBackup(BaseModel):
    """Backup of config.json autoload before persistent profile overrides it."""

    enabled: bool = False
    autoload: Dict[str, str] = {}


class ProfilesDocument(BaseModel):
    """Root document stored in profiles.json."""

    version: int = 1
    profiles: Dict[str, ProfileModel] = {}
    desktop_profile: str = DEFAULT_DESKTOP_PROFILE
    active_profile: str = DEFAULT_DESKTOP_PROFILE
    persistent_profile: Optional[str] = None
    profile_switching_enabled: bool = False
    device_automation: Dict[str, bool] = {}
    app_rules: List[AppRuleModel] = []
    persistent_autoload_backup: PersistentAutoloadBackup = PersistentAutoloadBackup()

    @validator("desktop_profile", "active_profile")
    def _non_empty_profile_names(cls, value):
        if not value:
            raise ValueError("profile name must not be empty")
        return value


class ProfilesConfig:
    """Loads and saves profiles.json."""

    FILE_NAME = "profiles.json"

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = PathUtils.config_path()
        self.path = os.path.join(config_dir, self.FILE_NAME)
        self._doc: ProfilesDocument = ProfilesDocument(
            profiles={DEFAULT_DESKTOP_PROFILE: ProfileModel(device_presets={})},
            desktop_profile=DEFAULT_DESKTOP_PROFILE,
            active_profile=DEFAULT_DESKTOP_PROFILE,
        )

    def load(self) -> ProfilesDocument:
        if not os.path.exists(self.path):
            logger.debug('Profiles config "%s" not found, using defaults', self.path)
            return self._doc

        with open(self.path, "r") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError as exc:
                logger.error('Failed to parse "%s": %s', self.path, exc)
                return self._doc

        try:
            self._doc = ProfilesDocument(**raw)
        except ValidationError as exc:
            logger.error('Invalid profiles config "%s": %s', self.path, exc)
            return self._doc

        # Ensure desktop profile exists.
        if self._doc.desktop_profile not in self._doc.profiles:
            self._doc.profiles.setdefault(
                self._doc.desktop_profile, ProfileModel(device_presets={})
            )
        if self._doc.active_profile not in self._doc.profiles:
            self._doc.active_profile = self._doc.desktop_profile

        return self._doc

    def save(self, doc: Optional[ProfilesDocument] = None) -> None:
        if doc is not None:
            self._doc = doc
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._doc.dict(), f, indent=4)

    def get_doc(self) -> ProfilesDocument:
        return self._doc

    def compute_device_targets(self, profile_name: str) -> Dict[str, str]:
        """Return desired preset per device for *profile_name*.

        Desktop profile provides base values; profile overrides. Missing entries
        fall back to BLANK.
        """
        doc = self._doc
        base = doc.profiles.get(doc.desktop_profile)
        target = doc.profiles.get(profile_name)
        mapping: Dict[str, str] = {}
        if base is not None:
            mapping.update({str(k): str(v) for k, v in base.device_presets.items()})
        if target is not None:
            mapping.update({str(k): str(v) for k, v in target.device_presets.items()})
        return mapping

    def enable_persistent_profile(self, global_config: GlobalConfig, profile_name: str) -> None:
        """Enable Persistent Profile and override autoload accordingly."""
        self.load()
        if profile_name not in self._doc.profiles:
            raise ValueError(f'Unknown profile "{profile_name}"')

        if not self._doc.persistent_autoload_backup.enabled:
            self._doc.persistent_autoload_backup.enabled = True
            self._doc.persistent_autoload_backup.autoload = global_config.get_autoload_mapping()

        self._doc.persistent_profile = profile_name
        self._doc.active_profile = profile_name

        targets = self.compute_device_targets(profile_name)
        # Apply autoload overrides.
        all_keys = set(global_config.get_autoload_mapping().keys()) | set(targets.keys())
        for group_key in all_keys:
            desired = str(targets.get(group_key, BLANK_PRESET) or BLANK_PRESET)
            if desired == BLANK_PRESET:
                global_config.set_autoload_preset(group_key, None)
            else:
                global_config.set_autoload_preset(group_key, desired)

        self.save()

    def disable_persistent_profile(self, global_config: GlobalConfig) -> None:
        """Disable Persistent Profile and restore previous autoload mapping."""
        self.load()
        backup = self._doc.persistent_autoload_backup
        if backup.enabled:
            current = global_config.get_autoload_mapping()
            # Clear keys not present in backup.
            for group_key in set(current.keys()) - set(backup.autoload.keys()):
                global_config.set_autoload_preset(group_key, None)
            for group_key, preset in backup.autoload.items():
                global_config.set_autoload_preset(group_key, preset)

        self._doc.persistent_profile = None
        self._doc.persistent_autoload_backup = PersistentAutoloadBackup()
        self.save()

    def ensure_migrated_from_window_rules(self, config_dir: Optional[str] = None) -> bool:
        """If profiles.json doesn't exist but window_rules.json does, migrate.

        Returns True if migration occurred.
        """
        if config_dir is None:
            config_dir = os.path.dirname(self.path)

        if os.path.exists(self.path):
            return False

        rules_path = os.path.join(config_dir, WindowRulesConfig.FILE_NAME)
        if not os.path.exists(rules_path):
            return False

        try:
            rules_config = WindowRulesConfig(config_dir)
            rules: List[WindowRule] = rules_config.load()
        except Exception as exc:
            logger.error("Failed to migrate from window rules: %s", exc)
            return False

        # Build one Profile per old rule id, containing the single device preset.
        profiles: Dict[str, ProfileModel] = {DEFAULT_DESKTOP_PROFILE: ProfileModel()}
        app_rules: List[AppRuleModel] = []

        for rule in rules:
            profile_name = str(rule.id)
            if not profile_name:
                continue
            profiles.setdefault(profile_name, ProfileModel(device_presets={}))
            profiles[profile_name].device_presets[str(rule.device)] = str(rule.preset)
            app_rules.append(
                AppRuleModel(
                    id=str(rule.id),
                    enabled=bool(rule.enabled),
                    priority=int(rule.priority),
                    profile=profile_name,
                    match=rule.match,
                )
            )

        doc = ProfilesDocument(
            profiles=profiles,
            desktop_profile=DEFAULT_DESKTOP_PROFILE,
            active_profile=DEFAULT_DESKTOP_PROFILE,
            persistent_profile=None,
            profile_switching_enabled=True,
            app_rules=app_rules,
        )
        self._doc = doc
        self.save()
        logger.info("Migrated window rules to profiles.json (%d app rules)", len(app_rules))
        return True

    @staticmethod
    def _slug(value: str, limit: int = 64) -> str:
        value = PathUtils.sanitize_path_component(str(value or "")).strip()
        value = value.replace(" ", "-").lower()
        if not value:
            return "unknown"
        return value[:limit]

    @classmethod
    def app_profile_name(cls, window_class: str) -> str:
        """Return a stable profile name for an application window class."""
        window_class = str(window_class or "").strip()
        if not window_class:
            raise ValueError("window_class must not be empty")
        # Keep the original window class for readability, but prefix to avoid
        # collisions with DESKTOP or user-defined names.
        return f"{APP_PROFILE_PREFIX}{window_class}"

    @classmethod
    def app_rule_id(cls, window_class: str) -> str:
        """Return a stable rule id for an application window class."""
        return f"{APP_RULE_PREFIX}{cls._slug(window_class)}"

    @classmethod
    def association_profile_name(cls, kind: str, value: str) -> str:
        """Return a stable profile name for a window association.

        ``kind`` is one of: ``class``, ``cmdline``, ``title``.
        """
        kind = str(kind or "").strip().lower() or "unknown"
        value = str(value or "").strip()
        if not value:
            raise ValueError("association value must not be empty")
        return f"{APP_PROFILE_PREFIX}{kind}:{value}"

    @classmethod
    def association_rule_id(cls, kind: str, value: str) -> str:
        kind = str(kind or "").strip().lower() or "unknown"
        return f"{APP_RULE_PREFIX}{kind}:{cls._slug(value)}"

    def bind_device_preset_to_match(
        self,
        match: WindowMatch,
        *,
        kind: str,
        value: str,
        group_key: str,
        preset: str,
        priority: int = 1000,
    ) -> ProfilesDocument:
        """Bind *(group_key -> preset)* to a window association described by *match*."""
        doc = self.load()
        doc.profile_switching_enabled = True

        profile_name = self.association_profile_name(kind, value)
        doc.profiles.setdefault(profile_name, ProfileModel(device_presets={}))
        doc.profiles[profile_name].device_presets[str(group_key)] = str(preset)

        rule_id = self.association_rule_id(kind, value)

        existing = None
        for rule in doc.app_rules:
            if getattr(rule, "id", "") == rule_id:
                existing = rule
                break

        if existing is not None:
            existing.enabled = True
            existing.priority = int(priority)
            existing.profile = profile_name
            existing.match = match
        else:
            doc.app_rules.append(
                AppRuleModel(
                    id=rule_id,
                    enabled=True,
                    priority=int(priority),
                    profile=profile_name,
                    match=match,
                )
            )

        self.save(doc)
        return doc

    def bind_device_preset_to_app(
        self,
        window_class: str,
        group_key: str,
        preset: str,
        *,
        priority: int = 1000,
    ) -> ProfilesDocument:
        """Bind *(group_key -> preset)* to the app identified by *window_class*.

        This implements G HUB-like semantics: selecting a profile while an app is
        in the foreground should affect only that app, not all windows globally.
        """
        match = WindowMatch(window_class_equals=str(window_class))
        return self.bind_device_preset_to_match(
            match,
            kind="class",
            value=str(window_class),
            group_key=group_key,
            preset=preset,
            priority=priority,
        )
