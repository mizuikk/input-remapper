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
"""Match App/Game rules (Profile switching rules) against the focused window."""

from __future__ import annotations

import re
from typing import List, Optional

from inputremapper.logging.logger import logger
from inputremapper.profiles.config import AppRuleModel
from inputremapper.windowd.matcher import WindowInfo


def _match_fields(match, window: WindowInfo) -> bool:
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


def match_app_rule(rule: AppRuleModel, window: WindowInfo) -> bool:
    return _match_fields(rule.match, window)


def find_matching_app_rule(
    rules: List[AppRuleModel],
    window: WindowInfo,
) -> Optional[AppRuleModel]:
    """Return the best matching enabled app rule for *window*."""
    enabled = [(i, r) for i, r in enumerate(rules) if getattr(r, "enabled", True)]
    enabled.sort(key=lambda t: (-int(getattr(t[1], "priority", 0)), t[0]))

    for _, rule in enabled:
        if match_app_rule(rule, window):
            logger.debug(
                'App rule "%s" matched profile="%s"',
                getattr(rule, "id", ""),
                getattr(rule, "profile", ""),
            )
            return rule
    return None

