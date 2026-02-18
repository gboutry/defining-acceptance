from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

try:
    import allure as _allure
except Exception:  # pragma: no cover - optional backend
    _allure = None


logger = logging.getLogger("defining_acceptance.reporting")


class ReportAdapter:
    @contextmanager
    def step(self, title: str):
        if _allure is not None:
            with _allure.step(title):
                yield
            return

        logger.info("STEP: %s", title)
        yield

    def note(self, message: str):
        logger.info(message)

    def attach_text(self, content: str, name: str):
        text = "" if content is None else str(content)
        if _allure is not None:
            _allure.attach(
                text,
                name=name,
                attachment_type=_allure.attachment_type.TEXT,
            )
            return

        logger.info("ATTACH[%s] %s", name, text)

    def attach_file(self, path: Path, name: str) -> None:
        if _allure is not None:
            _allure.attach.file(
                str(path),
                name=name,
                attachment_type=_allure.attachment_type.TEXT,
            )
            return

        logger.info("ATTACH_FILE[%s] %s", name, path)

    def label(self, name: str, value: str):
        if _allure is not None:
            _allure.dynamic.label(name, value)

    def parent_suite(self, name: str):
        if _allure is not None:
            _allure.dynamic.parent_suite(name)

    def suite(self, name: str):
        if _allure is not None:
            _allure.dynamic.suite(name)

    def sub_suite(self, name: str):
        if _allure is not None:
            _allure.dynamic.sub_suite(name)

    def description(self, text: str):
        if _allure is not None:
            _allure.dynamic.description(text)


report = ReportAdapter()
