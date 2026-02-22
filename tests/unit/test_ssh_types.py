from __future__ import annotations

import pytest

from defining_acceptance.clients.ssh import CommandError, CommandResult, SSHError


def _make_result(
    returncode: int = 0,
    command: str = "echo hi",
    stdout: str = "hi\n",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestCommandResult:
    def test_succeeded_true_on_zero_returncode(self) -> None:
        """succeeded is True when returncode is 0."""
        result = _make_result(returncode=0)
        assert result.succeeded is True

    def test_succeeded_false_on_nonzero_returncode(self) -> None:
        """succeeded is False when returncode is non-zero."""
        result = _make_result(returncode=1)
        assert result.succeeded is False

    def test_check_returns_self_on_success(self) -> None:
        """check() returns self when the command succeeded."""
        result = _make_result(returncode=0)
        assert result.check() is result

    def test_check_raises_command_error_on_failure(self) -> None:
        """check() raises CommandError when returncode is non-zero."""
        result = _make_result(returncode=2)
        with pytest.raises(CommandError):
            result.check()


class TestCommandError:
    def test_is_exception(self) -> None:
        """CommandError is an Exception subclass."""
        result = _make_result(returncode=1)
        err = CommandError(result)
        assert isinstance(err, Exception)

    def test_result_attribute(self) -> None:
        """result attribute holds the original CommandResult."""
        original = _make_result(returncode=1)
        err = CommandError(original)
        assert err.result is original

    def test_message_contains_command(self) -> None:
        """Error message includes the command string."""
        result = _make_result(command="ls /missing", returncode=2)
        err = CommandError(result)
        assert "ls /missing" in str(err)

    def test_message_contains_returncode(self) -> None:
        """Error message includes the return code."""
        result = _make_result(returncode=127)
        err = CommandError(result)
        assert "127" in str(err)

    def test_message_contains_stdout_and_stderr(self) -> None:
        """Error message includes both stdout and stderr."""
        result = _make_result(returncode=1, stdout="out text", stderr="err text")
        err = CommandError(result)
        assert "out text" in str(err)
        assert "err text" in str(err)


class TestSSHError:
    def test_is_exception(self) -> None:
        """SSHError can be raised and caught as an Exception."""
        with pytest.raises(SSHError):
            raise SSHError("connection refused")

    def test_message_preserved(self) -> None:
        """SSHError preserves the message passed at construction."""
        err = SSHError("timeout")
        assert "timeout" in str(err)
