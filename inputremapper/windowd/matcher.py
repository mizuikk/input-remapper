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
"""Window information data class and rule matching engine."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from inputremapper.windowd.config import WindowMatch, WindowRule
from inputremapper.logging.logger import logger


@dataclass(frozen=True)
class WindowInfo:
    """Information about the currently focused window, sent by the KWin script."""

    window_class: str
    title: str
    pid: int
    # Human-readable representation used for equality checks and logging
    pid_cmdline: str = ""
    internal_id: str = ""
    # Cached from /proc/:pid/cmdline for matching
    _pid_cmdline: str = field(default="")

    def __post_init__(self):
        """Populate pid_cmdline from /proc if not already set."""
        if not self._pid_cmdline and self.pid > 0:
            try:
                cmdline_path = f"/proc/{self.pid}/cmdline"
                if os.path.exists(cmdline_path):
                    with open(cmdline_path, "r") as f:
                        raw = f.read()
                    # cmdline is NUL-separated; use space-joined form
                    joined = raw.replace("\0", " ").strip()
                    object.__setattr__(self, "_pid_cmdline", joined)
            except (OSError, PermissionError):
                pass

    @property
    def cmdline_for_matching(self) -> str:
        """Return the cmdline string used for matching rules."""
        return self._pid_cmdline or self.pid_cmdline or ""


def match_rule(rule: WindowRule, window: WindowInfo) -> bool:
    """Check whether *all* non-None match fields of *rule* match *window*.

    Returns True if the rule applies to this window.
    """
    match = rule.match

    if match.window_class_equals is not None:
        if window.window_class != match.window_class_equals:
            return False

    if match.window_class_regex is not None:
        if not re.search(match.window_class_regex, window.window_class):
            return False

    if match.title_equals is not None:
        if window.title != match.title_equals:
            return False

    if match.title_starts_with is not None:
        if not window.title.startswith(match.title_starts_with):
            return False

    if match.title_regex is not None:
        if not re.search(match.title_regex, window.title):
            return False

    if match.pid_cmdline_contains is not None:
        if match.pid_cmdline_contains not in window.cmdline_for_matching:
            return False

    if match.pid_cmdline_regex is not None:
        if not re.search(match.pid_cmdline_regex, window.cmdline_for_matching):
            return False

    return True


def find_matching_rules_by_device(
    rules: List[WindowRule],
    window: WindowInfo,
) -> Dict[str, WindowRule]:
    """For each device, find the highest-priority enabled rule matching *window*.

    Rules within the same device are evaluated by priority descending.
    Ties are broken by original list order (first in config wins).
    Returns a dict mapping ``group_key → winning_WindowRule``.
    Returns an empty dict if no rule matches.
    """
    # Stable-sort enabled rules: priority descending, original order preserved
    sorted_rules = sorted(
        (r for r in rules if r.enabled),
        key=lambda r: (-r.priority, rules.index(r)),
    )

    result: Dict[str, WindowRule] = {}
    for rule in sorted_rules:
        if rule.device in result:
            # We already have this device's winning rule (higher priority
            # because of the sort order).
            continue

        if match_rule(rule, window):
            logger.debug(
                'Window rule "%s" matched device="%s" preset="%s"',
                rule.id,
                rule.device,
                rule.preset,
            )
            result[rule.device] = rule

    if result:
        return result

    logger.debug(
        'No window rule matched: window_class="%s", title="%s"',
        window.window_class,
        window.title,
    )
    return result
