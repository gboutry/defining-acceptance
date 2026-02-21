from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger("defining_acceptance.reporting")


class ReportAdapter:
    def __init__(self) -> None:
        self._event_callback: Callable[[str, str, datetime], None] | None = None

    def set_event_callback(
        self, fn: Callable[[str, str, datetime], None] | None
    ) -> None:
        """Register a callback invoked on step enter/exit with (detail, timestamp).

        Pass ``None`` to disable (fall back to logging).
        """
        self._event_callback = fn

    @contextmanager
    def step(self, title: str):
        ts = datetime.now()
        cb = self._event_callback
        if cb is not None:
            cb("step", f"{title} - start", ts)
        logger.info("STEP[start]: %s", title)
        try:
            yield
        finally:
            ts = datetime.now()
            cb = self._event_callback
            if cb is not None:
                cb("step", f"{title} - end", ts)
            logger.info("STEP[end]: %s", title)

    def note(self, message: str) -> None:
        ts = datetime.now()
        cb = self._event_callback
        if cb is not None:
            cb("note", message, ts)
        logger.info(message)

    def attach_text(self, content: str, name: str) -> None:
        text = "" if content is None else str(content)
        logger.info("ATTACH[%s] %s", name, text)

    def attach_file(self, path: Path, name: str) -> None:
        logger.info("ATTACH_FILE[%s] %s", name, path)


report = ReportAdapter()
