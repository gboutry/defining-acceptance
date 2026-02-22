from __future__ import annotations

from defining_acceptance.utils import DeferStack


def test_add_stores_function() -> None:
    """add() stores a callable on the stack."""
    stack = DeferStack()
    calls: list[str] = []
    stack.add(calls.append, "a")
    assert len(stack._stack) == 1


def test_call_is_equivalent_to_add() -> None:
    """__call__ is an alias for add()."""
    stack = DeferStack()
    calls: list[str] = []
    stack(calls.append, "b")
    assert len(stack._stack) == 1


def test_cleanup_lifo_order() -> None:
    """cleanup() invokes registered functions in reverse (LIFO) order."""
    stack = DeferStack()
    order: list[int] = []
    stack.add(order.append, 1)
    stack.add(order.append, 2)
    stack.add(order.append, 3)
    stack.cleanup()
    assert order == [3, 2, 1]


def test_cleanup_passes_positional_args() -> None:
    """cleanup() forwards stored positional arguments to the function."""
    stack = DeferStack()
    received: list[tuple] = []
    stack.add(lambda a, b: received.append((a, b)), "x", "y")
    stack.cleanup()
    assert received == [("x", "y")]


def test_cleanup_passes_keyword_args() -> None:
    """cleanup() forwards stored keyword arguments to the function."""
    stack = DeferStack()
    received: list[dict] = []
    stack.add(lambda **kw: received.append(kw), key="val")
    stack.cleanup()
    assert received == [{"key": "val"}]


def test_cleanup_suppresses_exceptions() -> None:
    """cleanup() swallows exceptions so remaining functions still run."""
    stack = DeferStack()
    executed: list[str] = []

    def boom() -> None:
        raise RuntimeError("oops")

    stack.add(boom)
    stack.add(executed.append, "after")
    stack.cleanup()
    assert executed == ["after"]


def test_cleanup_empty_stack_no_error() -> None:
    """cleanup() on an empty DeferStack raises no exception."""
    stack = DeferStack()
    stack.cleanup()  # must not raise


def test_cleanup_calls_all_registered_functions() -> None:
    """After cleanup(), every registered function has been called exactly once."""
    stack = DeferStack()
    results: list[int] = []
    for i in range(5):
        stack.add(results.append, i)
    stack.cleanup()
    assert sorted(results) == [0, 1, 2, 3, 4]
