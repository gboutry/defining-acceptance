from contextlib import suppress


class CleanupStack:
    """Helper to manage cleanup functions in a LIFO manner."""

    def __init__(self):
        self._stack = []

    def add(self, func, *args, **kwargs):
        """Add a cleanup function with its arguments."""
        self._stack.append((func, args, kwargs))

    def cleanup(self):
        """Run all cleanup functions in reverse order."""
        for func, args, kwargs in reversed(self._stack):
            with suppress(Exception):
                func(*args, **kwargs)
