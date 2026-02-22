from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from defining_acceptance.reporting import ReportAdapter, report


def test_set_event_callback_note_invokes_callback() -> None:
    """set_event_callback registers a callback called by note() with correct args."""
    adapter = ReportAdapter()
    cb = MagicMock()
    adapter.set_event_callback(cb)
    adapter.note("hello world")
    cb.assert_called_once()
    event_type, message, ts = cb.call_args[0]
    assert event_type == "note"
    assert message == "hello world"
    assert isinstance(ts, datetime)


def test_set_event_callback_none_disables_callback() -> None:
    """set_event_callback(None) disables the callback; note() does not crash."""
    adapter = ReportAdapter()
    cb = MagicMock()
    adapter.set_event_callback(cb)
    adapter.set_event_callback(None)
    adapter.note("should not crash")
    cb.assert_not_called()


def test_step_calls_callback_twice() -> None:
    """step() context manager invokes callback for start and end."""
    adapter = ReportAdapter()
    cb = MagicMock()
    adapter.set_event_callback(cb)
    with adapter.step("my task"):
        pass
    assert cb.call_count == 2


def test_step_callback_start_and_end_messages() -> None:
    """step() passes '<title> - start' and '<title> - end' to callback."""
    adapter = ReportAdapter()
    cb = MagicMock()
    adapter.set_event_callback(cb)
    with adapter.step("deploy"):
        pass
    first_call = cb.call_args_list[0][0]
    second_call = cb.call_args_list[1][0]
    assert first_call[0] == "step"
    assert first_call[1] == "deploy - start"
    assert second_call[0] == "step"
    assert second_call[1] == "deploy - end"


def test_step_no_callback_no_exception() -> None:
    """step() works without a registered callback."""
    adapter = ReportAdapter()
    with adapter.step("safe task"):
        pass  # must not raise


def test_attach_text_does_not_raise() -> None:
    """attach_text() does not raise for normal content."""
    adapter = ReportAdapter()
    adapter.attach_text("some content", "my-attachment")


def test_attach_text_handles_none_content() -> None:
    """attach_text() does not raise when content is None."""
    adapter = ReportAdapter()
    adapter.attach_text(None, "null-attachment")  # type: ignore[arg-type]


def test_attach_file_does_not_raise() -> None:
    """attach_file() does not raise given a Path."""
    adapter = ReportAdapter()
    adapter.attach_file(Path("/tmp/dummy.log"), "log-file")


def test_report_singleton_is_report_adapter() -> None:
    """Module-level report object is a ReportAdapter instance."""
    assert isinstance(report, ReportAdapter)
