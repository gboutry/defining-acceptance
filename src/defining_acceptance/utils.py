from contextlib import suppress
from typing import Any


class DeferStack:
    """Helper to manage cleanup functions in a LIFO manner."""

    def __init__(self):
        self._stack = []

    def add(self, func, *args, **kwargs):
        """Add a cleanup function with its arguments."""
        self._stack.append((func, args, kwargs))

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        """Allow the instance to be called like a function to add cleanup."""
        self.add(*args, **kwds)

    def cleanup(self):
        """Run all cleanup functions in reverse order."""
        for func, args, kwargs in reversed(self._stack):
            with suppress(Exception):
                func(*args, **kwargs)
