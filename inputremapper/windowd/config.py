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
"""Window rules configuration models and file I/O."""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

try:
    from pydantic.v1 import BaseModel, validator, ValidationError
except ImportError:
    from pydantic import BaseModel, validator, ValidationError

from inputremapper.configs.paths import PathUtils
from inputremapper.logging.logger import logger


class WindowMatch(BaseModel):
    """Fields to match against the current foreground window.

    Within a single rule all non-None fields are ANDed together:
    the rule matches only if every specified condition is satisfied.
    """

    window_class_equals: Optional[str] = None
    window_class_regex: Optional[str] = None
    title_equals: Optional[str] = None
    title_starts_with: Optional[str] = None
    title_regex: Optional[str] = None
    pid_cmdline_contains: Optional[str] = None
    pid_cmdline_regex: Optional[str] = None

    @validator("window_class_regex", "title_regex", "pid_cmdline_regex")
    def validate_regex(cls, value):
        """Check that the pattern compiles at config-load time."""
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"Invalid regex '{value}': {exc}")
        return value


class WindowRule(BaseModel):
    """A single window rule: match conditions + device + preset to apply."""

    id: str
    enabled: bool = True
    priority: int = 0
    device: str
    preset: str
    match: WindowMatch


class WindowRulesConfig:
    """Loads and saves window rules from a JSON file in the config directory.

    The file is named ``window_rules.json`` and lives next to ``config.json``.
    """

    FILE_NAME = "window_rules.json"

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = PathUtils.config_path()
        self.path = os.path.join(config_dir, self.FILE_NAME)
        self._rules: List[WindowRule] = []

    def load(self) -> List[WindowRule]:
        """Load rules from disk. Returns the (possibly empty) rule list."""
        if not os.path.exists(self.path):
            logger.debug('Window rules "%s" not found, using empty ruleset', self.path)
            self._rules = []
            return []

        with open(self.path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                logger.error(
                    'Failed to parse window rules "%s": %s', self.path, exc
                )
                self._rules = []
                return []

        if isinstance(data, list):
            raw_rules = data
        elif isinstance(data, dict):
            raw_rules = data.get("rules", [])
        else:
            logger.error(
                'Unexpected format in "%s", expected object or array', self.path
            )
            self._rules = []
            return []

        rules: List[WindowRule] = []
        for i, entry in enumerate(raw_rules):
            try:
                rules.append(WindowRule(**entry))
            except ValidationError as exc:
                logger.error(
                    'Skipping invalid window rule at index %d in "%s": %s',
                    i,
                    self.path,
                    exc,
                )
                continue

        self._rules = rules
        return rules

    def get_rules(self) -> List[WindowRule]:
        """Return the currently loaded rule list (call load() first)."""
        return list(self._rules)

    def set_rules(self, rules: List[WindowRule]):
        """Replace and persist the rule list."""
        self._rules = list(rules)
        self._save()

    def _save(self):
        """Write the current rules to disk."""
        PathUtils.touch(self.path)
        raw = [rule.dict() for rule in self._rules]
        with open(self.path, "w") as f:
            json.dump(raw, f, indent=4)
            f.write("\n")
        logger.info('Saved %d window rules to "%s"', len(self._rules), self.path)
