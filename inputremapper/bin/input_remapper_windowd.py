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
"""Entry point for ``input-remapper-windowd``.

This process runs as the user (not root) and provides a session D-Bus
service that KWin scripts call when the foreground window changes.
It evaluates window rules and switches presets via the root system daemon.
"""

from __future__ import annotations

import signal
import sys

from inputremapper.logging.logger import logger
from inputremapper.windowd.service import WindowDaemonService


class WindowDaemonBin:
    """Manages the lifecycle of the window daemon service."""

    @staticmethod
    def main():
        logger.info("Starting input-remapper-windowd")

        service = WindowDaemonService()
        service.publish()

        # Register signal handlers for graceful shutdown
        def _handle_signal(signum, frame):
            logger.info("Received signal %d, shutting down", signum)
            service.quit_loop()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        service.run()


if __name__ == "__main__":
    WindowDaemonBin.main()
