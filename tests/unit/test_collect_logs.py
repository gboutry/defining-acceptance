from __future__ import annotations

from defining_acceptance.collect_logs import _sanitize


def test_alphanumeric_and_safe_chars_preserved() -> None:
    """Alphanumeric characters and '.', '_', '-' pass through unchanged."""
    assert _sanitize("abc.XYZ_123-ok") == "abc.XYZ_123-ok"


def test_spaces_become_underscores() -> None:
    """Spaces are replaced with underscores."""
    assert _sanitize("hello world") == "hello_world"


def test_special_chars_become_underscores() -> None:
    """Special characters like '/', '@', ':' are replaced with underscores."""
    assert _sanitize("user@host:path/file") == "user_host_path_file"


def test_leading_trailing_underscores_stripped() -> None:
    """Leading and trailing underscores produced by substitution are stripped."""
    result = _sanitize("@hello@")
    assert not result.startswith("_")
    assert not result.endswith("_")
    assert "hello" in result


def test_all_unsafe_chars_returns_unknown() -> None:
    """A string made entirely of unsafe chars returns 'unknown'."""
    assert _sanitize("@@@") == "unknown"


def test_already_clean_string_unchanged() -> None:
    """A string with only safe characters is returned as-is."""
    assert _sanitize("clean-name_v2.0") == "clean-name_v2.0"
